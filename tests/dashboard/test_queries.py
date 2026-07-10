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

    rows = q.trades(sf, "국내형")
    assert len(rows) == 3
    # 최신 순 정렬
    assert rows[0]["ts"] == datetime(2026, 1, 3, 9, 30)
    assert rows[0]["symbol"] == "005930"
    assert rows[0]["side"] == "BUY"
    assert rows[0]["fired"] == ["G1", "G2"]

    limited = q.trades(sf, "국내형", limit=2)
    assert len(limited) == 2


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

    rows = q.trades(sf, "국내형")
    assert rows[0]["decision_type"] == "FORCED_SELL"
    assert rows[0]["trigger_rule"] == "R18"


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
def test_cash_roundtrip(sf):
    with sf() as s:
        _seed_character(s, "국내형", "KRW")
        s.add(db.CashBalance(character="국내형", currency="KRW", amount=5_000_000.0))
        s.commit()

    result = q.cash(sf, "국내형")
    assert result == {"KRW": 5_000_000.0}
    assert q.cash(sf, "해외형") == {}
