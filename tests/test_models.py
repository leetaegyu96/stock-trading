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
