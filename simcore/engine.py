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
    green_score: int
    fired: tuple[str, ...]
    change_pct: float
    volume: float


@dataclass
class PendingSell:
    symbol: str
    market: Market
    reason: TradeReason
    red_count: int
    red_score: int
    fired: tuple[str, ...]
    partial: bool = False


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
            # 매도 판정
            already_pending = {ps.symbol for ps in st.pending_sells}
            for sym, pos in st.portfolio.positions.items():
                if pos.market != market or sym not in snaps or sym in already_pending:
                    continue
                s = snaps[sym]
                red = set(s.red)
                stop_px = pos.avg_price * (1 + pos.locked_stop_pct)
                forced = (s.close <= stop_px            # R7/트레일링 (종가 갭)
                          or "R18" in red               # 지지선 붕괴
                          or ({"R5", "R23"} <= red))     # 거래량 급증 음봉 + 장대 음봉
                if forced:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=False))
                elif s.red_score >= r.sell_full_min:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=False))
                elif s.red_score >= r.sell_partial_min:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=True))
            # 매수 후보
            held = set(st.portfolio.positions) | {b.symbol for b in st.pending_buys}
            for sym, s in snaps.items():
                if (sym in held or sym in st.cooldowns
                        or s.green_score < r.buy_score_min or not s.buy_gate):
                    continue
                st.pending_buys.append(PendingBuy(
                    sym, market, len(s.green), s.green_score, s.green,
                    s.change_pct, s.volume))

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
                    carried.append(ps); continue
                if ps.symbol not in st.portfolio.positions:
                    continue
                price = opens.get(ps.symbol)
                if price is None:
                    carried.append(ps); continue
                pos = st.portfolio.positions[ps.symbol]
                qty = None
                if ps.partial:
                    qty = max(1, int(pos.quantity * r.partial_sell_fraction))
                # 부분매도 수량이 반올림으로 잔량 전체를 청산하는 경우(예: quantity==1)에도
                # 쿨다운이 정확히 걸려야 하므로, 등급이 아니라 _sell 의 "실제 청산 여부" 가드에
                # 위임한다 (cooldown=True 는 포지션이 남아 있으면 자동으로 무시됨).
                self._sell(st, d, ps.symbol, price, ps.reason, fx_rate,
                           quantity=qty, cooldown=True,
                           red_count=ps.red_count, red_score=ps.red_score, fired=ps.fired)
            st.pending_sells = carried
            # 2) 매수: 우선순위 = green_score → 등락률 → 거래량
            buys = sorted((b for b in st.pending_buys if b.market == market),
                          key=lambda b: (-b.green_score, -b.change_pct, -b.volume))
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
               green_count=b.green_count, green_score=b.green_score, fired=b.fired)

    def _sell(self, st: CharacterState, d: Date, symbol: str, price: float,
              reason: TradeReason, fx_rate: float, quantity: int | None = None,
              cooldown: bool = True, red_count: int = 0, red_score: int = 0,
              fired: tuple[str, ...] = ()) -> None:
        pos = st.portfolio.positions[symbol]
        market = pos.market
        fill_price = price * (1 - self.config.costs.slippage)
        st.portfolio.sell(d, symbol, fill_price, reason, quantity=quantity,
                          red_count=red_count, red_score=red_score, fired=fired)
        if cooldown and symbol not in st.portfolio.positions:
            st.cooldowns[symbol] = [market, self.config.rules.cooldown_days]
        if st.spec.base_currency == Currency.KRW and market == Market.US:
            st.portfolio.convert_all_usd_to_krw(fx_rate)  # 범용형: 매도 대금 즉시 원화로

    def _update_trailing(self, pos, high: float) -> None:
        r = self.config.rules
        if high > pos.peak_price:
            pos.peak_price = high
        peak_gain = pos.peak_price / pos.avg_price - 1.0
        for thr, lock in r.trailing_tiers:          # 내림차순, 첫 매칭
            if peak_gain >= thr:
                pos.locked_stop_pct = max(pos.locked_stop_pct, lock)
                break
        if peak_gain >= r.trailing_top:             # 최고가 대비 트레일
            trail = pos.peak_price * (1 - r.trail_pct) / pos.avg_price - 1.0
            pos.locked_stop_pct = max(pos.locked_stop_pct, trail)

    # ---- 장중: 트레일링 스탑 (리플레이 = 당일 OHLC 근사, 라이브 = 현재가 bar) ----
    def check_stops(self, d: Date, market: Market, bars: dict[str, DailyBar],
                    fx_rate: float) -> None:
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            for sym in list(st.portfolio.positions):
                pos = st.portfolio.positions[sym]
                if pos.market != market or sym not in bars:
                    continue
                b = bars[sym]
                stop_px = pos.avg_price * (1 + pos.locked_stop_pct)  # 갱신 전 잠금선
                if b.low <= stop_px:                                 # 트리거 우선(보수적)
                    reason = (TradeReason.TRAILING_STOP
                              if pos.locked_stop_pct > self.config.rules.stop_loss_pct
                              else TradeReason.STOP_LOSS)
                    self._sell(st, d, sym, stop_px, reason, fx_rate)
                    continue
                self._update_trailing(pos, b.high)                   # 미발동 시 peak 갱신

    # ---- 사용자 입출금 ----
    def apply_flow(self, d: Date, character: str, amount_krw: float, fx_rate: float,
                   open_prices: dict[str, float] | None = None,
                   liquidate: tuple[str, ...] = ()) -> None:
        st = self.states[character]
        if amount_krw >= 0:
            st.portfolio.deposit(d, amount_krw, fx_rate)
            return
        for sym in liquidate:  # 사용자가 지정한 청산 종목을 당일 시가로 매도
            if sym not in st.portfolio.positions:
                continue
            price = (open_prices or {}).get(sym)
            if price is None:
                raise ValueError(f"{character}: {sym} 청산 가격이 없습니다")
            self._sell(st, d, sym, price, TradeReason.USER_WITHDRAWAL, fx_rate)
        st.portfolio.withdraw(d, -amount_krw, fx_rate)

    # ---- 평가·강제 처리 ----
    def snapshot(self, last_close: dict[str, float], fx_rate: float) -> dict[str, float]:
        return {name: st.portfolio.equity_krw(last_close, fx_rate)
                for name, st in self.states.items()}

    def force_close(self, d: Date, symbol: str, price: float, fx_rate: float) -> None:
        """상장폐지 등: 모든 캐릭터에서 마지막 가격으로 강제 청산."""
        for st in self.states.values():
            if symbol in st.portfolio.positions:
                self._sell(st, d, symbol, price, TradeReason.DELISTED, fx_rate)
