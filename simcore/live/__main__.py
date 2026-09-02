"""라이브 데몬 진입점 + 입출금 CLI.

  python -m simcore.live run                         # 데몬 시작(스케줄러)
  python -m simcore.live deposit 국내형 5000000       # 입금 예약(다음 개장 반영)
  python -m simcore.live withdraw 해외형 3000000 --liquidate AAPL   # 출금 예약
"""
from __future__ import annotations
import argparse
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from simcore import data as datamod
from simcore.config import Config
from simcore.engine import Engine
from simcore.live.settings import load_settings, LiveSettings
from simcore.live.ratelimit import RateLimiter
from simcore.live.kis_client import KisClient
from simcore.live.repository import Repository, DbTokenStore
from simcore.live.orchestrator import Orchestrator
from simcore.live.scheduler import LiveScheduler
from simcore.live.recovery import catch_up
from simcore.live import db

_MARKETS = ("KR", "US")


def _fx_provider(repo: Repository):
    """USD/KRW 일별 환율. KIS 전용 FX 엔드포인트가 없어 yfinance(KRW=X) 사용,
    실패 시 마지막 알려진 환율(run_state.last_fx_rate) 폴백."""
    def fx(d: date) -> float:
        try:
            s = datamod.load_fx(d, d, cache_dir=Path("data/cache"))
            return float(s.iloc[-1])
        except Exception:
            return repo.get_run_state("KR").last_fx_rate or 1300.0
    return fx


def _index_provider(cache: Path):
    """가드용 시장 지수 로더. load_index 내부 폴백(pykrx→yfinance)·캐시 재사용.
    start 를 넉넉히 당겨(180일) LOOKBACK_PAD 와 합쳐 최장 SMA(120일) 워밍업을 보장."""
    def load(market: str, upto: date):
        return datamod.load_index(market, upto - timedelta(days=180), upto, cache)
    return load


def _config_from_settings(settings) -> Config:
    """LiveSettings → Config. 모든 env 토글이 기본값이면 Config() 그대로(기존 동작 100% 불변).

    - INTRADAY_ENABLED=true  → intraday_enabled/intraday_scan_minutes 반영
    - SIGNAL_SELL_ENABLED=false → 적신호 점수 매도 OFF("손절/트레일만" 모드)
    - MAX_POSITIONS=N (≠기본 5) → 동시 보유 종목 수 반영
    """
    cfg = Config()
    if settings.intraday_enabled:
        cfg = replace(cfg, rules=replace(cfg.rules,
                      intraday_enabled=True,
                      intraday_scan_minutes=settings.intraday_scan_minutes))
    if not settings.signal_sell_enabled:
        cfg = replace(cfg, rules=replace(cfg.rules, signal_sell_enabled=False))
    if settings.max_positions != cfg.rules.max_positions:
        cfg = replace(cfg, rules=replace(cfg.rules, max_positions=settings.max_positions))
    return cfg


def build_app(settings: LiveSettings):
    engine = db.make_engine(settings.database_url)
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    repo = Repository(sf)
    kis = KisClient(settings, DbTokenStore(sf),
                    RateLimiter(settings.kis_rate_limit_per_sec))
    cfg = _config_from_settings(settings)
    eng = Engine(cfg)
    orch = Orchestrator(eng, kis, repo, cfg, fx_provider=_fx_provider(repo),
                        index_provider=_index_provider(Path("data/cache")))
    return eng, kis, repo, orch


def _holidays_provider(kis):
    """휴장일 집합. KR 은 KIS 휴장일 API, US 는 NYSE 목록으로 정밀화 예정(서브프로젝트 5).
    현재는 주말만 비거래(빈 집합)."""
    def provider(market: str) -> set[date]:
        return set()
    return provider


def _universe_provider(kis, repo, kr_top: int = 30, us_top: int = 30):
    from simcore import universe as uni

    def provider(market: str) -> list[str]:
        today = date.today()
        cached = repo.load_universe(market, today)
        if cached:
            return cached
        if market == "KR":
            syms = kis.market_cap_ranking(kr_top)
        else:
            syms = uni.sp500(Path("data/cache"))[:us_top]
        repo.save_universe(market, syms, today)
        return syms
    return provider


def boot(settings: LiveSettings) -> None:
    eng, kis, repo, orch = build_app(settings)
    if not repo.rehydrate(eng):
        eng.start(date.today(), orch.fx(date.today()))     # 콜드스타트: 3캐릭터 1억
        repo.persist_state(eng)
    # 장중 가드(킬스위치 기준선·휩쏘 캡)도 복원한다(#26). 콜드스타트면 테이블이
    # 비어 있어 no-op — CharacterState 기본값(intraday_day=None 등)이 유지된다.
    repo.rehydrate_intraday_guards(eng)
    holidays = _holidays_provider(kis)
    universe = _universe_provider(kis, repo)
    for market in _MARKETS:
        catch_up(orch, repo, market, date.today(), universe(market), holidays(market))
    sched = LiveScheduler(orch, repo, holidays, universe, cfg=orch.cfg).build()
    sched.start()
    print("[live] 스케줄러 가동. Ctrl+C 로 종료.")
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        print("[live] 종료됨.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="simcore.live")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    dep = sub.add_parser("deposit")
    dep.add_argument("character")
    dep.add_argument("amount", type=float)
    wd = sub.add_parser("withdraw")
    wd.add_argument("character")
    wd.add_argument("amount", type=float)
    wd.add_argument("--liquidate", default="")
    args = ap.parse_args()

    settings = load_settings()
    if args.cmd == "run":
        boot(settings)
        return
    _, _, repo, _ = build_app(settings)
    if args.cmd == "deposit":
        repo.enqueue_flow(args.character, args.amount)
        print(f"입금 예약됨: {args.character} +{args.amount:,.0f} (다음 개장 반영)")
    elif args.cmd == "withdraw":
        liq = tuple(x for x in args.liquidate.split(";") if x)
        repo.enqueue_flow(args.character, -args.amount, liquidate=liq)
        print(f"출금 예약됨: {args.character} -{args.amount:,.0f} "
              f"{'(청산: ' + ','.join(liq) + ')' if liq else ''}(다음 개장 반영)")


if __name__ == "__main__":
    main()
