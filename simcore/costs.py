"""수수료·세금·환전 비용. 요율은 config.CostModel 에서만 온다."""
from __future__ import annotations
from simcore.config import CostModel
from simcore.models import Market, Side


def commission_rate(market: Market, c: CostModel) -> float:
    return c.kr_commission if market == Market.KR else c.us_commission


def trade_costs(market: Market, side: Side, gross: float, c: CostModel) -> tuple[float, float]:
    fee = gross * commission_rate(market, c)
    tax = gross * c.kr_tax if (market == Market.KR and side == Side.SELL) else 0.0
    return fee, tax


def krw_to_usd(amount_krw: float, fx_rate: float, fee_rate: float) -> float:
    return amount_krw / fx_rate * (1 - fee_rate)


def usd_to_krw(amount_usd: float, fx_rate: float, fee_rate: float) -> float:
    return amount_usd * fx_rate * (1 - fee_rate)
