from datetime import date
from simcore.models import (
    Market, Currency, MARKET_CURRENCY, Side, TradeReason,
    DailyBar, Position, Trade, CapitalFlow, SymbolSnapshot,
)

def test_market_currency_mapping():
    assert MARKET_CURRENCY[Market.KR] == Currency.KRW
    assert MARKET_CURRENCY[Market.US] == Currency.USD

def test_trade_is_immutable_record():
    t = Trade(date=date(2025, 1, 2), character="국내형", symbol="005930",
              market=Market.KR, side=Side.BUY, quantity=10, price=60000.0,
              fee=90.0, tax=0.0, reason=TradeReason.SIGNAL_BUY,
              green_count=7, fired=("G1", "G2"))
    assert t.realized_pnl == 0.0
    assert t.fired == ("G1", "G2")

def test_snapshot_carries_signal_results():
    s = SymbolSnapshot(symbol="AAPL", market=Market.US, green=("G1",), red=(),
                       close=190.0, change_pct=0.012, volume=1_000_000)
    assert len(s.green) == 1


def test_snapshot_has_score_fields():
    s = SymbolSnapshot("005930", Market.KR, ("G1",), (), 100.0, 0.01, 1000.0,
                       green_score=18, red_score=0, buy_gate=True)
    assert s.green_score == 18 and s.buy_gate is True


def test_position_trailing_fields_default():
    p = Position("005930", Market.KR, 10, 100.0, date(2026, 1, 2))
    assert p.peak_price == 0.0 and p.locked_stop_pct == 0.0
    p.peak_price = 120.0
    assert p.peak_price == 120.0


def test_trailing_stop_reason_exists():
    assert TradeReason.TRAILING_STOP.value == "TRAILING_STOP"


def test_trade_has_decision_fields():
    from simcore.models import Trade, DecisionType, Market, Side
    from datetime import date
    t = Trade(date(2026,1,2), "국내형", "AAA", Market.KR, Side.SELL, 1, 100.0, 0.0, 0.0,
              __import__("simcore.models", fromlist=["TradeReason"]).TradeReason.SIGNAL_SELL,
              realized_pnl=0.0, decision_type=DecisionType.FORCED_SELL, trigger_rule="R18")
    assert t.decision_type == DecisionType.FORCED_SELL and t.trigger_rule == "R18"
    assert list(DecisionType) and DecisionType.BUY.value == "BUY"


def test_intraday_decision_types_exist():
    from simcore.models import DecisionType
    assert DecisionType.INTRADAY_BUY.value == "INTRADAY_BUY"
    assert DecisionType.INTRADAY_SELL.value == "INTRADAY_SELL"
