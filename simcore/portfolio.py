"""캐릭터별 회계: 현금(통화별)·포지션·거래·입출금 원장. 모든 변경 후 불변식 검사."""
from __future__ import annotations
from datetime import date as Date

from simcore.config import Config
from simcore import costs as costmod
from simcore.models import (
    CapitalFlow, Currency, DecisionType, Market, MARKET_CURRENCY, Position, Side, Trade,
    TradeReason,
)

_EPS = 1e-6


class InsufficientCashError(Exception):
    def __init__(self, character: str, shortfall_krw: float):
        self.character = character
        self.shortfall_krw = shortfall_krw
        super().__init__(
            f"{character}: 출금 부족액 {shortfall_krw:,.0f} KRW - 청산할 종목을 지정하세요")


class Portfolio:
    def __init__(self, character: str, base_currency: Currency, config: Config):
        self.character = character
        self.base_currency = base_currency
        self.config = config
        self.cash: dict[Currency, float] = {Currency.KRW: 0.0, Currency.USD: 0.0}
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.flows: list[CapitalFlow] = []

    # ---- 입출금 ----
    def deposit(self, d: Date, amount_krw: float, fx_rate: float) -> None:
        if self.base_currency == Currency.USD:
            self.cash[Currency.USD] += costmod.krw_to_usd(
                amount_krw, fx_rate, self.config.costs.fx_fee)
        else:
            self.cash[Currency.KRW] += amount_krw
        self.flows.append(CapitalFlow(d, self.character, amount_krw, fx_rate))
        self.assert_invariants()

    def withdraw(self, d: Date, amount_krw: float, fx_rate: float) -> None:
        if self.base_currency == Currency.USD:
            needed_usd = amount_krw / (fx_rate * (1 - self.config.costs.fx_fee))
            if self.cash[Currency.USD] + _EPS < needed_usd:
                short = (needed_usd - self.cash[Currency.USD]) * fx_rate
                raise InsufficientCashError(self.character, short)
            self.cash[Currency.USD] -= needed_usd
        else:
            if self.cash[Currency.KRW] + _EPS < amount_krw:
                raise InsufficientCashError(
                    self.character, amount_krw - self.cash[Currency.KRW])
            self.cash[Currency.KRW] -= amount_krw
        self.flows.append(CapitalFlow(d, self.character, -amount_krw, fx_rate))
        self.assert_invariants()

    # ---- 매매 ----
    def buy(self, d: Date, symbol: str, market: Market, quantity: int, price: float,
            reason: TradeReason, green_count: int = 0, green_score: int = 0,
            fired: tuple[str, ...] = (), decision_type: DecisionType = DecisionType.BUY,
            trigger_rule: str = "") -> Trade:
        if symbol in self.positions:
            raise ValueError(f"{self.character}: {symbol} 이미 보유 중 - 재매수 금지")
        cur = MARKET_CURRENCY[market]
        gross = quantity * price
        fee, tax = costmod.trade_costs(market, Side.BUY, gross, self.config.costs)
        total = gross + fee + tax
        if self.cash[cur] + _EPS < total:
            raise ValueError(f"{self.character}: {symbol} 매수 현금 부족 "
                             f"(필요 {total:,.0f} {cur}, 보유 {self.cash[cur]:,.0f})")
        self.cash[cur] -= total
        self.positions[symbol] = Position(
            symbol, market, quantity, price, d,
            peak_price=price, locked_stop_pct=self.config.rules.stop_loss_pct)
        trade = Trade(d, self.character, symbol, market, Side.BUY, quantity, price,
                      fee, tax, reason, green_count=green_count, fired=fired,
                      green_score=green_score, decision_type=decision_type,
                      trigger_rule=trigger_rule)
        self.trades.append(trade)
        self.assert_invariants()
        return trade

    def sell(self, d: Date, symbol: str, price: float, reason: TradeReason,
             quantity: int | None = None, red_count: int = 0, red_score: int = 0,
             fired: tuple[str, ...] = (), decision_type: DecisionType = DecisionType.FULL_SELL,
             trigger_rule: str = "") -> Trade:
        pos = self.positions[symbol]
        qty = pos.quantity if quantity is None else min(quantity, pos.quantity)
        cur = MARKET_CURRENCY[pos.market]
        gross = qty * price
        fee, tax = costmod.trade_costs(pos.market, Side.SELL, gross, self.config.costs)
        self.cash[cur] += gross - fee - tax
        pnl = (price - pos.avg_price) * qty - fee - tax
        # 반올림(max(1, qty*fraction))으로 부분매도 수량이 잔량 전체를 청산하는 경우
        # (예: quantity==1) "부분 매도" 라벨이 남으면 설명·수량이 불일치하므로 승격한다.
        if decision_type == DecisionType.PARTIAL_SELL and qty >= pos.quantity:
            decision_type = DecisionType.FULL_SELL
        if qty >= pos.quantity:
            self.positions.pop(symbol)
        else:
            pos.quantity -= qty                       # 부분매도: 평단·트레일링 유지
        trade = Trade(d, self.character, symbol, pos.market, Side.SELL, qty,
                      price, fee, tax, reason, red_count=red_count, fired=fired,
                      red_score=red_score, realized_pnl=pnl, decision_type=decision_type,
                      trigger_rule=trigger_rule)
        self.trades.append(trade)
        self.assert_invariants()
        return trade

    # ---- 환전 (범용형: KRW 베이스로 미국 주식 거래 시) ----
    def convert_to_usd(self, target_usd: float, fx_rate: float) -> None:
        fee = self.config.costs.fx_fee
        krw_cost = target_usd * fx_rate / (1 - fee)
        if self.cash[Currency.KRW] + _EPS < krw_cost:
            raise ValueError(f"{self.character}: 환전 원화 부족")
        self.cash[Currency.KRW] -= krw_cost
        self.cash[Currency.USD] += target_usd
        self.assert_invariants()

    def convert_all_usd_to_krw(self, fx_rate: float) -> None:
        usd = self.cash[Currency.USD]
        if usd <= 0:
            return
        self.cash[Currency.USD] = 0.0
        self.cash[Currency.KRW] += costmod.usd_to_krw(usd, fx_rate, self.config.costs.fx_fee)
        self.assert_invariants()

    # ---- 평가 ----
    def equity_krw(self, prices: dict[str, float], fx_rate: float) -> float:
        total = self.cash[Currency.KRW] + self.cash[Currency.USD] * fx_rate
        for sym, pos in self.positions.items():
            px = prices.get(sym, pos.avg_price)
            value = pos.quantity * px
            total += value * fx_rate if pos.market == Market.US else value
        return total

    def assert_invariants(self) -> None:
        for cur, amt in self.cash.items():
            if amt < -_EPS:
                raise RuntimeError(f"{self.character}: {cur} 현금 음수 ({amt})")
        for pos in self.positions.values():
            if pos.quantity <= 0:
                raise RuntimeError(f"{self.character}: {pos.symbol} 수량 0 이하")
