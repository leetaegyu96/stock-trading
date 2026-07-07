from datetime import date
import pytest
from simcore.config import Config
from simcore.models import Market, Currency, TradeReason, Side
from simcore.portfolio import Portfolio, InsufficientCashError

CFG = Config()
D = date(2025, 1, 6)

def krw_portfolio(cash=10_000_000):
    p = Portfolio("국내형", Currency.KRW, CFG)
    p.deposit(D, cash, fx_rate=1300.0)
    return p

def test_buy_deducts_cash_and_fee():
    p = krw_portfolio()
    t = p.buy(D, "005930", Market.KR, 100, 60000.0, TradeReason.SIGNAL_BUY, green_count=7)
    gross = 100 * 60000.0
    assert p.cash[Currency.KRW] == pytest.approx(10_000_000 - gross - gross * 0.00015)
    assert p.positions["005930"].quantity == 100
    assert t.side == Side.BUY and t.green_count == 7

def test_buy_insufficient_cash_raises():
    p = krw_portfolio(cash=1_000_000)
    with pytest.raises(ValueError):
        p.buy(D, "005930", Market.KR, 100, 60000.0, TradeReason.SIGNAL_BUY)

def test_sell_realizes_pnl_after_costs():
    p = krw_portfolio()
    p.buy(D, "005930", Market.KR, 100, 60000.0, TradeReason.SIGNAL_BUY)
    t = p.sell(date(2025, 1, 10), "005930", 66000.0, TradeReason.TAKE_PROFIT)
    gross = 100 * 66000.0
    fee, tax = gross * 0.00015, gross * 0.0015
    assert t.realized_pnl == pytest.approx(100 * 6000.0 - fee - tax)
    assert "005930" not in p.positions

def test_accounting_invariant_cash_plus_positions():
    p = krw_portfolio()
    p.buy(D, "005930", Market.KR, 100, 60000.0, TradeReason.SIGNAL_BUY)
    eq = p.equity_krw({"005930": 60000.0}, fx_rate=1300.0)
    gross = 100 * 60000.0
    assert eq == pytest.approx(10_000_000 - gross * 0.00015)  # 총자산 = 초기 - 수수료

def test_usd_base_deposit_converts():
    p = Portfolio("해외형", Currency.USD, CFG)
    p.deposit(D, 1_300_000, fx_rate=1300.0)
    assert p.cash[Currency.USD] == pytest.approx(1000 * 0.999)
    assert p.cash[Currency.KRW] == 0.0

def test_withdraw_insufficient_raises_with_shortfall():
    p = krw_portfolio(cash=1_000_000)
    with pytest.raises(InsufficientCashError) as e:
        p.withdraw(D, 3_000_000, fx_rate=1300.0)
    assert e.value.shortfall_krw == pytest.approx(2_000_000)
    assert len(p.flows) == 1  # 실패한 출금은 원장에 남지 않음 (입금 1건만)

def test_flows_ledger_records_deposit_and_withdrawal():
    p = krw_portfolio()
    p.withdraw(D, 2_000_000, fx_rate=1300.0)
    assert [f.amount_krw for f in p.flows] == [10_000_000, -2_000_000]
    assert p.cash[Currency.KRW] == pytest.approx(8_000_000)
