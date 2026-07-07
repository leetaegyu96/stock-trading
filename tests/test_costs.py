import pytest
from simcore.config import CostModel
from simcore.models import Market, Side
from simcore.costs import trade_costs, krw_to_usd, usd_to_krw, commission_rate

C = CostModel()

def test_kr_buy_has_fee_no_tax():
    fee, tax = trade_costs(Market.KR, Side.BUY, 1_000_000, C)
    assert fee == pytest.approx(150.0)   # 0.015%
    assert tax == 0.0

def test_kr_sell_has_fee_and_tax():
    fee, tax = trade_costs(Market.KR, Side.SELL, 1_000_000, C)
    assert fee == pytest.approx(150.0)
    assert tax == pytest.approx(1500.0)  # 0.15%

def test_us_sell_has_fee_only():
    fee, tax = trade_costs(Market.US, Side.SELL, 10_000, C)
    assert fee == pytest.approx(9.0)     # 0.09%
    assert tax == 0.0

def test_fx_roundtrip_loses_fee_twice():
    usd = krw_to_usd(1_300_000, 1300.0, C.fx_fee)
    assert usd == pytest.approx(1000 * 0.999)
    krw = usd_to_krw(usd, 1300.0, C.fx_fee)
    assert krw == pytest.approx(1_300_000 * 0.999 * 0.999)

def test_commission_rate():
    assert commission_rate(Market.KR, C) == C.kr_commission
    assert commission_rate(Market.US, C) == C.us_commission
