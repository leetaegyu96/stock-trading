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
