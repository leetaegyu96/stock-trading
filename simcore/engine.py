"""매매 엔진. 신호 결과(SymbolSnapshot)를 소비해 7/3 규칙·손익절·포지션 관리를 수행한다.
시계·데이터 소스를 모른다 — 리플레이와 라이브가 같은 메서드를 호출한다."""
from __future__ import annotations
from dataclasses import dataclass, field, replace as dc_replace
from datetime import date as Date
from datetime import datetime

from simcore.config import Config
from simcore import costs as costmod
from simcore.models import (
    CandidateEval, Currency, DailyBar, DecisionType, Market, MARKET_CURRENCY, SymbolSnapshot,
    TradeReason,
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
    decision_type: "DecisionType | None" = None   # 결정 시점 확정
    trigger_rule: str = ""


@dataclass
class PendingSell:
    symbol: str
    market: Market
    reason: TradeReason
    red_count: int
    red_score: int
    fired: tuple[str, ...]
    partial: bool = False
    decision_type: "DecisionType | None" = None   # 결정 시점 확정
    trigger_rule: str = ""


@dataclass
class CharacterState:
    spec: CharacterSpec
    portfolio: Portfolio
    pending_buys: list[PendingBuy] = field(default_factory=list)
    pending_sells: list[PendingSell] = field(default_factory=list)
    cooldowns: dict[str, list] = field(default_factory=dict)  # sym -> [Market, remaining_days]
    intraday_day: "date | None" = None
    intraday_buys: dict = field(default_factory=dict)
    intraday_sells: dict = field(default_factory=dict)
    intraday_last_sell_ts: dict = field(default_factory=dict)
    intraday_day_start_equity: "float | None" = None


class Engine:
    def __init__(self, config: Config,
                 characters: tuple[CharacterSpec, ...] = DEFAULT_CHARACTERS):
        self.config = config
        self.states: dict[str, CharacterState] = {
            s.name: CharacterState(s, Portfolio(s.name, s.base_currency, config))
            for s in characters
        }
        # 관찰 전용: 캐릭터명 → 최근 마감 매수 후보 평가(매매 결정에는 사용되지 않음).
        self.last_candidates: dict[str, list[CandidateEval]] = {}

    def start(self, d: Date, fx_rate: float) -> None:
        for st in self.states.values():
            st.portfolio.deposit(d, self.config.initial_capital_krw, fx_rate)

    # ---- 장 마감: 신호 판정 → 다음 개장 주문 예약 ----
    def evaluate_close(self, d: Date, market: Market,
                       snaps: dict[str, SymbolSnapshot],
                       bearish_by_market: dict | None = None) -> None:
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
                    if s.close <= stop_px:
                        trig = "R7"
                    elif "R18" in red:
                        trig = "R18"
                    else:
                        trig = "R5+R23"
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=False,
                        decision_type=DecisionType.FORCED_SELL, trigger_rule=trig))
                elif not r.signal_sell_enabled:
                    continue                       # 점수 매도 OFF — 강제매도(위)만 유효
                elif s.red_score >= r.sell_full_min:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=False,
                        decision_type=DecisionType.FULL_SELL, trigger_rule="+".join(s.red)))
                elif s.red_score >= r.sell_partial_min:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=True,
                        decision_type=DecisionType.PARTIAL_SELL, trigger_rule="+".join(s.red)))
            # 매수 후보 (하락장 가드: 집합에 든 캐릭터만, 그 캐릭터의 전 시장 하락 시 차단)
            if (st.spec.name in r.bear_guard_characters and bearish_by_market
                    and all(bearish_by_market.get(m, False) for m in st.spec.markets)):
                continue
            held = set(st.portfolio.positions) | {b.symbol for b in st.pending_buys}
            # 후보 평가 기록(관찰 전용) — 아래 continue 지점들은 원래 단일 or 조건과
            # 완전히 동일한 순서·조건이며, 결합 결과(스킵 여부)도 동일하다. 기록만 추가.
            cands: list[CandidateEval] = []
            for sym, s in snaps.items():
                if sym in held:
                    cands.append(CandidateEval(sym, market, s.green_score, s.red_score,
                                                s.buy_gate, "차단", "보유중"))
                    continue
                if sym in st.cooldowns:
                    cands.append(CandidateEval(sym, market, s.green_score, s.red_score,
                                                s.buy_gate, "차단", "쿨다운"))
                    continue
                if s.green_score < r.buy_score_min:
                    cands.append(CandidateEval(sym, market, s.green_score, s.red_score,
                                                s.buy_gate, "차단", "점수부족"))
                    continue
                if not s.buy_gate:
                    cands.append(CandidateEval(sym, market, s.green_score, s.red_score,
                                                s.buy_gate, "차단", "게이트미충족"))
                    continue
                st.pending_buys.append(PendingBuy(
                    sym, market, len(s.green), s.green_score, s.green,
                    s.change_pct, s.volume,
                    decision_type=DecisionType.BUY,
                    trigger_rule=f"게이트+{s.green_score}점"))
                cands.append(CandidateEval(sym, market, s.green_score, s.red_score,
                                            s.buy_gate, "예약", ""))
            # 이 시장 분만 교체, 다른 시장 분은 유지
            kept = [c for c in self.last_candidates.get(st.spec.name, []) if c.market != market]
            self.last_candidates[st.spec.name] = kept + cands

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
                           red_count=ps.red_count, red_score=ps.red_score, fired=ps.fired,
                           decision_type=ps.decision_type or DecisionType.FULL_SELL,
                           trigger_rule=ps.trigger_rule)
            st.pending_sells = carried
            # 2) 매수: 우선순위 = green_score → 등락률 → 거래량
            buys = sorted((b for b in st.pending_buys if b.market == market),
                          key=lambda b: (-b.green_score, -b.change_pct, -b.volume))
            st.pending_buys = [b for b in st.pending_buys if b.market != market]
            for idx, b in enumerate(buys):
                slots = r.max_positions - len(st.portfolio.positions)
                if slots <= 0:
                    for rest in buys[idx:]:
                        self._mark_candidate_blocked(st, rest.symbol, market, "슬롯부족")
                    break
                price = opens.get(b.symbol)
                if price is None:
                    self._mark_candidate_blocked(st, b.symbol, market, "가격없음")
                    continue
                if b.symbol in st.portfolio.positions or b.symbol in st.cooldowns:
                    continue
                bought = self._buy(st, d, b, price, fx_rate, slots)
                if not bought:
                    self._mark_candidate_blocked(st, b.symbol, market, "현금부족")

    def _mark_candidate_blocked(self, st: CharacterState, symbol: str, market: Market,
                                 reason: str) -> None:
        """관찰 전용: fill_open 체결 단계 차단을 last_candidates에 반영(있으면 갱신)."""
        lst = self.last_candidates.get(st.spec.name)
        if not lst:
            return
        for i, c in enumerate(lst):
            if c.symbol == symbol and c.market == market:
                lst[i] = dc_replace(c, status="차단", block_reason=reason)
                break

    def _buy(self, st: CharacterState, d: Date, b: PendingBuy, price: float,
             fx_rate: float, slots: int) -> bool:
        c = self.config.costs
        cur = MARKET_CURRENCY[b.market]
        pf = st.portfolio
        # 두 통화를 다 쓰는 캐릭터(범용형)는 반대 통화 잔고도 매수 여력이다. 예산은 총
        # 여력으로 잡고, 체결에는 보유 통화를 먼저 쓴 뒤 **부족분만** 환전한다 — 매도마다
        # 전액을 되돌리던 예전 방식은 왕복 수수료를 물었다(0.1% × 2).
        multi_currency = len(st.spec.markets) > 1
        budget = (pf.buying_power(cur, fx_rate) if multi_currency else pf.cash[cur]) / slots
        fee_rate = costmod.commission_rate(b.market, c)
        fill_price = price * (1 + c.slippage)
        qty = int(budget // (fill_price * (1 + fee_rate)))
        if qty <= 0:
            return False
        total = qty * fill_price * (1 + fee_rate)
        if not pf.ensure_cash(cur, total, fx_rate):
            return False
        pf.buy(d, b.symbol, b.market, qty, fill_price, TradeReason.SIGNAL_BUY,
               green_count=b.green_count, green_score=b.green_score, fired=b.fired,
               decision_type=b.decision_type or DecisionType.BUY, trigger_rule=b.trigger_rule)
        return True

    def _sell(self, st: CharacterState, d: Date, symbol: str, price: float,
              reason: TradeReason, fx_rate: float, quantity: int | None = None,
              cooldown: bool = True, red_count: int = 0, red_score: int = 0,
              fired: tuple[str, ...] = (),
              decision_type: DecisionType = DecisionType.FULL_SELL,
              trigger_rule: str = "") -> None:
        pos = st.portfolio.positions[symbol]
        market = pos.market
        fill_price = price * (1 - self.config.costs.slippage)
        st.portfolio.sell(d, symbol, fill_price, reason, quantity=quantity,
                          red_count=red_count, red_score=red_score, fired=fired,
                          decision_type=decision_type, trigger_rule=trigger_rule)
        if cooldown and symbol not in st.portfolio.positions:
            st.cooldowns[symbol] = [market, self.config.rules.cooldown_days]
        # 매도 대금은 그 통화 그대로 둔다. 예전에는 범용형의 US 매도마다 달러 전액을
        # 원화로 되돌렸는데, 다음 US 매수에서 다시 달러로 바꾸느라 왕복 0.2% 를 물었다
        # (3.2년 리플레이 기준 초기자본의 5.0%p). 이제 `_buy` 가 부족분만 환전하고,
        # 출금은 `Portfolio.withdraw` 가 필요한 만큼만 환전한다.

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

    # ---- 장중: 가드 헬퍼 (휩쏘 캡·재매수 쿨다운·킬스위치) ----
    def _intraday_roll_day(self, st: CharacterState, d: Date, day_equity: float) -> None:
        if st.intraday_day != d:
            st.intraday_day = d
            st.intraday_buys = {}
            st.intraday_sells = {}
            st.intraday_last_sell_ts = {}
            st.intraday_day_start_equity = day_equity

    def _intraday_buy_block(self, st: CharacterState, symbol: str, now: datetime,
                            cur_equity: float) -> str | None:
        """장중 매수 차단 사유(관찰용) — 없으면 None. `_intraday_can_buy` 와 완전히 동일한
        순서·조건이며, bool 대신 사유 문자열을 돌려줘 의사결정판에 기록할 수 있게 한다."""
        r = self.config.rules
        if not r.intraday_buy_enabled:
            return "장중매수OFF"
        if (r.intraday_max_buys_per_day
                and sum(st.intraday_buys.values()) >= r.intraday_max_buys_per_day):
            return "일일매수상한"
        if st.intraday_buys.get(symbol, 0) >= r.intraday_max_buys_per_symbol:
            return "장중매수캡"
        last = st.intraday_last_sell_ts.get(symbol)
        if last is not None:
            mins = (now - last).total_seconds() / 60.0
            if mins < r.intraday_reentry_cooldown_min:
                return "재매수쿨다운"
        start = st.intraday_day_start_equity
        if start and (cur_equity / start - 1.0) <= r.intraday_daily_loss_halt_pct:
            return "킬스위치"   # 당일 손실 한도 도달 → 신규 매수 중단
        return None

    def _intraday_can_buy(self, st: CharacterState, symbol: str, now: datetime,
                          cur_equity: float) -> bool:
        return self._intraday_buy_block(st, symbol, now, cur_equity) is None

    def _intraday_can_sell(self, st: CharacterState, symbol: str) -> bool:
        return st.intraday_sells.get(symbol, 0) < self.config.rules.intraday_max_sells_per_symbol

    # ---- 장중: 현재가 즉시 체결 (evaluate_close 규칙 재사용 + 체결강도 게이팅) ----
    def evaluate_intraday(self, d, market, snaps, strengths, fx_rate, now,
                          day_equity, cur_equity):
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            self._intraday_roll_day(st, d, day_equity.get(st.spec.name, 0.0))
            eq = cur_equity.get(st.spec.name, st.intraday_day_start_equity or 0.0)
            # 1) 매도 (보유 종목 규칙 발동 시 현재가 즉시 매도)
            for sym in list(st.portfolio.positions):
                # 방어: 같은 락 구간 안이라도 이 루프 도중 포지션이 사라지는 경우(예: 향후
                # 리팩터로 인한 재진입)에 KeyError 를 내지 않고 조용히 스킵한다.
                pos = st.portfolio.positions.get(sym)
                if pos is None:
                    continue
                if pos.market != market or sym not in snaps:
                    continue
                s = snaps[sym]
                red = set(s.red)
                forced = ("R18" in red or ({"R5", "R23"} <= red))
                if forced:
                    trig = "R18" if "R18" in red else "R5+R23"
                    self._sell(st, d, sym, s.close, TradeReason.SIGNAL_SELL, fx_rate,
                               red_count=len(red), red_score=s.red_score, fired=tuple(s.red),
                               decision_type=DecisionType.INTRADAY_SELL, trigger_rule=trig)
                    st.intraday_sells[sym] = st.intraday_sells.get(sym, 0) + 1
                    st.intraday_last_sell_ts[sym] = now
                    continue
                if not r.signal_sell_enabled:
                    continue                       # 점수 매도 OFF — 강제매도(위)만 유효
                full = s.red_score >= r.sell_full_min
                partial = s.red_score >= r.sell_partial_min
                if (full or partial) and self._intraday_can_sell(st, sym):
                    qty = (max(1, int(pos.quantity * r.partial_sell_fraction))
                           if partial and not full else None)
                    self._sell(st, d, sym, s.close, TradeReason.SIGNAL_SELL, fx_rate,
                               quantity=qty, red_count=len(red), red_score=s.red_score,
                               fired=tuple(s.red), decision_type=DecisionType.INTRADAY_SELL,
                               trigger_rule="+".join(s.red))
                    st.intraday_sells[sym] = st.intraday_sells.get(sym, 0) + 1
                    if sym not in st.portfolio.positions:
                        st.intraday_last_sell_ts[sym] = now
            # 2) 매수 (미보유 종목이 게이트+조건 충족 시 현재가 즉시 매수)
            #    관찰 전용: 종목별 판정 결과(status/block_reason)를 last_candidates 에 기록한다.
            #    아래 분기는 매매 로직을 바꾸지 않는다(기록만 추가) — evaluate_close 와 동일 원칙.
            #    ※ slots<=0 은 원래 break 였으나, 남은 후보 전부에 "슬롯부족"을 기록하려고
            #      continue 로 바꾼다. 매수가 슬롯을 늘리는 경로는 없어 체결 결과는 동일하다.
            held = set(st.portfolio.positions)
            cands = sorted(
                (s for sym, s in snaps.items()
                 if sym not in held and sym not in st.cooldowns
                 and s.green_score >= r.buy_score_min and s.buy_gate),
                key=lambda s: (-s.green_score, -s.change_pct, -s.volume))
            decided: dict[str, tuple[str, str]] = {}   # sym -> (status, block_reason)
            for s in cands:
                slots = r.max_positions - len(st.portfolio.positions)
                if slots <= 0:
                    decided[s.symbol] = ("차단", "슬롯부족")
                    continue
                strength = strengths.get(s.symbol)
                if strength is not None and strength < r.intraday_strength_buy_min:
                    decided[s.symbol] = ("차단", "체결강도미달")
                    continue
                block = self._intraday_buy_block(st, s.symbol, now, eq)
                if block is not None:
                    decided[s.symbol] = ("차단", block)
                    continue
                b = PendingBuy(s.symbol, market, len(s.green), s.green_score, s.green,
                               s.change_pct, s.volume,
                               decision_type=DecisionType.INTRADAY_BUY,
                               trigger_rule=f"장중 게이트+{s.green_score}점")
                if self._buy(st, d, b, s.close, fx_rate, slots):
                    st.intraday_buys[s.symbol] = st.intraday_buys.get(s.symbol, 0) + 1
                    decided[s.symbol] = ("매수", "")
                else:
                    decided[s.symbol] = ("차단", "현금부족")
            # 이 시장 스냅 전 종목에 대해 후보 평가 기록(held/cooldown/점수/게이트는 여기서 분류)
            cands_eval: list[CandidateEval] = []
            for sym, s in snaps.items():
                if sym in decided:
                    status, reason = decided[sym]
                elif sym in held:
                    status, reason = "차단", "보유중"
                elif sym in st.cooldowns:
                    status, reason = "차단", "쿨다운"
                elif s.green_score < r.buy_score_min:
                    status, reason = "차단", "점수부족"
                elif not s.buy_gate:
                    status, reason = "차단", "게이트미충족"
                else:
                    status, reason = "차단", ""   # 도달 불가(후보였다면 decided에 있음) 안전 폴백
                cands_eval.append(CandidateEval(sym, market, s.green_score, s.red_score,
                                                s.buy_gate, status, reason))
            kept = [c for c in self.last_candidates.get(st.spec.name, []) if c.market != market]
            self.last_candidates[st.spec.name] = kept + cands_eval

    # ---- 장중: 트레일링 스탑 (리플레이 = 당일 OHLC 근사, 라이브 = 현재가 bar) ----
    def check_stops(self, d: Date, market: Market, bars: dict[str, DailyBar],
                    fx_rate: float, update_trailing: bool = True) -> None:
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
                    trig = "R10" if reason == TradeReason.TRAILING_STOP else "R7"
                    self._sell(st, d, sym, stop_px, reason, fx_rate,
                               decision_type=DecisionType.FORCED_SELL, trigger_rule=trig)
                    continue
                if update_trailing:
                    self._update_trailing(pos, b.high)               # 미발동 시 peak 갱신

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
