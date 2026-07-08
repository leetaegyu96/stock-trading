import os, pandas as pd, pytest
from datetime import date
from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.live.orchestrator import Orchestrator
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory


class FakeKis:
    def __init__(self, bars): self.bars = bars     # {(market,symbol): DataFrame}
    def daily_bars(self, market, symbol, start, end): return self.bars[(market, symbol)]
    def current_price(self, market, symbol): return float(self.bars[(market, symbol)].iloc[-1]["close"])
    def market_cap_ranking(self, n): return ["005930"]


def _uptrend(n=80):
    idx = pd.bdate_range("2026-01-01", periods=n)
    base = pd.Series(range(n), index=idx) * 1.0 + 100
    return pd.DataFrame({"open": base, "high": base + 2, "low": base - 1,
                         "close": base + 1, "volume": [1e6] * n}, index=idx)


@needs_db
def test_on_close_persists_signals_and_equity(session):
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    d0 = date(2026, 1, 1)
    eng.start(d0, 1300.0)
    kis = FakeKis({("KR", "005930"): _uptrend()})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    last = _uptrend().index[-1].date()
    orch.on_close(last, "KR", ["005930"])
    # equity 기록됨 + run_state 갱신 + 중복 호출 무시
    assert repo.get_run_state("KR").last_close_date == last
    orch.on_close(last, "KR", ["005930"])   # 멱등: 재실행 무시


@needs_db
def test_on_close_values_cross_market_holding_at_last_price(session):
    """범용형이 US 종목 보유 + KR on_close 시, 반대 시장 leg 가 평단(원가)이 아니라
    최근가로 평가되는지 (Important #1 회귀 가드)."""
    from simcore.models import Market, TradeReason
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    st = eng.states["범용형"]
    st.portfolio.convert_to_usd(1000.0, 1300.0)
    st.portfolio.buy(date(2026, 1, 2), "AAPL", Market.US, 5, 150.0, TradeReason.SIGNAL_BUY)
    # US 보유 종목의 일봉 캐시 (마지막 종가 190, 평단 150 과 다름)
    us_bars = pd.DataFrame({"open": [188.], "high": [192.], "low": [187.],
                            "close": [190.], "volume": [1e6]},
                           index=pd.to_datetime(["2026-01-05"]))
    repo.upsert_daily_bars("US", "AAPL", us_bars)
    kis = FakeKis({("KR", "005930"): _uptrend()})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    orch.on_close(_uptrend().index[-1].date(), "KR", ["005930"])
    # KR 마감인데도 US 보유 종목이 최근가(190)로 시드됨 — 원가(150) 폴백 아님
    assert orch._last_price["AAPL"] == 190.0


@needs_db
def test_on_close_idempotent_no_duplicate_equity(session):
    """같은 날 on_close 2회 호출 시 equity_curve 행이 늘지 않는다 (멱등 강화)."""
    from simcore.live import db
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    kis = FakeKis({("KR", "005930"): _uptrend()})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    last = _uptrend().index[-1].date()
    orch.on_close(last, "KR", ["005930"])
    with sf() as s:
        n1 = s.query(db.EquityPoint).count()
    orch.on_close(last, "KR", ["005930"])       # no-op
    with sf() as s:
        n2 = s.query(db.EquityPoint).count()
    assert n1 == n2 and n1 > 0
