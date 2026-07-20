from datetime import date
import pytest
from tests.live.conftest import needs_db
from simcore.live.db import CashBalance, TradeRow, SignalStatusRow
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
    # 트레일링이 이미 한 단계 잠긴 상태를 흉내낸다 (peak 갱신 + 잠금선 상향)
    st.portfolio.positions["005930"].peak_price = 120.0
    st.portfolio.positions["005930"].locked_stop_pct = 0.10
    st.cooldowns["000660"] = [Market.KR, 2]
    repo.persist_state(eng)

    eng2 = Engine(Config())
    assert repo.rehydrate(eng2) is True
    s2 = eng2.states["국내형"]
    assert "005930" in s2.portfolio.positions
    assert s2.portfolio.positions["005930"].quantity == 10
    # 재기동 후에도 트레일링 잠금 상태(peak_price/locked_stop_pct)가 유지되어야 한다 —
    # 그렇지 않으면 check_stops 가 stop_px=avg_price(락 0.0)로 계산해 즉시 강제매도된다.
    assert s2.portfolio.positions["005930"].peak_price == 120.0
    assert s2.portfolio.positions["005930"].locked_stop_pct == 0.10
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
    pb = PendingBuy(symbol="000660", market=Market.KR, green_count=8, green_score=20,
                     fired=("R1", "R2", "R3"), change_pct=3.5, volume=123456.0)
    ps = PendingSell(symbol="005930", market=Market.KR, reason=TradeReason.SIGNAL_SELL,
                      red_count=4, red_score=12, fired=("R4", "R5"), partial=True)
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
    assert rb.green_score == pb.green_score
    assert tuple(rb.fired) == pb.fired
    assert rb.change_pct == pb.change_pct
    assert rb.volume == pb.volume

    assert len(s2.pending_sells) == 1
    rs = s2.pending_sells[0]
    assert rs.symbol == ps.symbol
    assert rs.market == ps.market
    assert rs.reason == ps.reason
    assert rs.red_count == ps.red_count
    assert rs.red_score == ps.red_score
    assert rs.partial == ps.partial is True
    assert tuple(rs.fired) == ps.fired


@needs_db
def test_pending_sell_decision_type_survives_rehydrate_then_fills_without_crash(session):
    """감사 CRITICAL: 대기 매도(FORCED_SELL)의 decision_type/trigger_rule이 재시작
    (persist_state → 새 엔진 → rehydrate) 후에도 보존되어야 한다. 보존되지 않으면
    fill_open → append_new_trades 에서 decision_type=None.value → AttributeError로
    라이브 데몬이 크래시한다."""
    import os
    from simcore.models import DecisionType, Market as M
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 7, 6), 1300.0)
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 7, 6), "005930", M.KR, 10, 70000.0, TradeReason.SIGNAL_BUY)
    ps = PendingSell(symbol="005930", market=M.KR, reason=TradeReason.SIGNAL_SELL,
                      red_count=2, red_score=8, fired=("R5", "R23"), partial=False,
                      decision_type=DecisionType.FORCED_SELL, trigger_rule="R5+R23")
    st.pending_sells.append(ps)
    repo.persist_state(eng)

    # 재시작 시뮬레이션: 새 엔진 + rehydrate
    eng2 = Engine(Config())
    eng2.start(date(2026, 7, 6), 1300.0)
    assert repo.rehydrate(eng2) is True
    st2 = eng2.states["국내형"]
    assert len(st2.pending_sells) == 1
    rs = st2.pending_sells[0]
    assert rs.decision_type == DecisionType.FORCED_SELL
    assert rs.trigger_rule == "R5+R23"

    # 체결 + 이력 기록에서 크래시하지 않아야 한다 (P0-1: FORCED_SELL 라벨 보존)
    eng2.fill_open(date(2026, 7, 7), M.KR, {"005930": 60000.0}, fx_rate=1300.0)
    repo.append_new_trades(eng2)

    with sf() as s:
        row = s.query(TradeRow).filter_by(character="국내형", symbol="005930",
                                           side="SELL").one()
        assert row.decision_type == "FORCED_SELL"
        assert row.trigger_rule == "R5+R23"


@needs_db
def test_append_new_trades_persists_decision_type_and_trigger_rule(session):
    """Task 6: Trade.decision_type/trigger_rule(Task 1·2)이 TradeRow에 저장·복원되어야
    한다 — 대시보드(Task 7/8)가 이 두 컬럼을 소비한다."""
    import os
    from simcore.models import DecisionType
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 7, 6), 1300.0)
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 7, 6), "005930", Market.KR, 10, 70000.0,
                      TradeReason.SIGNAL_BUY, decision_type=DecisionType.FORCED_SELL,
                      trigger_rule="R7")
    repo.append_new_trades(eng)

    with sf() as s:
        row = s.query(TradeRow).filter_by(character="국내형", symbol="005930").one()
        assert row.decision_type == "FORCED_SELL"
        assert row.trigger_rule == "R7"


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


