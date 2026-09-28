"""계좌·보유·거래내역 조회 (SPEC §7). 모든 응답은 사람 단위 금액(serializers)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, sessionmaker

from v2.backend import market as market_mod
from v2.backend import serializers as ser
from v2.backend.deps import current_user, get_sf, require_account
from v2.backend.models import Account, EquitySnapshot, EventLog, Position, Trade, User
from v2.backend.money import to_minor

router = APIRouter(prefix="/api", tags=["accounts"])


def _prices_for(session: Session, acct: Account) -> tuple[dict[str, int], bool]:
    """보유 종목 현재가를 최소단위로. 하나라도 실패하면 stale=True 로 알린다.

    시세가 없다고 화면을 비우지 않는다 — 평단 폴백은 serializer 가 처리하고,
    여기서는 '지금 값이 최신이 아님'만 정확히 전달한다.
    """
    prices: dict[str, int] = {}
    stale = False
    symbols = [p.symbol for p in session.query(Position).filter_by(account_id=acct.id)]
    for sym in symbols:
        try:
            px, is_stale = market_mod.current_price(acct.kind, sym)
            prices[sym] = to_minor(px, acct.currency)
            stale = stale or is_stale
        except Exception:
            stale = True                     # 조회 실패 — 평단으로 평가된다
    return prices, stale


@router.get("/accounts")
def list_accounts(user: User = Depends(current_user),
                  sf: sessionmaker[Session] = Depends(get_sf)) -> list[dict]:
    with sf() as s:
        accounts = (s.query(Account).filter_by(user_id=user.id)
                    .order_by(Account.kind.desc()).all())    # KR 먼저
        out = []
        for acct in accounts:
            prices, stale = _prices_for(s, acct)
            out.append(ser.account_summary(s, acct, prices, stale))
        return out


@router.get("/accounts/{account_id}")
def get_account(acct: Account = Depends(require_account),
                sf: sessionmaker[Session] = Depends(get_sf)) -> dict:
    with sf() as s:
        acct = s.merge(acct, load=False) if acct not in s else acct
        prices, stale = _prices_for(s, acct)
        out = ser.account_summary(s, acct, prices, stale)
        curve = (s.query(EquitySnapshot).filter_by(account_id=acct.id)
                 .order_by(EquitySnapshot.ts).all())
        out["equity_curve"] = [
            {"ts": r.ts.isoformat(), "equity": ser.money(r.equity_minor, acct.currency)}
            for r in curve]
        return out


@router.get("/accounts/{account_id}/positions")
def list_positions(acct: Account = Depends(require_account),
                   sf: sessionmaker[Session] = Depends(get_sf)) -> list[dict]:
    with sf() as s:
        prices, stale = _prices_for(s, acct)
        rows = (s.query(Position).filter_by(account_id=acct.id)
                .order_by(Position.opened_at).all())
        return [ser.position_out(p, acct.currency, prices.get(p.symbol),
                                 stale and p.symbol not in prices, p.sell_rule)
                for p in rows]


@router.get("/accounts/{account_id}/trades")
def list_trades(acct: Account = Depends(require_account),
                sf: sessionmaker[Session] = Depends(get_sf),
                limit: int = Query(100, ge=1, le=500),
                offset: int = Query(0, ge=0)) -> dict:
    with sf() as s:
        q = s.query(Trade).filter_by(account_id=acct.id)
        total = q.count()
        rows = q.order_by(Trade.executed_at.desc(), Trade.id.desc()) \
                .offset(offset).limit(limit).all()
        return {"items": [ser.trade_out(t, acct.currency) for t in rows], "total": total}


@router.get("/accounts/{account_id}/events")
def list_events(acct: Account = Depends(require_account),
                sf: sessionmaker[Session] = Depends(get_sf),
                limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    with sf() as s:
        rows = (s.query(EventLog).filter_by(account_id=acct.id)
                .order_by(EventLog.ts.desc(), EventLog.id.desc()).limit(limit).all())
        return [ser.event_out(e) for e in rows]
