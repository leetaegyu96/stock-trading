"""라이브 엔진 구동자 — run_replay 와 동일 엔진 호출을 실시간 트리거로."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import pandas as pd

from simcore.config import Config
from simcore.engine import Engine
from simcore.models import CapitalFlow, DailyBar, Market, SymbolSnapshot
from simcore import signals as sigmod
from simcore import data as datamod


class Orchestrator:
    def __init__(self, engine: Engine, kis, repo, cfg: Config, fx_provider,
                 index_provider=None):
        self.engine = engine
        self.kis = kis
        self.repo = repo
        self.cfg = cfg
        self.fx = fx_provider
        # (market:str, upto:date) -> pd.Series | None. None 이면 가드용 지수 미사용(가드 무발동).
        self.index_provider = index_provider
        # 보유 종목의 최근가 캐시(호출 간 유지) — run_replay 의 run-lifetime last_close 와 동일 역할.
        # 이게 없으면 이번 사이클 universe 에 없는 보유 종목(예: 범용형의 반대 시장 leg)이
        # equity 평가 시 평단가(원가)로 폴백되어 equity_curve/TWR 가 오염된다.
        self._last_price: dict[str, float] = {}

    def _refresh_bars(self, market: str, symbol: str, upto: date) -> pd.DataFrame:
        cached = self.repo.load_daily_bars(market, symbol)
        start = (cached.index.max().date() + timedelta(days=1)) if not cached.empty \
            else upto - timedelta(days=180)
        if start <= upto:
            fresh = self.kis.daily_bars(market, symbol, start, upto)
            if not fresh.empty:
                self.repo.upsert_daily_bars(market, symbol, fresh)
        return self.repo.load_daily_bars(market, symbol)

    def _seed_held_prices(self) -> None:
        """아직 캐시에 없는 보유 종목(양 시장)의 최근가를 DB 일봉 마지막 종가로 시드."""
        for st in self.engine.states.values():
            for sym, pos in st.portfolio.positions.items():
                if sym in self._last_price:
                    continue
                bars = self.repo.load_daily_bars(pos.market.value, sym)
                if not bars.empty:
                    self._last_price[sym] = float(bars["close"].iloc[-1])

    def on_close(self, d: date, market: str, universe: list[str]) -> None:
        rs = self.repo.get_run_state(market)
        if rs.last_close_date == d:
            return                                  # 멱등: 이미 처리
        m = Market(market)
        fx = self.fx(d)
        self._seed_held_prices()
        snaps: dict[str, SymbolSnapshot] = {}
        for sym in universe:
            try:
                df = self._refresh_bars(market, sym, d)
            except Exception as exc:
                print(f"[live] {market} {sym} 일봉 실패 스킵: {exc}")
                continue
            ts = pd.Timestamp(d)
            if ts not in df.index:
                continue
            frame = sigmod.evaluate_frame(df, self.cfg.signals)
            green, red = sigmod.fired_at(frame, ts)
            gs, rs, gate = sigmod.snapshot_scores(green, red, self.cfg.scores)
            loc = df.index.get_loc(ts)
            prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else float(df.loc[ts, "close"])
            close = float(df.loc[ts, "close"])
            snaps[sym] = SymbolSnapshot(sym, m, green, red, close,
                                        close / prev_close - 1.0, float(df.loc[ts, "volume"]),
                                        green_score=gs, red_score=rs, buy_gate=gate)
            self._last_price[sym] = close
        self.engine.evaluate_close(d, m, snaps,
                                   bearish_by_market=self._bearish_by_market(d))
        snap = self.engine.snapshot(self._last_price, fx)
        # 상태 delta + 이력 append + equity + run_state 갱신을 한 트랜잭션으로 (스펙 §144).
        with self.repo.transaction() as s:
            self.repo.persist_state(self.engine, session=s)
            self.repo.append_new_trades(self.engine, session=s)
            self.repo.record_equity(datetime.now(), snap, session=s)
            self.repo.mark_close(market, d, fx, session=s)

    def _bearish_by_market(self, d: date) -> dict | None:
        """가드 대상 캐릭터가 있을 때만 양 시장 지수로 하락장 dict 계산 (리플레이와 동일 판정식).
        provider 없음/대상 없음 → None(가드 무발동). 시장별 로드 실패 → 그 시장 False."""
        if not self.cfg.rules.bear_guard_characters or self.index_provider is None:
            return None
        indices = {}
        for mk in (Market.KR, Market.US):
            try:
                indices[mk] = self.index_provider(mk.value, d)
            except Exception as exc:
                print(f"[live] {mk.value} 지수 로드 실패(가드 False 폴백): {exc}")
                indices[mk] = None
        periods = {Market.KR: self.cfg.signals.market_trend_period_kr,
                   Market.US: self.cfg.signals.market_trend_period_us}
        return datamod.make_bearish_fn(indices, periods)(pd.Timestamp(d))

    def on_open(self, d: date, market: str, universe: list[str]) -> None:
        rs = self.repo.get_run_state(market)
        if rs.last_open_date == d:
            return                                  # 멱등: 이미 처리
        m = Market(market)
        fx = self.fx(d)
        # 1) 대기 입출금 처리 (이 시장을 거래하는 캐릭터만 — 각 flow 는 첫 해당 시장 개장에 1회)
        applied: list = []
        for req in self.repo.pending_flow_requests():
            st = self.engine.states.get(req.character)
            if st is None or m not in st.spec.markets:
                continue
            liq = tuple(req.liquidate or ())
            try:
                opens = {sym: self.kis.current_price(market, sym) for sym in liq}
                self.engine.apply_flow(d, req.character, req.amount_krw, fx,
                                       open_prices=opens, liquidate=liq)
            except Exception as exc:
                print(f"[live] flow {req.id} 적용 실패(보류): {exc}")
                continue
            applied.append(req)
        # 2) 예약 주문 종목 현재가(=시가)로 체결. 가격 없는 종목은 fill_open 이 이월.
        pend_syms = {b.symbol for st in self.engine.states.values()
                     for b in st.pending_buys if b.market == m}
        pend_syms |= {ps.symbol for st in self.engine.states.values()
                      for ps in st.pending_sells if ps.market == m}
        opens: dict[str, float] = {}
        for sym in pend_syms:
            try:
                opens[sym] = self.kis.current_price(market, sym)
                self._last_price[sym] = opens[sym]
            except Exception as exc:
                print(f"[live] {market} {sym} 시가 조회 실패(이월): {exc}")
        self.engine.fill_open(d, m, opens, fx)
        with self.repo.transaction() as s:
            for req in applied:
                self.repo.record_flow(
                    CapitalFlow(d, req.character, req.amount_krw, fx), session=s)
                self.repo.mark_flow_applied(req.id, session=s)
            self.repo.persist_state(self.engine, session=s)
            self.repo.append_new_trades(self.engine, session=s)
            self.repo.mark_open(market, d, fx, session=s)

    def on_tick(self, d: date, market: str) -> None:
        m = Market(market)
        fx = self.fx(d)
        held = {sym for st in self.engine.states.values()
                for sym, pos in st.portfolio.positions.items() if pos.market == m}
        bars: dict[str, DailyBar] = {}
        for sym in held:
            try:
                px = self.kis.current_price(market, sym)
            except Exception:
                continue                            # 이번 사이클 스킵, 다음 틱 재시도
            self._last_price[sym] = px
            bars[sym] = DailyBar(sym, d, px, px, px, px, 0.0)  # o=h=l=c=현재가 유사봉
        if not bars:
            return
        self.engine.check_stops(d, m, bars, fx)
        with self.repo.transaction() as s:
            self.repo.persist_state(self.engine, session=s)
            self.repo.append_new_trades(self.engine, session=s)
