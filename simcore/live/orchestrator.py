"""라이브 엔진 구동자 — run_replay 와 동일 엔진 호출을 실시간 트리거로."""
from __future__ import annotations
import threading
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
        # 장중 잠정봉 시가·고저 추적: symbol -> (open, high, low, day). 일자 바뀌면 리셋.
        self._intraday_hl: dict[str, tuple] = {}
        # on_open/on_close/on_tick/on_intraday 는 APScheduler 스레드풀에서 서로 다른
        # 스레드로 동시에 실행될 수 있고, 모두 같은 Engine.states 를 락 없이 mutate 하면
        # 레이스(예: 손절과 장중 매도가 동시에 같은 포지션을 건드림)가 난다. 상태 mutate
        # + persist 구간만 이 락으로 직렬화한다 — 재진입 가능(RLock)해서 핸들러 내부에서
        # 중첩 호출되어도 데드락이 없다. KIS 네트워크 조회는 절대 락을 잡은 채로 하지
        # 않는다(10분 60종목 장중 스캔이 5분 손절 틱을 굶기지 않도록).
        self._lock = threading.RLock()

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
        # 상태 mutate(evaluate_close) + 조회(snapshot) + persist 를 한 락 구간으로 직렬화.
        # 위 유니버스 조회 루프(네트워크)는 락 밖에서 이미 끝났다.
        with self._lock:
            self.engine.evaluate_close(d, m, snaps,
                                       bearish_by_market=self._bearish_by_market(d))
            snap = self.engine.snapshot(self._last_price, fx)
            rows = self._signal_status_rows(d, m, snaps)
            # 상태 delta + 이력 append + equity + run_state 갱신을 한 트랜잭션으로 (스펙 §144).
            with self.repo.transaction() as s:
                self.repo.persist_state(self.engine, session=s)
                self.repo.append_new_trades(self.engine, session=s)
                self.repo.record_equity(datetime.now(), snap, session=s)
                self.repo.mark_close(market, d, fx, session=s)
                # market 스코프 교체 — 이 시장 마감분만 지우고 다시 쓴다. 전량삭제(market=None)를
                # 쓰면 KR 마감이 US 의 최신 상태까지 지워버린다(감사 Phase B, Task 3).
                self.repo.replace_signal_status(rows, session=s, market=market)

    def _signal_status_rows(self, d: date, m: Market,
                            snaps: dict[str, SymbolSnapshot]) -> list[dict]:
        """이번 마감(시장 m)의 후보(engine.last_candidates)+보유 상태를 signal_status
        행으로 구성한다(관찰 전용, 스펙 §5 — run_replay 말미 로직과 동일 계산식)."""
        rows: list[dict] = []
        for name, st in self.engine.states.items():
            for c in self.engine.last_candidates.get(name, []):
                if c.market != m:
                    continue
                rows.append({
                    "date": d, "character": name, "symbol": c.symbol,
                    "market": m.value, "kind": "후보",
                    "green_score": c.green_score, "red_score": c.red_score,
                    "buy_gate": c.buy_gate, "status": c.status,
                    "block_reason": c.block_reason, "stop_px": None, "trail_px": None,
                    "close": self._last_price.get(c.symbol),
                })
            for sym, pos in st.portfolio.positions.items():
                if pos.market != m:
                    continue
                snap = snaps.get(sym)
                red_score = (snap.red_score if snap is not None
                             else self._prior_held_red_score(name, sym))
                stop_px = pos.avg_price * (1 + pos.locked_stop_pct)
                peak_gain = pos.peak_price / pos.avg_price - 1.0
                trail_px = (pos.peak_price * (1 - self.cfg.rules.trail_pct)
                            if peak_gain >= self.cfg.rules.trailing_top else None)
                rows.append({
                    "date": d, "character": name, "symbol": sym,
                    "market": m.value, "kind": "보유",
                    "green_score": 0, "red_score": red_score,
                    "buy_gate": False, "status": "", "block_reason": "",
                    "stop_px": stop_px, "trail_px": trail_px,
                    "close": self._last_price.get(sym),
                })
        return rows

    def _prior_held_red_score(self, character: str, symbol: str) -> int:
        """이번 마감의 universe 프레임에 스냅이 없는 보유 종목(랭킹 이탈 등)에 대해,
        red_score=0(무위험 오인)으로 리셋하지 않고 직전 signal_status(kind=보유) 행의
        값을 승계한다. 직전 행이 없으면(첫 마감 등) 0."""
        prior = [r for r in self.repo.signal_status(character)
                 if r["symbol"] == symbol and r["kind"] == "보유"]
        return prior[-1]["red_score"] if prior else 0

    def _bearish_by_market(self, d: date) -> dict | None:
        """가드 대상 캐릭터가 있을 때만 양 시장 지수로 하락장 dict 계산 (리플레이와 동일 판정식).
        provider 없음/대상 없음 → None(가드 무발동). 시장별 로드 실패 → 그 시장 False."""
        if not self.cfg.rules.bear_guard_characters or self.index_provider is None:
            return None
        indices = {}
        # 주의: 라이브는 KR 마감 이벤트 시점에 US 지수도 조회 → US는 당일 미마감이라 asof(d)가
        # 전일 US 세션을 반환할 수 있음. 리플레이는 같은 시뮬 날짜로 양시장을 동시 판정하므로,
        # 범용형(양시장 동시 하락 필요)을 라이브에서 켤 경우 경계일에 라이브↔리플레이 판정이
        # 어긋날 수 있다(단일시장형은 무관). 범용형 라이브 활성화 전 점검 필요.
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
        # 1) 대기 입출금 처리 준비 (이 시장을 거래하는 캐릭터만) — 청산 대상 현재가 조회는
        #    네트워크이므로 락 밖에서 먼저 끝낸다. engine.apply_flow(상태 mutate)만 아래
        #    락 구간으로 미룬다.
        flow_reqs: list[tuple] = []
        for req in self.repo.pending_flow_requests():
            st = self.engine.states.get(req.character)
            if st is None or m not in st.spec.markets:
                continue
            liq = tuple(req.liquidate or ())
            try:
                liq_opens = {sym: self.kis.current_price(market, sym) for sym in liq}
            except Exception as exc:
                print(f"[live] flow {req.id} 시가 조회 실패(보류): {exc}")
                continue
            flow_reqs.append((req, liq_opens, liq))
        # 2) 예약 주문 종목 현재가(=시가) 조회(네트워크, 락 밖). 가격 없는 종목은
        #    fill_open 이 이월한다.
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
        # 상태 mutate(apply_flow/fill_open) + persist 를 한 락 구간으로 직렬화.
        applied: list = []
        with self._lock:
            for req, liq_opens, liq in flow_reqs:
                try:
                    self.engine.apply_flow(d, req.character, req.amount_krw, fx,
                                           open_prices=liq_opens, liquidate=liq)
                except Exception as exc:
                    print(f"[live] flow {req.id} 적용 실패(보류): {exc}")
                    continue
                applied.append(req)
            self.engine.fill_open(d, m, opens, fx)
            with self.repo.transaction() as s:
                for req in applied:
                    self.repo.record_flow(
                        CapitalFlow(d, req.character, req.amount_krw, fx), session=s)
                    self.repo.mark_flow_applied(req.id, session=s)
                self.repo.persist_state(self.engine, session=s)
                self.repo.append_new_trades(self.engine, session=s)
                self.repo.mark_open(market, d, fx, session=s)

    def on_intraday(self, now, d, market: str, universe: list[str]) -> None:
        m = Market(market)
        fx = self.fx(d)
        snaps: dict[str, SymbolSnapshot] = {}
        strengths: dict[str, float | None] = {}
        for sym in universe:
            try:
                px = self.kis.current_price(market, sym)
            except Exception:
                continue                            # 이번 사이클 스킵, 다음 틱 재시도
            # 이 종목의 나머지 처리(거래량/일봉/신호 계산) 중 어디서든 예외가 나도
            # 이 종목만 스킵하고 나머지 유니버스·persist 는 계속되어야 한다(부분 실패 스킵).
            try:
                self._last_price[sym] = px
                # 당일 누적거래량(실패 시 히스토리 마지막 거래량 대용)
                try:
                    today = self.kis.daily_bars(market, sym, d, d)
                    vol = float(today["volume"].iloc[-1]) if not today.empty else 0.0
                except Exception:
                    vol = 0.0
                # 확정 히스토리(어제까지만 조회/캐시) + 잠정 오늘 봉(open/high/low 추적, close=현재가).
                # KIS 일봉 조회는 장중에 당일(d)까지 요청하면 장중 진행 중인 "잠정" 봉을 반환하는데,
                # _refresh_bars 는 조회 결과를 그대로 DB 캐시에 upsert 한다. upto=d 로 부르면 그
                # 잠정봉이 d 자 확정 일봉으로 영속되고, 캐시 커트오프(cached.index.max()+1)
                # 때문에 이후(진짜 장마감의 on_close 포함) 재조회가 영구히 스킵되어 잠정가가
                # 그대로 당일 확정 종가로 굳어버린다. 그래서 확정 히스토리는 반드시 d-1까지만
                # 조회/캐시하고, 당일(d) 잠정봉은 아래에서 메모리상으로만 구성한다.
                df = self._refresh_bars(market, sym, d - timedelta(days=1))
                o, hi, lo, hl_day = self._intraday_hl.get(sym, (px, px, px, d))
                if hl_day != d:
                    o, hi, lo = px, px, px             # 일자 바뀜 → 당일 시가·고저 리셋
                hi, lo = max(hi, px), min(lo, px)
                self._intraday_hl[sym] = (o, hi, lo, d)
                ts = pd.Timestamp(d)
                df = df.copy()
                # 빈 히스토리(신규 상장 등)에서는 df["volume"].iloc[-1] 폴백이 IndexError 를
                # 내므로, 빈 df 는 0.0 으로 안전하게 폴백한다.
                fallback_vol = df["volume"].iloc[-1] if len(df) else 0.0
                df.loc[ts] = {"open": o, "high": hi, "low": lo, "close": px,
                              "volume": vol if vol else fallback_vol}
                df = df.sort_index()
                frame = sigmod.evaluate_frame(df, self.cfg.signals)
                green, red = sigmod.fired_at(frame, ts)
                gs, rs, gate = sigmod.snapshot_scores(green, red, self.cfg.scores)
                loc = df.index.get_loc(ts)
                prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else px
                # execution_strength 를 snaps 기록 전에 조회한다 — 이러면 이게 실패해도
                # snaps[sym]/strengths[sym] 둘 다 기록되지 않은 채로 이 종목이 통째로
                # 스킵되어(원자적 스킵), 부분적으로만 채워진 상태로 후보에 남는 일이 없다.
                strength = self.kis.execution_strength(market, sym)
                snaps[sym] = SymbolSnapshot(sym, m, green, red, px, px / prev_close - 1.0,
                                            vol, green_score=gs, red_score=rs, buy_gate=gate)
                strengths[sym] = strength
            except Exception as exc:
                print(f"[intraday] {market} {sym} 스킵: {exc}")
                continue
        if not snaps:
            return
        # 상태 조회(snapshot)+mutate(evaluate_intraday)+persist 를 한 락 구간으로 직렬화.
        # 위 유니버스 조회 루프(네트워크)는 락 밖에서 이미 끝났다. self._last_price/
        # self._intraday_hl 갱신은 이 핸들러만 쓰는 오케스트레이터 로컬 상태이고 종목별로
        # 멱등하게 덮어써서 락 밖에서 갱신해도 안전하다.
        with self._lock:
            eq = self.engine.snapshot(self._last_price, fx)
            self.engine.evaluate_intraday(d, m, snaps, strengths, fx, now,
                                          day_equity=eq, cur_equity=eq)
            with self.repo.transaction() as s:
                self.repo.persist_state(self.engine, session=s)
                self.repo.append_new_trades(self.engine, session=s)

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
        # 상태 mutate(check_stops) + persist 를 한 락 구간으로 직렬화. 위 보유 종목
        # 현재가 조회 루프(네트워크)는 락 밖에서 이미 끝났다.
        with self._lock:
            self.engine.check_stops(d, m, bars, fx)
            with self.repo.transaction() as s:
                self.repo.persist_state(self.engine, session=s)
                self.repo.append_new_trades(self.engine, session=s)
