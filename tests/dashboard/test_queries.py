from datetime import date, datetime

import pytest

from simcore.live import db

from tests.dashboard.conftest import needs_db
from dashboard.backend import queries as q


def _seed_character(s, name="국내형", base_currency="KRW"):
    s.merge(db.CharacterRow(name=name, base_currency=base_currency))


@needs_db
def test_list_characters_roundtrip(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        _seed_character(s, "해외형", "USD")
        s.commit()

    rows = q.list_characters(sf)
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"국내형", "해외형"}
    assert by_name["국내형"]["base_currency"] == "KRW"
    assert by_name["해외형"]["base_currency"] == "USD"


@needs_db
def test_positions_roundtrip(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.PositionRow(character="국내형", symbol="005930", market="KOSPI",
                              quantity=10, avg_price=70000.0, opened_date=date(2026, 1, 5)))
        s.commit()

    rows = q.positions(sf, "국내형")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "005930"
    assert rows[0]["market"] == "KOSPI"
    assert rows[0]["quantity"] == 10
    assert rows[0]["avg_price"] == 70000.0
    assert rows[0]["opened_date"] == date(2026, 1, 5)

    # 다른 캐릭터 데이터는 섞이지 않는다
    assert q.positions(sf, "해외형") == []


@needs_db
def test_trades_roundtrip_and_limit(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        for i in range(3):
            s.add(db.TradeRow(ts=datetime(2026, 1, i + 1, 9, 30), date=date(2026, 1, i + 1),
                               character="국내형", symbol="005930", market="KOSPI", side="BUY",
                               quantity=1, price=70000.0 + i, fee=100.0, tax=0.0,
                               reason="SIGNAL_BUY", green_count=3, red_count=0,
                               fired=["G1", "G2"], realized_pnl=0.0))
        s.commit()

    result = q.trades(sf, "국내형")
    rows = result["items"]
    assert len(rows) == 3
    assert result["total"] == 3
    # 최신 순 정렬
    assert rows[0]["ts"] == datetime(2026, 1, 3, 9, 30)
    assert rows[0]["symbol"] == "005930"
    assert rows[0]["side"] == "BUY"
    assert rows[0]["fired"] == ["G1", "G2"]

    limited = q.trades(sf, "국내형", limit=2)
    assert len(limited["items"]) == 2
    assert limited["total"] == 3  # total은 limit/offset 전 필터 기준 건수


@needs_db
def test_trades_include_decision_type_and_trigger_rule(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.TradeRow(ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
                           character="국내형", symbol="005930", market="KOSPI", side="SELL",
                           quantity=1, price=70000.0, fee=100.0, tax=0.0,
                           reason="FORCED_SELL", green_count=0, red_count=0,
                           fired=[], realized_pnl=-500.0,
                           decision_type="FORCED_SELL", trigger_rule="R18"))
        s.commit()

    rows = q.trades(sf, "국내형")["items"]
    assert rows[0]["decision_type"] == "FORCED_SELL"
    assert rows[0]["trigger_rule"] == "R18"


@needs_db
def test_trades_default_limit_is_20_and_offset_paginates(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        for i in range(25):
            s.add(db.TradeRow(ts=datetime(2026, 1, 1, 9, 0) , date=date(2026, 1, 1),
                               character="국내형", symbol=f"SYM{i:02d}", market="KOSPI",
                               side="BUY", quantity=1, price=1000.0, fee=0.0, tax=0.0,
                               reason="SIGNAL_BUY", green_count=0, red_count=0,
                               fired=[], realized_pnl=0.0))
        s.commit()
    result = q.trades(sf, "국내형")
    assert result["total"] == 25
    assert len(result["items"]) == 20

    page2 = q.trades(sf, "국내형", offset=20)
    assert page2["total"] == 25
    assert len(page2["items"]) == 5
    # 페이지 1과 2는 겹치지 않는다
    ids_page1 = {item["symbol"] for item in result["items"]}
    ids_page2 = {item["symbol"] for item in page2["items"]}
    assert ids_page1.isdisjoint(ids_page2)
    assert len(ids_page1 | ids_page2) == 25


@needs_db
def test_trades_filters_narrow_by_symbol_side_decision_type_and_date(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.TradeRow(ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
                           character="국내형", symbol="005930", market="KOSPI", side="BUY",
                           quantity=1, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_BUY",
                           green_count=0, red_count=0, fired=[], realized_pnl=0.0,
                           decision_type="BUY", trigger_rule="R1"))
        s.add(db.TradeRow(ts=datetime(2026, 1, 2, 9, 30), date=date(2026, 1, 2),
                           character="국내형", symbol="005930", market="KOSPI", side="SELL",
                           quantity=1, price=1100.0, fee=0.0, tax=0.0, reason="SIGNAL_SELL",
                           green_count=0, red_count=0, fired=[], realized_pnl=100.0,
                           decision_type="SELL", trigger_rule="R2"))
        s.add(db.TradeRow(ts=datetime(2026, 1, 3, 9, 30), date=date(2026, 1, 3),
                           character="국내형", symbol="000660", market="KOSPI", side="BUY",
                           quantity=1, price=2000.0, fee=0.0, tax=0.0, reason="SIGNAL_BUY",
                           green_count=0, red_count=0, fired=[], realized_pnl=0.0,
                           decision_type="BUY", trigger_rule="R3"))
        s.commit()

    by_symbol = q.trades(sf, "국내형", symbol="005930")
    assert by_symbol["total"] == 2
    assert {t["symbol"] for t in by_symbol["items"]} == {"005930"}

    by_side = q.trades(sf, "국내형", side="SELL")
    assert by_side["total"] == 1
    assert by_side["items"][0]["symbol"] == "005930"

    by_decision = q.trades(sf, "국내형", decision_type="SELL")
    assert by_decision["total"] == 1
    assert by_decision["items"][0]["decision_type"] == "SELL"

    by_date = q.trades(sf, "국내형", date_from=date(2026, 1, 2), date_to=date(2026, 1, 2))
    assert by_date["total"] == 1
    assert by_date["items"][0]["date"] == date(2026, 1, 2)

    by_date_range = q.trades(sf, "국내형", date_from=date(2026, 1, 1), date_to=date(2026, 1, 2))
    assert by_date_range["total"] == 2


@needs_db
def test_position_lifecycles_groups_entry_to_exit_and_reentry(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        # 생애 1: 진입 -> 부분매도 -> 청산
        s.add(db.TradeRow(ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
                           character="국내형", symbol="005930", market="KOSPI", side="BUY",
                           quantity=10, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_BUY",
                           green_count=0, red_count=0, fired=[], realized_pnl=0.0,
                           decision_type="BUY", trigger_rule="R1"))
        s.add(db.TradeRow(ts=datetime(2026, 1, 2, 9, 30), date=date(2026, 1, 2),
                           character="국내형", symbol="005930", market="KOSPI", side="SELL",
                           quantity=4, price=1100.0, fee=0.0, tax=0.0, reason="SIGNAL_SELL",
                           green_count=0, red_count=0, fired=[], realized_pnl=400.0,
                           decision_type="SELL", trigger_rule="R2"))
        s.add(db.TradeRow(ts=datetime(2026, 1, 3, 9, 30), date=date(2026, 1, 3),
                           character="국내형", symbol="005930", market="KOSPI", side="SELL",
                           quantity=6, price=1200.0, fee=0.0, tax=0.0, reason="SIGNAL_SELL",
                           green_count=0, red_count=0, fired=[], realized_pnl=1200.0,
                           decision_type="SELL", trigger_rule="R2"))
        # 생애 2: 재진입(진행중)
        s.add(db.TradeRow(ts=datetime(2026, 1, 5, 9, 30), date=date(2026, 1, 5),
                           character="국내형", symbol="005930", market="KOSPI", side="BUY",
                           quantity=5, price=1300.0, fee=0.0, tax=0.0, reason="SIGNAL_BUY",
                           green_count=0, red_count=0, fired=[], realized_pnl=0.0,
                           decision_type="BUY", trigger_rule="R3"))
        s.commit()

    lifecycles = q.position_lifecycles(sf, "국내형")
    assert len(lifecycles) == 2

    open_life = next(l for l in lifecycles if l["open"])
    closed_life = next(l for l in lifecycles if not l["open"])

    assert closed_life["entry_date"] == date(2026, 1, 1)
    assert closed_life["exit_date"] == date(2026, 1, 3)
    assert closed_life["realized_pnl_sum"] == 1600.0
    assert closed_life["qty_peak"] == 10
    assert len(closed_life["trades"]) == 3
    assert closed_life["entry_trigger"] == "R1"

    assert open_life["entry_date"] == date(2026, 1, 5)
    assert open_life["exit_date"] is None
    assert open_life["realized_pnl_sum"] == 0.0
    assert open_life["qty_peak"] == 5
    assert len(open_life["trades"]) == 1
    assert open_life["entry_trigger"] == "R3"

    # 진행중 생애가 먼저 온다
    assert lifecycles[0]["open"] is True


@needs_db
def test_position_lifecycles_skips_orphan_sell_without_crashing(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        # 사전 BUY 없이 시작하는 SELL(시드 데이터가 중간부터 시작하는 경우) — 스킵되어야 함
        s.add(db.TradeRow(ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
                           character="국내형", symbol="005930", market="KOSPI", side="SELL",
                           quantity=3, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_SELL",
                           green_count=0, red_count=0, fired=[], realized_pnl=-100.0,
                           decision_type="SELL", trigger_rule=""))
        s.add(db.TradeRow(ts=datetime(2026, 1, 2, 9, 30), date=date(2026, 1, 2),
                           character="국내형", symbol="005930", market="KOSPI", side="BUY",
                           quantity=5, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_BUY",
                           green_count=0, red_count=0, fired=[], realized_pnl=0.0,
                           decision_type="BUY", trigger_rule="R1"))
        s.commit()

    lifecycles = q.position_lifecycles(sf, "국내형")
    assert len(lifecycles) == 1
    assert lifecycles[0]["open"] is True
    assert lifecycles[0]["entry_date"] == date(2026, 1, 2)
    assert len(lifecycles[0]["trades"]) == 1


@needs_db
def test_recent_trades_include_decision_type_and_trigger_rule(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.TradeRow(ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
                           character="국내형", symbol="005930", market="KOSPI", side="SELL",
                           quantity=1, price=70000.0, fee=100.0, tax=0.0,
                           reason="FORCED_SELL", green_count=0, red_count=0,
                           fired=[], realized_pnl=-500.0,
                           decision_type="FORCED_SELL", trigger_rule="R18"))
        s.commit()

    rows = q.recent_trades(sf)
    assert rows[0]["decision_type"] == "FORCED_SELL"
    assert rows[0]["trigger_rule"] == "R18"


@needs_db
def test_benchmark_returns_none_when_not_seeded(sf):
    assert q.benchmark(sf, "국내형") is None


@needs_db
def test_benchmark_roundtrip(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.BenchmarkRow(character="국내형", benchmark_return=0.08,
                               benchmark_name="KOSPI200", ts=datetime(2026, 1, 5, 15, 40)))
        s.commit()

    row = q.benchmark(sf, "국내형")
    assert row is not None
    assert row["benchmark_return"] == pytest.approx(0.08)
    assert row["benchmark_name"] == "KOSPI200"


@needs_db
def test_flows_roundtrip(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.CapitalFlowRow(date=date(2026, 1, 1), character="국내형",
                                 amount_krw=1_000_000.0, fx_rate=1.0))
        s.add(db.CapitalFlowRow(date=date(2026, 1, 2), character="국내형",
                                 amount_krw=-500_000.0, fx_rate=1.0))
        s.commit()

    rows = q.flows(sf, "국내형")
    assert len(rows) == 2
    assert rows[0]["date"] == date(2026, 1, 1)
    assert rows[0]["amount_krw"] == 1_000_000.0
    assert rows[1]["amount_krw"] == -500_000.0


@needs_db
def test_equity_series_roundtrip(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.EquityPoint(ts=datetime(2026, 1, 1, 15, 30), character="국내형",
                              equity_krw=10_000_000.0))
        s.add(db.EquityPoint(ts=datetime(2026, 1, 2, 15, 30), character="국내형",
                              equity_krw=10_500_000.0))
        s.commit()

    series = q.equity_series(sf, "국내형")
    assert series == [
        (datetime(2026, 1, 1, 15, 30), 10_000_000.0),
        (datetime(2026, 1, 2, 15, 30), 10_500_000.0),
    ]


@needs_db
def test_market_status_roundtrip(sf):
    with sf() as s:
        s.add(db.RunState(market="KR", last_open_date=date(2026, 7, 10),
                           last_close_date=date(2026, 7, 10), last_fx_rate=1.0))
        s.add(db.RunState(market="US", last_open_date=date(2026, 7, 9),
                           last_close_date=date(2026, 7, 9), last_fx_rate=1300.0))
        s.commit()

    rows = q.market_status(sf)
    by_market = {r["market"]: r for r in rows}
    assert set(by_market) == {"KR", "US"}
    assert by_market["KR"]["last_close_date"] == "2026-07-10"
    assert by_market["US"]["last_close_date"] == "2026-07-09"
    assert by_market["KR"]["last_open_date"] == "2026-07-10"


@needs_db
def test_market_status_handles_null_dates(sf):
    with sf() as s:
        s.add(db.RunState(market="KR", last_open_date=None, last_close_date=None, last_fx_rate=0.0))
        s.commit()

    rows = q.market_status(sf)
    assert rows == [{"market": "KR", "last_close_date": None, "last_open_date": None}]


@needs_db
def test_cash_roundtrip(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.CashBalance(character="국내형", currency="KRW", amount=5_000_000.0))
        s.commit()

    result = q.cash(sf, "국내형")
    assert result == {"KRW": 5_000_000.0}
    assert q.cash(sf, "해외형") == {}
