"""매매 엔진. 신호 결과(SymbolSnapshot)를 소비해 7/3 규칙·손익절·포지션 관리를 수행한다.
시계·데이터 소스를 모른다 — 리플레이와 라이브가 같은 메서드를 호출한다."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date as Date

from simcore.config import Config
from simcore import costs as costmod
from simcore.models import (
    Currency, DailyBar, Market, MARKET_CURRENCY, SymbolSnapshot, TradeReason,
)
from simcore.portfolio import Portfolio


@dataclass(frozen=True)
class CharacterSpec:
    name: str
    markets: tuple[Market, ...]
    base_currency: Currency


DEFAULT_CHARACTERS: tuple[CharacterSpec, ...] = (
    CharacterSpec("국내형", (Market.KR,), Currency.KRW),
    CharacterSpec("해외형", (Market.US,), Currency.USD),
    CharacterSpec("범용형", (Market.KR, Market.US), Currency.KRW),
)


@dataclass
class PendingBuy:
    symbol: str
    market: Market
    green_count: int
    fired: tuple[str, ...]
    change_pct: float
    volume: float


@dataclass
class PendingSell:
    symbol: str
    market: Market
    reason: TradeReason
    red_count: int
    fired: tuple[str, ...]


@dataclass
class CharacterState:
    spec: CharacterSpec
    portfolio: Portfolio
    pending_buys: list[PendingBuy] = field(default_factory=list)
    pending_sells: list[PendingSell] = field(default_factory=list)
    cooldowns: dict[str, list] = field(default_factory=dict)  # sym -> [Market, remaining_days]


class Engine:
    def __init__(self, config: Config,
                 characters: tuple[CharacterSpec, ...] = DEFAULT_CHARACTERS):
        self.config = config
        self.states: dict[str, CharacterState] = {
            s.name: CharacterState(s, Portfolio(s.name, s.base_currency, config))
            for s in characters
        }

    def start(self, d: Date, fx_rate: float) -> None:
        for st in self.states.values():
            st.portfolio.deposit(d, self.config.initial_capital_krw, fx_rate)

    # ---- 장 마감: 신호 판정 → 다음 개장 주문 예약 ----
    def evaluate_close(self, d: Date, market: Market,
                       snaps: dict[str, SymbolSnapshot]) -> None:
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            # 쿨다운: 이 시장 마감마다 무조건 1 감소 (스냅샷 누락·거래정지와 무관)
            for sym in list(st.cooldowns):
                cd_market, remaining = st.cooldowns[sym]
                if cd_market != market:
                    continue
                remaining -= 1
                if remaining <= 0:
                    del st.cooldowns[sym]
                else:
                    st.cooldowns[sym][1] = remaining
            # 보유 종목 매도 판정 (R7/R10 은 종가 기준으로 여기서 추가)
            already_pending = {ps.symbol for ps in st.pending_sells}
            for sym, pos in st.portfolio.positions.items():
                if pos.market != market or sym not in snaps or sym in already_pending:
                    continue
                s = snaps[sym]
                red = list(s.red)
                if s.close <= pos.avg_price * (1 + r.stop_loss_pct):
                    red.append("R7")
                if s.close >= pos.avg_price * (1 + r.take_profit_pct):
                    red.append("R10")
                if len(red) >= r.sell_threshold:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), tuple(red)))
            # 매수 후보 (미보유 · 쿨다운 아님 · 임계값 이상)
            held = set(st.portfolio.positions) | {b.symbol for b in st.pending_buys}
            for sym, s in snaps.items():
                if (sym in held or sym in st.cooldowns
                        or len(s.green) < r.buy_threshold):
                    continue
                st.pending_buys.append(PendingBuy(
                    sym, market, len(s.green), s.green, s.change_pct, s.volume))

    # ---- 개장: 예약 주문 체결 ----
    def fill_open(self, d: Date, market: Market, opens: dict[str, float],
                  fx_rate: float) -> None:
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            # 1) 매도 먼저 (현금 확보). 가격 없는(거래정지) 매도는 이월
            carried: list[PendingSell] = []
            for ps in st.pending_sells:
                if ps.market != market:
                    carried.append(ps)
                    continue
                if ps.symbol not in st.portfolio.positions:
                    continue  # 이미 손절 등으로 청산됨 → 폐기
                price = opens.get(ps.symbol)
                if price is None:
                    carried.append(ps)
                    continue
                self._sell(st, d, ps.symbol, price, ps.reason, fx_rate,
                           red_count=ps.red_count, fired=ps.fired)
            st.pending_sells = carried
            # 2) 매수: 우선순위 = 신호 수 → 등락률 → 거래량
            buys = sorted((b for b in st.pending_buys if b.market == market),
                          key=lambda b: (-b.green_count, -b.change_pct, -b.volume))
            st.pending_buys = [b for b in st.pending_buys if b.market != market]
            for b in buys:
                slots = r.max_positions - len(st.portfolio.positions)
                if slots <= 0:
                    break
                price = opens.get(b.symbol)
                if (price is None or b.symbol in st.portfolio.positions
                        or b.symbol in st.cooldowns):
                    continue
                self._buy(st, d, b, price, fx_rate, slots)

    def _buy(self, st: CharacterState, d: Date, b: PendingBuy, price: float,
             fx_rate: float, slots: int) -> None:
        c = self.config.costs
        cur = MARKET_CURRENCY[b.market]
        pf = st.portfolio
        cross_currency = (st.spec.base_currency == Currency.KRW and cur == Currency.USD)
        if cross_currency:
            budget = costmod.krw_to_usd(pf.cash[Currency.KRW] / slots, fx_rate, c.fx_fee)
        else:
            budget = pf.cash[cur] / slots
        fee_rate = costmod.commission_rate(b.market, c)
        fill_price = price * (1 + c.slippage)
        qty = int(budget // (fill_price * (1 + fee_rate)))
        if qty <= 0:
            return
        if cross_currency:
            pf.convert_to_usd(qty * fill_price * (1 + fee_rate), fx_rate)
        pf.buy(d, b.symbol, b.market, qty, fill_price, TradeReason.SIGNAL_BUY,
               green_count=b.green_count, fired=b.fired)

    def _sell(self, st: CharacterState, d: Date, symbol: str, price: float,
              reason: TradeReason, fx_rate: float, red_count: int = 0,
              fired: tuple[str, ...] = ()) -> None:
        pos = st.portfolio.positions[symbol]
        fill_price = price * (1 - self.config.costs.slippage)
        st.portfolio.sell(d, symbol, fill_price, reason,
                          red_count=red_count, fired=fired)
        st.cooldowns[symbol] = [pos.market, self.config.rules.cooldown_days]
        if st.spec.base_currency == Currency.KRW and pos.market == Market.US:
            st.portfolio.convert_all_usd_to_krw(fx_rate)  # 범용형: 매도 대금 즉시 원화로
