"""6개월 리플레이 결과를 대시보드 DB(Postgres/SQLite)에 적재한다.

⚠️ 경고: DATABASE_URL 이 가리키는 DB의 거래·자산·포지션 데이터를 전부 지우고
리플레이 결과로 교체한다. 라이브 데몬이 쌓은 실데이터가 있으면 사라진다.
실행하려면 --force 플래그가 필요하다:

    python dashboard/scripts/seed_from_replay.py --force

핵심 불변식(총자산 정합): positions_by_char/cash_by_char(최종 스냅샷)와
daily_bars(같은 스냅샷 시점의 마지막 종가)를 함께 적재하므로,
card_summary.total_asset_krw == equity_curve 마지막 값이 성립한다.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time

import pandas as pd

from simcore.config import Config
from simcore.engine import DEFAULT_CHARACTERS
from simcore.live import db
from simcore.replay import DataBundle, ReplayResult, run_replay

_EQUITY_TIME = time(15, 40)
_TRADE_TIME = time(9, 1)
_MAX_BARS_PER_SYMBOL = 5

_BASE_CURRENCY_BY_NAME = {s.name: s.base_currency.value for s in DEFAULT_CHARACTERS}

# seed_demo.py 와 동일한 초기화 테이블 목록
_TABLES_TO_CLEAR = (
    db.EquityPoint, db.TradeRow, db.CapitalFlowRow, db.FlowRequest,
    db.PositionRow, db.CashBalance, db.Cooldown, db.PendingOrder,
    db.DailyBarRow, db.UniverseRow, db.CharacterRow,
)


def _fired_list(raw) -> list[str]:
    """trades DataFrame 의 fired 컬럼(';' 조인 문자열) → 리스트."""
    if not raw:
        return []
    return [f for f in str(raw).split(";") if f]


def _final_equity_krw(name: str, result: ReplayResult, fx_rate: float) -> float:
    """dashboard.backend.summary.card_summary 가 계산하는 방식과 동일하게
    최종 스냅샷(cash_by_char/positions_by_char/last_close)을 fx_rate 로 재평가한다.

    replay 내부의 equity 마지막 값은 리플레이 마지막 거래일의 (그날그날 다른) fx 로
    계산되어 있는데, 카드는 조회 시점의 fx_rate 로 USD 자산을 평가하므로, 이 둘을
    맞추지 않으면 fx 가 날짜별로 변하는 경우(범용형/해외형처럼 USD 를 보유한 캐릭터)
    total_asset_krw != equity 마지막 값이 되어 정합이 깨진다."""
    cash = result.cash_by_char.get(name, {})
    total = float(cash.get("KRW", 0.0)) + float(cash.get("USD", 0.0)) * fx_rate
    for p in result.positions_by_char.get(name, []):
        px = result.last_close.get(p["symbol"], p["avg_price"])
        value = p["quantity"] * px
        total += value * fx_rate if p["market"] == "US" else value
    return total


def seed_replay_result_into_db(result: ReplayResult, bundle: DataBundle, sf,
                                fx_rate: float = 1300.0,
                                initial_capital_krw: float = 100_000_000.0) -> None:
    """리플레이 결과(result)와 그 입력 데이터(bundle)를 세션 팩토리 sf 의 DB에 적재한다.

    positions_by_char/cash_by_char(최종 포지션·현금)와 daily_bars(같은 최종 스냅샷의
    마지막 종가)를 함께 써서, card_summary.total_asset_krw == equity 마지막 값이
    성립하도록 한다. 마지막 EquityPoint 는 카드가 쓰는 것과 동일한 fx_rate 로
    재평가한 값(_final_equity_krw)으로 덮어써서, fx 가 날짜별로 변해도(USD 보유
    캐릭터 포함) 정합이 정확히 성립하도록 한다.
    """
    with sf() as s:
        # ---- 0. 기존 데이터 초기화 ----
        for t in _TABLES_TO_CLEAR:
            s.query(t).delete()
        s.commit()

        names = list(result.equity.columns)
        first_date: date = result.equity.index.min().date()
        last_ts = result.equity.index.max()
        last_date: date = last_ts.date()
        fx0 = float(bundle.fx.asof(pd.Timestamp(first_date))) if len(bundle.fx) else fx_rate

        # ---- 1. 캐릭터 ----
        for name in names:
            s.add(db.CharacterRow(name=name,
                                  base_currency=_BASE_CURRENCY_BY_NAME.get(name, "KRW")))

        # ---- 2. 입출금: 초기입금(제외 대상, 첫 행) + flows_by_char 순입출금 ----
        for name in names:
            s.add(db.CapitalFlowRow(date=first_date, character=name,
                                    amount_krw=initial_capital_krw, fx_rate=fx0))
            flow = result.flows_by_char.get(name)
            if flow is None:
                continue
            for ts, amount in flow.items():
                s.add(db.CapitalFlowRow(date=pd.Timestamp(ts).date(), character=name,
                                        amount_krw=float(amount), fx_rate=fx_rate))

        # ---- 3. 자산곡선 ----
        # 마지막(최신) 포인트는 card_summary 와 동일한 fx_rate 로 재평가한 값으로
        # 덮어써서 총자산 정합을 정확히 맞춘다(Fix 1) — 그 이전 포인트들은 리플레이
        # 당시의 (날짜별로 다를 수 있는) fx 로 계산된 값을 그대로 둔다(스파크라인용).
        for name in names:
            col = result.equity[name]
            final_krw = _final_equity_krw(name, result, fx_rate)
            for ts, equity_krw in col.items():
                d = pd.Timestamp(ts).date()
                value = final_krw if ts == last_ts else float(equity_krw)
                s.add(db.EquityPoint(ts=datetime.combine(d, _EQUITY_TIME),
                                     character=name, equity_krw=float(value)))

        # ---- 4. 포지션 (최종 스냅샷) ----
        for name, positions in result.positions_by_char.items():
            for p in positions:
                s.add(db.PositionRow(
                    character=name, symbol=p["symbol"], market=p["market"],
                    quantity=int(p["quantity"]), avg_price=float(p["avg_price"]),
                    opened_date=p["opened"], peak_price=float(p.get("peak_price", 0.0)),
                    locked_stop_pct=float(p.get("locked_stop_pct", 0.0))))

        # ---- 5. 현금 (최종 스냅샷) ----
        for name, cash in result.cash_by_char.items():
            for currency in ("KRW", "USD"):
                s.add(db.CashBalance(character=name, currency=currency,
                                     amount=float(cash.get(currency, 0.0))))

        # ---- 6. 거래내역 ----
        trades = result.trades
        if trades is not None and not trades.empty:
            for row in trades.itertuples(index=False):
                d = pd.Timestamp(row.date).date()
                s.add(db.TradeRow(
                    ts=datetime.combine(d, _TRADE_TIME), date=d, character=row.character,
                    symbol=row.symbol, market=row.market, side=row.side,
                    quantity=int(row.quantity), price=float(row.price),
                    fee=float(row.fee), tax=float(row.tax), reason=row.reason,
                    green_count=int(row.green_count), red_count=int(row.red_count),
                    green_score=int(row.green_score), red_score=int(row.red_score),
                    fired=_fired_list(row.fired), realized_pnl=float(row.realized_pnl)))

        # ---- 7. 일봉 (최종 스냅샷 시점까지, 심볼당 최근 ≤5봉) ----
        # last_close 정합을 위해 마지막 봉이 replay 가 실제로 처리한 마지막 날짜(last_date)
        # 이하의 실제 데이터여야 한다 (bundle 이 replay 구간보다 더 뒤까지 있을 수 있음).
        for market, data in (("KR", bundle.kr), ("US", bundle.us)):
            for symbol, df in data.items():
                sliced = df[df.index.map(lambda ts: ts.date()) <= last_date]
                if sliced.empty:
                    continue
                tail = sliced.tail(_MAX_BARS_PER_SYMBOL)
                for ts, bar in tail.iterrows():
                    s.add(db.DailyBarRow(
                        market=market, symbol=symbol, date=pd.Timestamp(ts).date(),
                        open=float(bar["open"]), high=float(bar["high"]),
                        low=float(bar["low"]), close=float(bar["close"]),
                        volume=float(bar["volume"])))

        s.commit()


def _cli() -> None:
    if "--force" not in sys.argv:
        sys.exit("이 스크립트는 DB를 초기화합니다. 의도가 맞으면 --force 를 붙여 실행하세요.")

    import argparse
    import os
    from pathlib import Path

    from simcore import data as datamod, universe

    ap = argparse.ArgumentParser(description="리플레이 결과를 대시보드 DB에 시딩")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--start", default="2026-01-09")
    ap.add_argument("--end", default="2026-07-09")
    ap.add_argument("--kr-top", type=int, default=50)
    ap.add_argument("--us-top", type=int, default=50)
    ap.add_argument("--cache", default="data/cache")
    args = ap.parse_args(sys.argv[1:])

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cache = Path(args.cache)

    cfg = Config()
    kr_syms = universe.kospi200(cache, start)[: args.kr_top]
    us_syms = universe.sp500(cache)[: args.us_top]
    print(f"[seed_from_replay] KR {len(kr_syms)}종목, US {len(us_syms)}종목 로딩 중...")
    bundle = DataBundle(
        kr=datamod.load_kr_daily(kr_syms, start, end, cache),
        us=datamod.load_us_daily(us_syms, start, end, cache),
        fx=datamod.load_fx(start, end, cache),
    )
    print(f"[seed_from_replay] 리플레이 실행 {start} ~ {end} ...")
    result = run_replay(cfg, bundle, start, end)

    url = os.environ["DATABASE_URL"]
    engine = db.make_engine(url)
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    fx_rate = float(bundle.fx.iloc[-1])
    seed_replay_result_into_db(result, bundle, sf, fx_rate=fx_rate,
                               initial_capital_krw=cfg.initial_capital_krw)
    print("[seed_from_replay] 시딩 완료.")


if __name__ == "__main__":
    _cli()
