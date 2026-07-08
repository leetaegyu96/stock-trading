"""엔진 상태 영속/복원 + 이력 append + run_state 멱등 (스펙 §5)."""
from __future__ import annotations
from datetime import date, datetime
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
