from datetime import date
from tests.live.conftest import needs_db
from simcore.live.db import CashBalance
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
