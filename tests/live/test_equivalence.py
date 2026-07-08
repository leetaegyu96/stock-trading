"""★ 라이브 orchestrator ≡ run_replay 동치성 (이 서브프로젝트의 안전벨트).

같은 일봉 데이터를 (A) run_replay 와 (B) 라이브 orchestrator(on_open→on_close 루프)에
각각 주입하고, 신호 구동 거래(종목·매매·수량 시퀀스)가 완전히 동일한지 검증한다.

손익절/익절은 리플레이(당일 OHLC 근사)와 라이브(5분 현재가 샘플링)의 데이터 입도가
본질적으로 달라 동치 대상이 아니다. 따라서 이 테스트는 손절 -99% / 익절 +999% 로
설정해 R7/R10 을 사실상 비활성화하고, 순수 신호→체결 경로만 비교한다(공유 코드경로).
"""
import os
from dataclasses import replace
from datetime import date
import numpy as np
import pandas as pd

from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.replay import run_replay, DataBundle
from simcore.live.orchestrator import Orchestrator
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory
from simcore.live import calendar as cal


def _rise_fall(base0: float, peak: float, n: int = 140) -> pd.DataFrame:
    """상승→하락 결정론 시계열. 상승기엔 매수 신호(G1·G2·G4·G7), 하락기엔
    매도 신호(R1·R2·R4)가 켜지도록 워밍업(60거래일) 이후 충분한 추세를 준다."""
    half = n // 2
    up = np.linspace(base0, peak, half)
    down = np.linspace(peak, base0 * 1.2, n - half)
    close = pd.Series(np.concatenate([up, down]),
                      index=pd.bdate_range("2026-01-01", periods=n))
    opens = close.shift(1).fillna(close.iloc[0])
    return pd.DataFrame({"open": opens, "high": close + 1.0, "low": close - 1.0,
                         "close": close, "volume": [1e6] * n}, index=close.index)


@needs_db
def test_live_orchestrator_equals_replay(session):
    kr = {"005930": _rise_fall(100.0, 200.0), "000660": _rise_fall(80.0, 160.0)}
    idx = kr["005930"].index
    fx = pd.Series([1300.0] * len(idx), index=idx)
    bundle = DataBundle(kr=kr, us={}, fx=fx)
    # 손익절 비활성화 → 순수 신호 경로만. 매수 임계값 4(상승기 G1·G2·G4·G7)로 거래 유도.
    base = Config()
    cfg = replace(base, rules=replace(base.rules, buy_threshold=4,
                                      stop_loss_pct=-0.99, take_profit_pct=9.99))
    start, end = idx[0].date(), idx[-1].date()

    # (A) 리플레이
    rep = run_replay(cfg, bundle, start, end)
    rep_kr = rep.trades[rep.trades.character == "국내형"] if not rep.trades.empty else rep.trades
    rep_seq = [(r.symbol, r.side, r.quantity) for r in rep_kr.itertuples()]

    # (B) 라이브 orchestrator: 같은 데이터를 하루씩 on_open→on_close
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(cfg)
    eng.start(start, 1300.0)

    class DayKis:
        def __init__(self, kr):
            self.kr = kr
            self.today = None
        def daily_bars(self, market, symbol, s, e):
            df = self.kr[symbol]
            return df[df.index.date <= e]
        def current_price(self, market, symbol):
            # 개장 체결가 = 당일 시가 (run_replay 의 fill_open 과 동일)
            return float(self.kr[symbol].loc[pd.Timestamp(self.today), "open"])
        def market_cap_ranking(self, n):
            return list(self.kr)[:n]

    kis = DayKis(kr)
    orch = Orchestrator(eng, kis, repo, cfg, fx_provider=lambda d: 1300.0)
    for d in cal.trading_days_between(start, end, "KR", set()):
        kis.today = d
        orch.on_open(d, "KR", list(kr))     # 전일 예약분 체결
        orch.on_close(d, "KR", list(kr))    # 당일 신호 예약
    live_seq = [(t.symbol, t.side.value, t.quantity)
                for t in eng.states["국내형"].portfolio.trades]

    assert rep_seq, "리플레이가 거래를 하나도 만들지 못함 — 픽스처/임계값 조정 필요"
    assert live_seq == rep_seq
