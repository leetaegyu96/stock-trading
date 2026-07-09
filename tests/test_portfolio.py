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

def test_convert_to_usd_deducts_krw_with_fee():
    p = krw_portfolio()
    p.convert_to_usd(1000.0, fx_rate=1300.0)
    assert p.cash[Currency.USD] == pytest.approx(1000.0)
    assert p.cash[Currency.KRW] == pytest.approx(10_000_000 - 1000.0 * 1300.0 / 0.999)

def test_convert_all_usd_to_krw():
    p = krw_portfolio()
    p.convert_to_usd(1000.0, fx_rate=1300.0)
    krw_before = p.cash[Currency.KRW]
    p.convert_all_usd_to_krw(fx_rate=1300.0)
    assert p.cash[Currency.USD] == 0.0
    assert p.cash[Currency.KRW] == pytest.approx(krw_before + 1000.0 * 1300.0 * 0.999)

def test_rebuy_held_symbol_raises():
    p = krw_portfolio()
    p.buy(D, "005930", Market.KR, 10, 60000.0, TradeReason.SIGNAL_BUY)
    with pytest.raises(ValueError):
        p.buy(D, "005930", Market.KR, 10, 60000.0, TradeReason.SIGNAL_BUY)

def test_invariant_violation_raises_even_without_asserts():
    p = krw_portfolio()
    p.cash[Currency.KRW] = -1.0
    with pytest.raises(RuntimeError):
        p.assert_invariants()


def _pf():
    pf = Portfolio("t", Currency.KRW, Config())
    pf.deposit(date(2026, 1, 2), 100_000_000.0, 1300.0)
    return pf


def test_buy_initializes_trailing_state():
    pf = _pf()
    pf.buy(date(2026, 1, 2), "005930", Market.KR, 100, 1000.0,
           TradeReason.SIGNAL_BUY, green_score=20)
    pos = pf.positions["005930"]
    assert pos.peak_price == 1000.0
    assert pos.locked_stop_pct == Config().rules.stop_loss_pct
    assert pf.trades[-1].green_score == 20


def test_partial_sell_keeps_position_reduced():
    pf = _pf()
    pf.buy(date(2026, 1, 2), "005930", Market.KR, 100, 1000.0, TradeReason.SIGNAL_BUY)
    cash_after_buy = pf.cash[Currency.KRW]
    pf.sell(date(2026, 1, 3), "005930", 1100.0, TradeReason.SIGNAL_SELL, quantity=50)
    assert "005930" in pf.positions
    assert pf.positions["005930"].quantity == 50
    assert pf.cash[Currency.KRW] > cash_after_buy         # 매도 대금 유입
    assert pf.trades[-1].quantity == 50
    assert pf.trades[-1].realized_pnl != 0.0


def test_full_sell_pops_position():
    pf = _pf()
    pf.buy(date(2026, 1, 2), "005930", Market.KR, 100, 1000.0, TradeReason.SIGNAL_BUY)
    pf.sell(date(2026, 1, 3), "005930", 1100.0, TradeReason.SIGNAL_SELL)
    assert "005930" not in pf.positions
