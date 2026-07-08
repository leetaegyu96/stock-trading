from datetime import date
from tests.live.conftest import needs_db
from simcore.live.db import CashBalance, TradeRow
from simcore.config import Config
from simcore.engine import Engine, PendingBuy, PendingSell
from simcore.models import Currency, Market, TradeReason
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory


@needs_db
def test_insert_and_query_cash(session):
    session.add(CashBalance(character="국내형", currency="KRW", amount=100.0))
    session.commit()
    row = session.query(CashBalance).filter_by(character="국내형").one()
    assert row.amount == 100.0


@needs_db
def test_persist_rehydrate_roundtrip(session):
    import os
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 7, 6), 1300.0)                 # 3캐릭터 1억 입금
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 7, 6), "005930", Market.KR, 10, 70000.0,
                     __import__("simcore.models", fromlist=["TradeReason"]).TradeReason.SIGNAL_BUY)
    st.cooldowns["000660"] = [Market.KR, 2]
    repo.persist_state(eng)

    eng2 = Engine(Config())
    assert repo.rehydrate(eng2) is True
    s2 = eng2.states["국내형"]
    assert "005930" in s2.portfolio.positions
    assert s2.portfolio.positions["005930"].quantity == 10
    assert abs(s2.portfolio.cash[Currency.KRW] - st.portfolio.cash[Currency.KRW]) < 1e-3
    assert abs(s2.portfolio.cash[Currency.USD] - st.portfolio.cash[Currency.USD]) < 1e-3
    assert s2.cooldowns["000660"][1] == 2


@needs_db
def test_persist_rehydrate_pending_orders_roundtrip(session):
    import os
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 7, 6), 1300.0)
    st = eng.states["국내형"]
    pb = PendingBuy(symbol="000660", market=Market.KR, green_count=8,
                     fired=("R1", "R2", "R3"), change_pct=3.5, volume=123456.0)
    ps = PendingSell(symbol="005930", market=Market.KR, reason=TradeReason.SIGNAL_SELL,
                      red_count=4, fired=("R4", "R5"))
    st.pending_buys.append(pb)
    st.pending_sells.append(ps)
    repo.persist_state(eng)

    eng2 = Engine(Config())
    assert repo.rehydrate(eng2) is True
    s2 = eng2.states["국내형"]

    assert len(s2.pending_buys) == 1
    rb = s2.pending_buys[0]
    assert rb.symbol == pb.symbol
    assert rb.market == pb.market
    assert rb.green_count == pb.green_count
    assert tuple(rb.fired) == pb.fired
    assert rb.change_pct == pb.change_pct
    assert rb.volume == pb.volume

    assert len(s2.pending_sells) == 1
    rs = s2.pending_sells[0]
    assert rs.symbol == ps.symbol
    assert rs.market == ps.market
    assert rs.reason == ps.reason
    assert rs.red_count == ps.red_count
    assert tuple(rs.fired) == ps.fired


@needs_db
def test_run_state_idempotency_and_flow_queue(session):
    import os
    from simcore.live.repository import Repository
    from simcore.live.db import make_engine, make_session_factory
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    rs = repo.get_run_state("KR")
    assert rs.last_close_date is None
    repo.mark_close("KR", date(2026, 7, 6), 1300.0)
    assert repo.get_run_state("KR").last_close_date == date(2026, 7, 6)

    rid = repo.enqueue_flow("국내형", 5_000_000.0)
    pend = repo.pending_flow_requests()
    assert len(pend) == 1 and pend[0].amount_krw == 5_000_000.0
    repo.mark_flow_applied(rid)
    assert repo.pending_flow_requests() == []


@needs_db
def test_daily_bars_upsert_load(session):
    import os, pandas as pd
    from simcore.live.repository import Repository
    from simcore.live.db import make_engine, make_session_factory
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    df = pd.DataFrame({"open":[1.],"high":[2.],"low":[0.5],"close":[1.5],"volume":[10.]},
                      index=pd.to_datetime(["2026-07-06"]))
    repo.upsert_daily_bars("KR", "005930", df)
    got = repo.load_daily_bars("KR", "005930")
    assert got.iloc[0]["close"] == 1.5


@needs_db
def test_append_new_trades_survives_restart(session):
    """재시작(새 Repository + rehydrate로 trades 빈 리스트 시작) 이후에도
    신규 거래가 DB에 정상 기록되어야 한다 (세션 로컬 커서 방식)."""
    import os
    from simcore.live.db import make_engine, make_session_factory
    engine_ = make_engine(os.environ["TEST_DATABASE_URL"])
    sf = make_session_factory(engine_)

    repo1 = Repository(sf)
    eng_a = Engine(Config())
    eng_a.start(date(2026, 7, 6), 1300.0)
    st_a = eng_a.states["국내형"]
    st_a.portfolio.buy(date(2026, 7, 6), "005930", Market.KR, 10, 70000.0,
                        TradeReason.SIGNAL_BUY)
    repo1.append_new_trades(eng_a)
    repo1.persist_state(eng_a)
    with sf() as s:
        assert s.query(TradeRow).filter_by(character="국내형").count() == 1

    # 프로세스 재시작 시뮬레이션: 새 Repository 인스턴스 + 새 엔진(rehydrate로 trades는 빈 리스트로 시작)
    repo2 = Repository(sf)
    eng_b = Engine(Config())
    eng_b.start(date(2026, 7, 6), 1300.0)
    assert repo2.rehydrate(eng_b) is True
    st_b = eng_b.states["국내형"]
    assert st_b.portfolio.trades == []

    st_b.portfolio.buy(date(2026, 7, 6), "000660", Market.KR, 5, 50000.0,
                        TradeReason.SIGNAL_BUY)
    repo2.append_new_trades(eng_b)

    with sf() as s:
        rows = s.query(TradeRow).filter_by(character="국내형").all()
        assert len(rows) == 2
        assert {r.symbol for r in rows} == {"005930", "000660"}
