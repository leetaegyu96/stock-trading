"""#26: 장중 가드(킬스위치·휩쏘 캡) 영속 — 재시작 시 리셋 방지.

CharacterState 의 intraday_day/intraday_day_start_equity/intraday_buys/
intraday_sells/intraday_last_sell_ts 는 지금까지 메모리에만 존재해, 데몬이 장중에
재시작하면 _intraday_roll_day 가 재시작 시점 equity 로 day_start_equity 를 재기준해
킬스위치(-5%)와 3회 매수/매도 캡이 조용히 리셋됐다. 이 테스트는 그 5개 필드가
DB 왕복(persist_intraday_guards → rehydrate_intraday_guards) 후에도 그대로
복원되는지, 그리고 그 복원이 실제로 킬스위치 판정에 반영되는지 검증한다."""
from datetime import date, datetime
import pytest
from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory


@needs_db
def test_persist_and_rehydrate_intraday_guards_roundtrip(session):
    import os
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 7, 6), 1300.0)
    st = eng.states["국내형"]
    st.intraday_day = date(2026, 7, 21)
    st.intraday_day_start_equity = 1.0e8
    st.intraday_buys = {"005930": 2}
    st.intraday_sells = {"AAPL": 1}
    st.intraday_last_sell_ts = {"AAPL": datetime(2026, 7, 21, 10, 30)}
    repo.persist_intraday_guards(eng)

    eng2 = Engine(Config())
    eng2.start(date(2026, 7, 6), 1300.0)
    repo.rehydrate_intraday_guards(eng2)
    st2 = eng2.states["국내형"]

    assert st2.intraday_day == date(2026, 7, 21)
    assert st2.intraday_day_start_equity == pytest.approx(1.0e8)
    assert st2.intraday_buys == {"005930": 2}
    assert st2.intraday_sells == {"AAPL": 1}
    assert st2.intraday_last_sell_ts == {"AAPL": datetime(2026, 7, 21, 10, 30)}


@needs_db
def test_rehydrate_intraday_guards_empty_table_is_noop(session):
    import os
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 7, 6), 1300.0)

    repo.rehydrate_intraday_guards(eng)  # 저장된 행이 전혀 없어도 크래시하면 안 됨

    for st in eng.states.values():
        assert st.intraday_day is None
        assert st.intraday_day_start_equity is None
        assert st.intraday_buys == {}
        assert st.intraday_sells == {}
        assert st.intraday_last_sell_ts == {}


@needs_db
def test_killswitch_baseline_survives_restart(session):
    """day_start_equity=1e8 로 마감된 상태가 재시작(새 Engine + rehydrate) 후에도
    보존되어, 현재 equity=0.94e8(-6%, 킬스위치 -5% 초과) 에서 매수가 차단돼야 한다.
    복원되지 않으면(버그) day_start_equity 가 None 이 되어 킬스위치가 무장 해제된다."""
    import os
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 7, 6), 1300.0)
    st = eng.states["국내형"]
    st.intraday_day = date(2026, 7, 21)
    st.intraday_day_start_equity = 1.0e8
    repo.persist_intraday_guards(eng)

    # 재시작 시뮬레이션
    eng2 = Engine(Config())
    eng2.start(date(2026, 7, 6), 1300.0)
    repo.rehydrate_intraday_guards(eng2)
    st2 = eng2.states["국내형"]

    now = datetime(2026, 7, 21, 10, 30)
    assert eng2._intraday_can_buy(st2, "X", now, cur_equity=0.94e8) is False
