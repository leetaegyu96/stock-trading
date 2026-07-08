"""라이브 엔진 구동자 — run_replay 와 동일 엔진 호출을 실시간 트리거로."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import pandas as pd

from simcore.config import Config
from simcore.engine import Engine
from simcore.models import DailyBar, Market, SymbolSnapshot
from simcore import signals as sigmod


class Orchestrator:
    def __init__(self, engine: Engine, kis, repo, cfg: Config, fx_provider):
        self.engine = engine
        self.kis = kis
        self.repo = repo
        self.cfg = cfg
        self.fx = fx_provider

    def _refresh_bars(self, market: str, symbol: str, upto: date) -> pd.DataFrame:
        cached = self.repo.load_daily_bars(market, symbol)
        start = (cached.index.max().date() + timedelta(days=1)) if not cached.empty \
            else upto - timedelta(days=180)
        if start <= upto:
            fresh = self.kis.daily_bars(market, symbol, start, upto)
            if not fresh.empty:
                self.repo.upsert_daily_bars(market, symbol, fresh)
        return self.repo.load_daily_bars(market, symbol)

    def on_close(self, d: date, market: str, universe: list[str]) -> None:
        rs = self.repo.get_run_state(market)
        if rs.last_close_date == d:
            return                                  # 멱등: 이미 처리
        m = Market(market)
        fx = self.fx(d)
        snaps: dict[str, SymbolSnapshot] = {}
        last_close: dict[str, float] = {}
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
            last_close[sym] = close
        self.engine.evaluate_close(d, m, snaps)
        self.repo.persist_state(self.engine)
        self.repo.append_new_trades(self.engine)
        snap = self.engine.snapshot(last_close, fx)
        self.repo.record_equity(datetime.now(), snap)
        self.repo.mark_close(market, d, fx)
