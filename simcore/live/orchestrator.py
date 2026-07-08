"""라이브 엔진 구동자 — run_replay 와 동일 엔진 호출을 실시간 트리거로."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import pandas as pd

from simcore.config import Config
from simcore.engine import Engine
from simcore.models import Market, SymbolSnapshot
from simcore import signals as sigmod


class Orchestrator:
    def __init__(self, engine: Engine, kis, repo, cfg: Config, fx_provider):
        self.engine = engine
        self.kis = kis
        self.repo = repo
        self.cfg = cfg
        self.fx = fx_provider
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
            loc = df.index.get_loc(ts)
            prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else float(df.loc[ts, "close"])
            close = float(df.loc[ts, "close"])
            snaps[sym] = SymbolSnapshot(sym, m, green, red, close,
                                        close / prev_close - 1.0, float(df.loc[ts, "volume"]))
            self._last_price[sym] = close
        self.engine.evaluate_close(d, m, snaps)
        snap = self.engine.snapshot(self._last_price, fx)
        # 상태 delta + 이력 append + equity + run_state 갱신을 한 트랜잭션으로 (스펙 §144).
        with self.repo.transaction() as s:
            self.repo.persist_state(self.engine, session=s)
            self.repo.append_new_trades(self.engine, session=s)
            self.repo.record_equity(datetime.now(), snap, session=s)
            self.repo.mark_close(market, d, fx, session=s)
