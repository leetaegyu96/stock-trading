"""대시보드 백엔드 — Postgres 조회 (simcore.live.db ORM 재사용, 읽기 전용)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from simcore.live import db


def list_characters(sf) -> list[dict]:
    """등록된 전체 캐릭터 목록."""
    with sf() as s:
        rows = s.execute(select(db.CharacterRow)).scalars().all()
        return [{"name": r.name, "base_currency": r.base_currency} for r in rows]


def positions(sf, name: str) -> list[dict]:
    """캐릭터의 보유 종목."""
    with sf() as s:
        rows = s.execute(
            select(db.PositionRow)
            .where(db.PositionRow.character == name)
            .order_by(db.PositionRow.symbol)
        ).scalars().all()
        return [
            {
                "symbol": r.symbol,
                "market": r.market,
                "quantity": r.quantity,
                "avg_price": r.avg_price,
                "opened_date": r.opened_date,
            }
            for r in rows
        ]


def trades(sf, name: str, limit: int = 200) -> list[dict]:
    """캐릭터의 거래 내역(최신순, limit 개)."""
    with sf() as s:
        rows = s.execute(
            select(db.TradeRow)
            .where(db.TradeRow.character == name)
            .order_by(db.TradeRow.ts.desc(), db.TradeRow.id.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "ts": r.ts,
                "date": r.date,
                "symbol": r.symbol,
                "market": r.market,
                "side": r.side,
                "quantity": r.quantity,
                "price": r.price,
                "fee": r.fee,
                "tax": r.tax,
                "reason": r.reason,
                "green_count": r.green_count,
                "red_count": r.red_count,
                "fired": list(r.fired or []),
                "realized_pnl": r.realized_pnl,
            }
            for r in rows
        ]


def flows(sf, name: str) -> list[dict]:
    """캐릭터의 입출금(자본 흐름) 이력, 날짜순."""
    with sf() as s:
        rows = s.execute(
            select(db.CapitalFlowRow)
            .where(db.CapitalFlowRow.character == name)
            .order_by(db.CapitalFlowRow.date, db.CapitalFlowRow.id)
        ).scalars().all()
        return [
            {
                "date": r.date,
                "amount_krw": r.amount_krw,
                "fx_rate": r.fx_rate,
            }
            for r in rows
        ]


def equity_series(sf, name: str) -> list[tuple[datetime, float]]:
    """캐릭터의 자산곡선(시각순)."""
    with sf() as s:
        rows = s.execute(
            select(db.EquityPoint)
            .where(db.EquityPoint.character == name)
            .order_by(db.EquityPoint.ts)
        ).scalars().all()
        return [(r.ts, r.equity_krw) for r in rows]


def cash(sf, name: str) -> dict[str, float]:
    """캐릭터의 통화별 현금 잔고."""
    with sf() as s:
        rows = s.execute(
            select(db.CashBalance).where(db.CashBalance.character == name)
        ).scalars().all()
        return {r.currency: r.amount for r in rows}