@needs_db
def test_replace_signal_status_replaces_all_and_keeps_only_latest(session):
    """전량 교체(market=None): 두 번째 replace 호출 후에는 첫 배치의 행이 남아있지
    않고 두 번째 배치만 조회되어야 한다(최신 마감만 유지). signal_status(character=)
    필터도 SQL where 로 동작해야 한다(Task 5 캐릭터별 조회가 이 필터에 의존)."""
    import os
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    batch1 = [
        {"date": date(2026, 7, 6), "character": "국내형", "symbol": "005930",
         "market": "KR", "kind": "후보", "green_score": 20, "red_score": 0,
         "buy_gate": True, "status": "예약", "block_reason": "", "stop_px": None,
         "trail_px": None, "close": 70000.0},
    ]
    repo.replace_signal_status(batch1)
    with sf() as s:
        assert s.query(SignalStatusRow).count() == 1

    batch2 = [
        {"date": date(2026, 7, 7), "character": "국내형", "symbol": "000660",
         "market": "KR", "kind": "보유", "green_score": 0, "red_score": 5,
         "buy_gate": False, "status": "", "block_reason": "", "stop_px": 65000.0,
         "trail_px": None, "close": 68000.0},
        {"date": date(2026, 7, 7), "character": "해외형", "symbol": "AAPL",
         "market": "US", "kind": "후보", "green_score": 15, "red_score": 2,
         "buy_gate": False, "status": "차단", "block_reason": "점수부족", "stop_px": None,
         "trail_px": None, "close": 190.5},
    ]
    repo.replace_signal_status(batch2)
    with sf() as s:
        assert s.query(SignalStatusRow).count() == 2

    rows = repo.signal_status()
    assert len(rows) == 2
    by_symbol = {r["symbol"]: r for r in rows}
    assert "005930" not in by_symbol  # 첫 배치는 제거됨

    held = by_symbol["000660"]
    assert held["date"] == date(2026, 7, 7)
    assert held["character"] == "국내형"
    assert held["market"] == "KR"
    assert held["kind"] == "보유"
    assert held["red_score"] == 5
    assert held["buy_gate"] is False
    assert held["stop_px"] == pytest.approx(65000.0)
    assert held["trail_px"] is None  # nullable 필드 온전히 보존

    cand = by_symbol["AAPL"]
    assert cand["market"] == "US"
    assert cand["kind"] == "후보"
    assert cand["status"] == "차단"
    assert cand["block_reason"] == "점수부족"
    assert cand["stop_px"] is None
    assert cand["close"] == pytest.approx(190.5)

    # character 필터(pre-fix): "해외형"만 요청하면 "국내형" 행은 섞이지 않는다.
    only_foreign = repo.signal_status(character="해외형")
    assert len(only_foreign) == 1
    assert only_foreign[0]["symbol"] == "AAPL"
    assert only_foreign[0]["character"] == "해외형"


@needs_db
def test_replace_signal_status_market_scoped_preserves_other_markets(session):
    """market 인자를 주면 그 시장 행만 지우고 다시 쓴다 — 다른 시장 최신 마감 상태는
    그대로 보존되어야 한다(라이브 on_close 는 시장 하나씩 마감하므로 필수, Task 3)."""
    import os
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)

    kr_batch = [
        {"date": date(2026, 7, 6), "character": "국내형", "symbol": "005930",
         "market": "KR", "kind": "보유", "green_score": 0, "red_score": 3,
         "buy_gate": False, "status": "", "block_reason": "", "stop_px": 65000.0,
         "trail_px": None, "close": 70000.0},
    ]
    repo.replace_signal_status(kr_batch, market="KR")

    us_batch = [
        {"date": date(2026, 7, 6), "character": "해외형", "symbol": "AAPL",
         "market": "US", "kind": "보유", "green_score": 0, "red_score": 1,
         "buy_gate": False, "status": "", "block_reason": "", "stop_px": 180.0,
         "trail_px": None, "close": 190.0},
    ]
    repo.replace_signal_status(us_batch, market="US")

    rows = repo.signal_status()
    by_symbol = {r["symbol"]: r for r in rows}
    assert set(by_symbol) == {"005930", "AAPL"}  # US 시딩이 KR 행을 지우지 않음

    # KR 을 다음 마감으로 다시 갈아치워도 US 행은 그대로 남는다.
    kr_batch2 = [
        {"date": date(2026, 7, 7), "character": "국내형", "symbol": "000660",
         "market": "KR", "kind": "보유", "green_score": 0, "red_score": 0,
         "buy_gate": False, "status": "", "block_reason": "", "stop_px": 50000.0,
         "trail_px": None, "close": 52000.0},
    ]
    repo.replace_signal_status(kr_batch2, market="KR")
    rows = repo.signal_status()
    by_symbol = {r["symbol"]: r for r in rows}
    assert set(by_symbol) == {"000660", "AAPL"}
    assert by_symbol["AAPL"]["market"] == "US"
