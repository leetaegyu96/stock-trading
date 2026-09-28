"""시세·종목 라우터 (SPEC §7 시세). 읽기 전용이며 로그인만 요구한다."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from v2.backend import market as market_mod
from v2.backend.deps import ApiError, current_user
from v2.backend.models import User
from v2.backend.trading import TradingError

router = APIRouter(prefix="/api/market", tags=["market"])

_CURRENCY = {"KR": "KRW", "US": "USD"}


def _check_kind(kind: str) -> str:
    if kind not in _CURRENCY:
        raise ApiError("NOT_FOUND", f"알 수 없는 시장입니다: {kind}", status=404)
    return kind


@router.get("/{kind}/stocks")
def list_stocks(kind: str, _user: User = Depends(current_user),
                offset: int = Query(0, ge=0),
                limit: int = Query(30, ge=1, le=100)) -> dict:
    """한 페이지와 전체 개수. 상세는 요청 구간만 채우므로 limit 을 올리면 그만큼 느려진다."""
    _check_kind(kind)
    try:
        items, total = market_mod.list_stocks(kind, offset, limit)
    except TradingError as exc:
        raise ApiError(exc.code, exc.message, status=503) from exc
    return {"items": [s.to_dict() for s in items], "total": total,
            "offset": offset, "limit": limit}


@router.get("/{kind}/stocks/{symbol}")
def get_stock(kind: str, symbol: str, _user: User = Depends(current_user)) -> dict:
    _check_kind(kind)
    try:
        detail = market_mod.get_stock(kind, symbol)
    except TradingError as exc:
        raise ApiError(exc.code, exc.message, status=503) from exc
    return detail.to_dict()
