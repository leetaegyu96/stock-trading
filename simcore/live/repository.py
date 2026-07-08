"""엔진 상태 영속/복원 + 이력 append + run_state 멱등 (스펙 §5)."""
from __future__ import annotations
from datetime import date, datetime
import pandas as pd
from sqlalchemy import delete, select

from simcore.engine import Engine, PendingBuy, PendingSell
from simcore.models import (Currency, Market, Position, TradeReason)
from simcore.live import db


class DbTokenStore:
    def __init__(self, session_factory):
        self.sf = session_factory

    def get(self):
        with self.sf() as s:
            row = s.get(db.KisToken, 1)
            return (row.access_token, row.expires_at) if row and row.access_token else None

    def save(self, token: str, expires_at: float) -> None:
        with self.sf() as s:
            row = s.get(db.KisToken, 1)
            if row is None:
                s.add(db.KisToken(id=1, access_token=token, expires_at=expires_at))
            else:
                row.access_token, row.expires_at = token, expires_at
            s.commit()


class Repository:
    def __init__(self, session_factory):
        self.sf = session_factory

    def persist_state(self, engine: Engine) -> None:
        with self.sf() as s:
            for t in (db.CashBalance, db.PositionRow, db.PendingOrder, db.Cooldown):
                s.execute(delete(t))
            for name, st in engine.states.items():
                s.merge(db.CharacterRow(name=name,
                                        base_currency=st.portfolio.base_currency.value))
                for cur, amt in st.portfolio.cash.items():
                    s.add(db.CashBalance(character=name, currency=cur.value, amount=amt))
                for sym, pos in st.portfolio.positions.items():
                    s.add(db.PositionRow(character=name, symbol=sym, market=pos.market.value,
                                         quantity=pos.quantity, avg_price=pos.avg_price,
                                         opened_date=pos.opened))
                for b in st.pending_buys:
                    s.add(db.PendingOrder(character=name, side="BUY", symbol=b.symbol,
                                          market=b.market.value, green_count=b.green_count,
                                          change_pct=b.change_pct, volume=b.volume,
                                          fired=list(b.fired), created_date=date.today()))
                for ps in st.pending_sells:
                    s.add(db.PendingOrder(character=name, side="SELL", symbol=ps.symbol,
                                          market=ps.market.value, red_count=ps.red_count,
                                          fired=list(ps.fired), reason=ps.reason.value,
                                          created_date=date.today()))
                for sym, (mkt, rem) in st.cooldowns.items():
                    s.add(db.Cooldown(character=name, symbol=sym, market=mkt.value,
                                      remaining_days=rem))
            s.commit()

    def rehydrate(self, engine: Engine) -> bool:
        with self.sf() as s:
            cash = s.execute(select(db.CashBalance)).scalars().all()
            if not cash:
                return False
            for row in cash:
                st = engine.states.get(row.character)
                if st:
                    st.portfolio.cash[Currency(row.currency)] = row.amount
            for p in s.execute(select(db.PositionRow)).scalars():
                st = engine.states.get(p.character)
                if st:
                    st.portfolio.positions[p.symbol] = Position(
                        p.symbol, Market(p.market), p.quantity, p.avg_price, p.opened_date)
            for o in s.execute(select(db.PendingOrder)).scalars():
                st = engine.states.get(o.character)
                if not st:
                    continue
                if o.side == "BUY":
                    st.pending_buys.append(PendingBuy(o.symbol, Market(o.market),
                        o.green_count, tuple(o.fired or ()), o.change_pct, o.volume))
                else:
                    st.pending_sells.append(PendingSell(o.symbol, Market(o.market),
                        TradeReason(o.reason), o.red_count, tuple(o.fired or ())))
            for c in s.execute(select(db.Cooldown)).scalars():
                st = engine.states.get(c.character)
                if st:
                    st.cooldowns[c.symbol] = [Market(c.market), c.remaining_days]
            return True

    def get_run_state(self, market: str):
        with self.sf() as s:
            rs = s.get(db.RunState, market)
            if rs is None:
                rs = db.RunState(market=market, schema_version=1, last_fx_rate=0.0)
                s.add(rs); s.commit(); s.refresh(rs)
            s.expunge(rs)
            return rs

    def mark_open(self, market: str, d, fx: float) -> None:
        with self.sf() as s:
            rs = s.get(db.RunState, market) or db.RunState(market=market)
            rs.last_open_date, rs.last_fx_rate = d, fx
            s.merge(rs); s.commit()

    def mark_close(self, market: str, d, fx: float) -> None:
        with self.sf() as s:
            rs = s.get(db.RunState, market) or db.RunState(market=market)
            rs.last_close_date, rs.last_fx_rate = d, fx
            s.merge(rs); s.commit()

    def append_new_trades(self, engine) -> None:
        with self.sf() as s:
            for name, st in engine.states.items():
                have = s.query(db.TradeRow).filter_by(character=name).count()
                for t in st.portfolio.trades[have:]:
                    s.add(db.TradeRow(ts=datetime.now(), date=t.date, character=name,
                        symbol=t.symbol, market=t.market.value, side=t.side.value,
                        quantity=t.quantity, price=t.price, fee=t.fee, tax=t.tax,
                        reason=t.reason.value, green_count=t.green_count,
                        red_count=t.red_count, fired=list(t.fired),
                        realized_pnl=t.realized_pnl))
            s.commit()

    def record_equity(self, ts, snap: dict) -> None:
        with self.sf() as s:
            for name, eq in snap.items():
                s.add(db.EquityPoint(ts=ts, character=name, equity_krw=eq))
            s.commit()

    def enqueue_flow(self, character: str, amount_krw: float, liquidate=()) -> int:
        with self.sf() as s:
            fr = db.FlowRequest(character=character, amount_krw=amount_krw,
                                liquidate=list(liquidate), status="pending",
                                requested_at=datetime.now())
            s.add(fr); s.commit(); s.refresh(fr)
            return fr.id

    def pending_flow_requests(self, character=None):
        with self.sf() as s:
            q = s.query(db.FlowRequest).filter_by(status="pending")
            if character:
                q = q.filter_by(character=character)
            rows = q.order_by(db.FlowRequest.id).all()
            for r in rows:
                s.expunge(r)
            return rows

    def mark_flow_applied(self, req_id: int) -> None:
        with self.sf() as s:
            r = s.get(db.FlowRequest, req_id)
            if r:
                r.status, r.applied_at = "applied", datetime.now()
                s.commit()

    def upsert_daily_bars(self, market: str, symbol: str, df: pd.DataFrame) -> None:
        with self.sf() as s:
            for ts, r in df.iterrows():
                s.merge(db.DailyBarRow(market=market, symbol=symbol, date=ts.date(),
                    open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                    close=float(r["close"]), volume=float(r["volume"])))
            s.commit()

    def load_daily_bars(self, market: str, symbol: str) -> pd.DataFrame:
        with self.sf() as s:
            rows = s.query(db.DailyBarRow).filter_by(market=market, symbol=symbol) \
                    .order_by(db.DailyBarRow.date).all()
            recs = [{"date": pd.Timestamp(r.date), "open": r.open, "high": r.high,
                     "low": r.low, "close": r.close, "volume": r.volume} for r in rows]
            if not recs:
                return pd.DataFrame(columns=["open","high","low","close","volume"])
            return pd.DataFrame(recs).set_index("date")

    def save_universe(self, market: str, symbols: list[str], as_of) -> None:
        with self.sf() as s:
            for rank, sym in enumerate(symbols):
                s.merge(db.UniverseRow(market=market, symbol=sym, as_of_date=as_of, rank=rank))
            s.commit()

    def load_universe(self, market: str, as_of) -> list[str]:
        with self.sf() as s:
            rows = s.query(db.UniverseRow).filter_by(market=market, as_of_date=as_of) \
                    .order_by(db.UniverseRow.rank).all()
            return [r.symbol for r in rows]

    def record_flow(self, flow) -> None:
        with self.sf() as s:
            s.add(db.CapitalFlowRow(date=flow.date, character=flow.character,
                amount_krw=flow.amount_krw, fx_rate=flow.fx_rate))
            s.commit()
