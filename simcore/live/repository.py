"""엔진 상태 영속/복원 + 이력 append + run_state 멱등 (스펙 §5).

write 메서드는 `session=None` 이면 자체 세션을 열고 commit(하위호환), session 이 주어지면
그 세션을 쓰고 commit 하지 않는다(호출자가 `transaction()` 으로 한 번에 commit)."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import date, datetime
import json
import pandas as pd
from sqlalchemy import delete, select

from simcore.engine import Engine, PendingBuy, PendingSell
from simcore.models import (Currency, DecisionType, Market, Position, TradeReason)
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
        self._trade_cursor: dict[str, int] = {}

    @contextmanager
    def transaction(self):
        """여러 write 를 한 트랜잭션으로 묶는다. 예외 시 commit 하지 않아 롤백된다."""
        with self.sf() as s:
            yield s
            s.commit()

    @contextmanager
    def _session(self, session):
        """session 주어지면 그대로 yield(호출자 commit), 없으면 자체 세션 + commit."""
        if session is not None:
            yield session
        else:
            with self.sf() as s:
                yield s
                s.commit()

    def persist_state(self, engine: Engine, session=None) -> None:
        with self._session(session) as s:
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
                                         opened_date=pos.opened, peak_price=pos.peak_price,
                                         locked_stop_pct=pos.locked_stop_pct))
                for b in st.pending_buys:
                    s.add(db.PendingOrder(character=name, side="BUY", symbol=b.symbol,
                                          market=b.market.value, green_count=b.green_count,
                                          green_score=b.green_score,
                                          change_pct=b.change_pct, volume=b.volume,
                                          fired=list(b.fired), created_date=date.today(),
                                          decision_type=(b.decision_type.value
                                                         if b.decision_type else ""),
                                          trigger_rule=b.trigger_rule))
                for ps in st.pending_sells:
                    s.add(db.PendingOrder(character=name, side="SELL", symbol=ps.symbol,
                                          market=ps.market.value, red_count=ps.red_count,
                                          red_score=ps.red_score, partial=ps.partial,
                                          fired=list(ps.fired), reason=ps.reason.value,
                                          created_date=date.today(),
                                          decision_type=(ps.decision_type.value
                                                         if ps.decision_type else ""),
                                          trigger_rule=ps.trigger_rule))
                for sym, (mkt, rem) in st.cooldowns.items():
                    s.add(db.Cooldown(character=name, symbol=sym, market=mkt.value,
                                      remaining_days=rem))

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
                        p.symbol, Market(p.market), p.quantity, p.avg_price, p.opened_date,
                        peak_price=p.peak_price, locked_stop_pct=p.locked_stop_pct)
            for o in s.execute(select(db.PendingOrder)).scalars():
                st = engine.states.get(o.character)
                if not st:
                    continue
                if o.side == "BUY":
                    st.pending_buys.append(PendingBuy(o.symbol, Market(o.market),
                        o.green_count, o.green_score, tuple(o.fired or ()),
                        o.change_pct, o.volume,
                        decision_type=DecisionType(o.decision_type) if o.decision_type else None,
                        trigger_rule=o.trigger_rule or ""))
                else:
                    st.pending_sells.append(PendingSell(o.symbol, Market(o.market),
                        TradeReason(o.reason), o.red_count, o.red_score,
                        tuple(o.fired or ()), partial=o.partial,
                        decision_type=DecisionType(o.decision_type) if o.decision_type else None,
                        trigger_rule=o.trigger_rule or ""))
            for c in s.execute(select(db.Cooldown)).scalars():
                st = engine.states.get(c.character)
                if st:
                    st.cooldowns[c.symbol] = [Market(c.market), c.remaining_days]
            return True

    def persist_intraday_guards(self, engine: Engine, session=None) -> None:
        """캐릭터별 장중 가드(킬스위치 기준선·휩쏘 캡 카운터)를 1행으로 upsert 한다(#26).
        session 이 주어지면 호출자 트랜잭션(on_intraday)에 합류한다."""
        with self._session(session) as s:
            for name, st in engine.states.items():
                last_sell_ts = {sym: ts.isoformat()
                                for sym, ts in st.intraday_last_sell_ts.items()}
                s.merge(db.IntradayGuardRow(
                    character=name,
                    intraday_day=st.intraday_day,
                    day_start_equity=st.intraday_day_start_equity,
                    buys_json=json.dumps(st.intraday_buys),
                    sells_json=json.dumps(st.intraday_sells),
                    last_sell_ts_json=json.dumps(last_sell_ts)))

    def rehydrate_intraday_guards(self, engine: Engine) -> None:
        """부팅 시 장중 가드를 복원한다(#26). 테이블이 비어 있으면(콜드스타트) no-op —
        CharacterState 의 기본값(None/빈 dict)이 그대로 유지된다."""
        with self.sf() as s:
            for row in s.execute(select(db.IntradayGuardRow)).scalars():
                st = engine.states.get(row.character)
                if not st:
                    continue
                st.intraday_day = row.intraday_day
                st.intraday_day_start_equity = row.day_start_equity
                st.intraday_buys = json.loads(row.buys_json or "{}")
                st.intraday_sells = json.loads(row.sells_json or "{}")
                st.intraday_last_sell_ts = {
                    sym: datetime.fromisoformat(ts)
                    for sym, ts in json.loads(row.last_sell_ts_json or "{}").items()}

    def get_run_state(self, market: str):
        with self.sf() as s:
            rs = s.get(db.RunState, market)
            if rs is None:
                rs = db.RunState(market=market, schema_version=1, last_fx_rate=0.0)
                s.add(rs); s.commit(); s.refresh(rs)
            s.expunge(rs)
            return rs

    def mark_open(self, market: str, d, fx: float, session=None) -> None:
        with self._session(session) as s:
            rs = s.get(db.RunState, market) or db.RunState(market=market)
            rs.last_open_date, rs.last_fx_rate = d, fx
            s.merge(rs)

    def mark_close(self, market: str, d, fx: float, session=None) -> None:
        with self._session(session) as s:
            rs = s.get(db.RunState, market) or db.RunState(market=market)
            rs.last_close_date, rs.last_fx_rate = d, fx
            s.merge(rs)

    def record_scan(self, market: str, ts, universe_size: int, evaluated: int,
                    failed: int, gate_pass: int, buys: int, sells: int,
                    scan_minutes: int, session=None) -> None:
        """장중 스캔 하트비트 upsert — 시장별 최신 1행(`mark_close` 와 동일 패턴)."""
        with self._session(session) as s:
            row = s.get(db.IntradayScanRow, market) or db.IntradayScanRow(market=market)
            row.ts, row.universe_size, row.evaluated = ts, universe_size, evaluated
            row.failed, row.gate_pass = failed, gate_pass
            row.buys, row.sells, row.scan_minutes = buys, sells, scan_minutes
            s.merge(row)

    def scan_status(self) -> list[dict]:
        """시장별 장중 스캔 하트비트 전체 행(관찰 전용)."""
        with self.sf() as s:
            rows = s.execute(select(db.IntradayScanRow)
                             .order_by(db.IntradayScanRow.market)).scalars().all()
            return [{
                "market": r.market, "ts": r.ts, "universe_size": r.universe_size,
                "evaluated": r.evaluated, "failed": r.failed, "gate_pass": r.gate_pass,
                "buys": r.buys, "sells": r.sells, "scan_minutes": r.scan_minutes,
            } for r in rows]

    def append_new_trades(self, engine, session=None) -> None:
        with self._session(session) as s:
            for name, st in engine.states.items():
                start = self._trade_cursor.get(name, 0)
                for t in st.portfolio.trades[start:]:
                    s.add(db.TradeRow(ts=datetime.now(), date=t.date, character=name,
                        symbol=t.symbol, market=t.market.value, side=t.side.value,
                        quantity=t.quantity, price=t.price, fee=t.fee, tax=t.tax,
                        reason=t.reason.value, green_count=t.green_count,
                        red_count=t.red_count, green_score=t.green_score,
                        red_score=t.red_score, fired=list(t.fired),
                        realized_pnl=t.realized_pnl,
                        decision_type=t.decision_type.value, trigger_rule=t.trigger_rule))
                self._trade_cursor[name] = len(st.portfolio.trades)

    def record_equity(self, ts, snap: dict, session=None) -> None:
        with self._session(session) as s:
            for name, eq in snap.items():
                s.add(db.EquityPoint(ts=ts, character=name, equity_krw=eq))

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

    def mark_flow_applied(self, req_id: int, session=None) -> None:
        with self._session(session) as s:
            r = s.get(db.FlowRequest, req_id)
            if r:
                r.status, r.applied_at = "applied", datetime.now()

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

    def record_flow(self, flow, session=None) -> None:
        with self._session(session) as s:
            s.add(db.CapitalFlowRow(date=flow.date, character=flow.character,
                amount_krw=flow.amount_krw, fx_rate=flow.fx_rate))

    def replace_signal_status(self, rows: list[dict], session=None,
                               market: str | None = None) -> None:
        """전량 교체 — 최신 마감분만 유지한다(감사 Phase B, 스펙 §5).

        market=None(기본) — 전체 테이블을 지우고 rows 로 교체한다(리플레이 시딩:
        한 번에 모든 시장·캐릭터의 마지막 마감 상태를 새로 쓴다).
        market="KR"/"US" — 그 시장의 행만 지우고 rows 로 교체한다. 다른 시장의
        행은 그대로 보존된다(라이브 on_close 는 시장 하나씩 마감하므로, 전량삭제를
        쓰면 방금 마감한 시장이 다른 시장의 최신 상태까지 지워버린다 — Task 3 해결)."""
        with self._session(session) as s:
            if market is None:
                s.execute(delete(db.SignalStatusRow))
            else:
                s.execute(delete(db.SignalStatusRow)
                         .where(db.SignalStatusRow.market == market))
            for r in rows:
                s.add(db.SignalStatusRow(
                    date=r["date"], character=r["character"], symbol=r["symbol"],
                    market=r.get("market", ""), kind=r["kind"],
                    green_score=r.get("green_score", 0),
                    red_score=r.get("red_score", 0), buy_gate=r.get("buy_gate", False),
                    status=r.get("status", ""), block_reason=r.get("block_reason", ""),
                    stop_px=r.get("stop_px"), trail_px=r.get("trail_px"),
                    close=r.get("close")))

    def signal_status(self, character: str | None = None) -> list[dict]:
        """후보·보유 상태 행. character 주어지면 SQL where 로 그 캐릭터만 필터한다
        (None 이면 전체 — 호출자가 kind 등 나머지는 직접 필터한다)."""
        with self.sf() as s:
            q = select(db.SignalStatusRow).order_by(db.SignalStatusRow.id)
            if character is not None:
                q = q.where(db.SignalStatusRow.character == character)
            rows = s.execute(q).scalars().all()
            return [{
                "date": r.date, "character": r.character, "symbol": r.symbol,
                "market": r.market, "kind": r.kind, "green_score": r.green_score,
                "red_score": r.red_score,
                "buy_gate": r.buy_gate, "status": r.status, "block_reason": r.block_reason,
                "stop_px": r.stop_px, "trail_px": r.trail_px, "close": r.close,
            } for r in rows]
