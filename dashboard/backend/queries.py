"""대시보드 백엔드 — Postgres 조회 (simcore.live.db ORM 재사용, 읽기 전용)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from simcore.live import db
from simcore.live.repository import Repository
from simcore.names import display_name


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
                "name": display_name(r.symbol, r.market),
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
                "name": display_name(r.symbol, r.market),
                "market": r.market,
                "side": r.side,
                "quantity": r.quantity,
                "price": r.price,
                "fee": r.fee,
                "tax": r.tax,
                "reason": r.reason,
                "green_count": r.green_count,
                "red_count": r.red_count,
                "green_score": r.green_score,
                "red_score": r.red_score,
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


def last_prices(sf, positions: list[dict]) -> dict[str, float]:
    """보유 종목의 daily_bars 최신 종가. 없으면 비워두어 summary 쪽 avg_price 폴백에 맡긴다."""
    repo = Repository(sf)
    prices: dict[str, float] = {}
    for pos in positions:
        bars = repo.load_daily_bars(pos["market"], pos["symbol"])
        if not bars.empty:
            prices[pos["symbol"]] = float(bars["close"].iloc[-1])
    return prices


def universe_movers(sf, top: int = 5) -> dict:
    """daily_bars 최근 2봉으로 시장별 등락률 상/하위 top."""
    with sf() as s:
        rows = s.execute(select(db.DailyBarRow)
                         .order_by(db.DailyBarRow.symbol, db.DailyBarRow.date)).scalars().all()
    by_sym: dict[tuple, list] = {}
    for r in rows:
        by_sym.setdefault((r.market, r.symbol), []).append(r)
    changes: dict[str, list] = {"KR": [], "US": []}
    for (market, symbol), bars in by_sym.items():
        if len(bars) < 2:
            continue
        prev, last = bars[-2].close, bars[-1].close
        if prev:
            changes.setdefault(market, []).append(
                {"symbol": symbol, "market": market, "close": last,
                 "change_pct": last / prev - 1.0})
    out = {}
    for market, lst in changes.items():
        lst.sort(key=lambda x: x["change_pct"])
        out[market] = {"down": lst[:top], "up": list(reversed(lst[-top:]))}
    return out


def recent_trades(sf, limit: int = 12) -> list[dict]:
    """전체 캐릭터 통합 최신 체결 N건."""
    with sf() as s:
        rows = s.execute(select(db.TradeRow)
                         .order_by(db.TradeRow.ts.desc(), db.TradeRow.id.desc())
                         .limit(limit)).scalars().all()
        return [{"character": r.character, "symbol": r.symbol, "market": r.market,
                 "side": r.side, "reason": r.reason, "realized_pnl": r.realized_pnl,
                 "date": r.date} for r in rows]


def cash(sf, name: str) -> dict[str, float]:
    """캐릭터의 통화별 현금 잔고."""
    with sf() as s:
        rows = s.execute(
            select(db.CashBalance).where(db.CashBalance.character == name)
        ).scalars().all()
        return {r.currency: r.amount for r in rows}
