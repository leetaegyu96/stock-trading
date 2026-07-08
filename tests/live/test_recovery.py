import os
import pandas as pd
from datetime import date

from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.live.orchestrator import Orchestrator
from simcore.live.repository import Repository
from simcore.live.recovery import catch_up
from simcore.live.db import make_engine, make_session_factory


def _uptrend(n=80):
    idx = pd.bdate_range("2026-01-01", periods=n)
    base = pd.Series(range(n), index=idx) * 1.0 + 100
    return pd.DataFrame({"open": base, "high": base + 2, "low": base - 1,
                         "close": base + 1, "volume": [1e6] * n}, index=idx)


class DayKis:
    def __init__(self, df):
        self.df = df
    def daily_bars(self, market, symbol, start, end):
        return self.df[self.df.index.date <= end]
    def current_price(self, market, symbol):
        return float(self.df.iloc[-1]["close"])
    def market_cap_ranking(self, n):
        return ["005930"]


@needs_db
def test_catch_up_processes_missed_days(session):
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    df = _uptrend()
    idx = df.index
    eng = Engine(Config())
    eng.start(idx[0].date(), 1300.0)
    orch = Orchestrator(eng, DayKis(df), repo, Config(), fx_provider=lambda d: 1300.0)

    repo.mark_close("KR", idx[40].date(), 1300.0)          # 41일째까지 처리됐다고 가정
    done = catch_up(orch, repo, "KR", idx[70].date(), ["005930"], set())

    assert idx[41].date() in done and idx[69].date() in done
    assert idx[70].date() not in done                      # 오늘은 제외
    assert repo.get_run_state("KR").last_close_date == idx[69].date()


@needs_db
def test_catch_up_noop_when_cold_start(session):
    """run_state 비어있으면(콜드스타트) 복구할 과거 없음 → 빈 리스트, no-op."""
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    df = _uptrend()
    eng = Engine(Config())
    eng.start(df.index[0].date(), 1300.0)
    orch = Orchestrator(eng, DayKis(df), repo, Config(), fx_provider=lambda d: 1300.0)
    assert catch_up(orch, repo, "KR", df.index[70].date(), ["005930"], set()) == []
