"""주문 — 매수·수동매도·매도벽 (SPEC §5, §6).

시세 조회는 **트랜잭션 밖에서** 먼저 끝낸다. 네트워크 호출을 계정 행 잠금 안에서 하면
느린 응답 하나가 그 계정의 모든 주문을 막는다(v1 오케스트레이터와 같은 원칙).
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from v2.backend import market as market_mod
from v2.backend import sellwall, serializers as ser, trading
from v2.backend.deps import (ApiError, current_user, get_sf, load_account,
                             load_position, require_account, require_position)
from v2.backend.models import Account, Position, User
from v2.backend.money import to_minor
from v2.backend.trading import InvariantViolation, TradingError

router = APIRouter(prefix="/api", tags=["orders"])


class OrderIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    quantity: int = Field(ge=1)


class SellRuleIn(BaseModel):
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    quantity: int | None = Field(default=None, ge=1)


def _as_api_error(exc: TradingError) -> ApiError:
    """서비스 계층 코드를 그대로 API 코드로. 불변식 위반만 500(사용자 잘못이 아니다)."""
    status = 500 if isinstance(exc, InvariantViolation) else 400
    if exc.code == "PRICE_UNAVAILABLE":
        status = 503
    elif exc.code == "NOT_FOUND":
        status = 404
    return ApiError(exc.code, exc.message, status=status)


def _quote(acct: Account, symbol: str) -> tuple[float, bool]:
    # 시장 불일치를 **시세 조회 전에** 먼저 걸러낸다. 순서가 반대면 "해외 계좌로 국내
    # 종목 매수" 같은 명백한 실수가 PRICE_UNAVAILABLE("시세를 못 가져왔다")로 보고돼,
    # 사용자는 자기 실수 대신 서버 장애를 의심하게 된다.
    if trading.market_of(symbol) != acct.kind:
        raise ApiError(
            "MARKET_MISMATCH",
            f"{'국내' if acct.kind == 'KR' else '해외'} 캐릭터로는 {symbol} 을(를) "
            f"거래할 수 없습니다. 캐릭터를 바꿔 주세요.")
    try:
        return market_mod.current_price(acct.kind, symbol)
    except TradingError as exc:
        raise _as_api_error(exc) from exc
    except Exception as exc:                 # 알 수 없는 시세 오류도 사용자에겐 같은 의미
        raise ApiError("PRICE_UNAVAILABLE",
                       f"{symbol} 의 현재가를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.",
                       status=503) from exc


def _order_result(s: Session, acct: Account, symbol: str, trade) -> dict:
    """체결 + 갱신된 계좌 + 갱신된 포지션을 함께 돌려준다 — 프론트가 재조회하지 않도록."""
    pos = trading.get_position(s, acct.id, symbol)
    price_minor = trade.price_minor
    return {
        "trade": ser.trade_out(trade, acct.currency),
        "account": ser.account_summary(s, acct, {symbol: price_minor}),
        "position": (ser.position_out(pos, acct.currency, price_minor, False, pos.sell_rule)
                     if pos else None),
    }


@router.post("/accounts/{account_id}/buy")
def buy(body: OrderIn, acct: Account = Depends(require_account),
        user: User = Depends(current_user),
        sf: sessionmaker[Session] = Depends(get_sf)) -> dict:
    price, stale = _quote(acct, body.symbol)       # 잠금 밖에서 조회
    s: Session = sf()
    try:
        locked = load_account(s, acct.id, user)
        trade = trading.buy(s, locked, body.symbol, body.quantity, price, stale=stale)
        out = _order_result(s, locked, body.symbol, trade)
        s.commit()
        return out
    except TradingError as exc:
        s.rollback()
        raise _as_api_error(exc) from exc
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@router.post("/accounts/{account_id}/sell")
def sell(body: OrderIn, acct: Account = Depends(require_account),
         user: User = Depends(current_user),
         sf: sessionmaker[Session] = Depends(get_sf)) -> dict:
    price, stale = _quote(acct, body.symbol)
    s: Session = sf()
    try:
        locked = load_account(s, acct.id, user)
        trade = trading.sell(s, locked, body.symbol, body.quantity, price, stale=stale)
        out = _order_result(s, locked, body.symbol, trade)
        s.commit()
        return out
    except TradingError as exc:
        s.rollback()
        raise _as_api_error(exc) from exc
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@router.put("/positions/{position_id}/sell-rule")
def put_sell_rule(body: SellRuleIn, pos: Position = Depends(require_position),
                  user: User = Depends(current_user),
                  sf: sessionmaker[Session] = Depends(get_sf)) -> dict:
    s: Session = sf()
    try:
        live = load_position(s, pos.id, user)
        acct = s.get(Account, live.account_id)
        rule = sellwall.set_rule(s, live, body.stop_loss_pct, body.take_profit_pct,
                                 body.quantity)
        s.commit()
        s.refresh(live)
        return {"sell_rule": ser.sell_rule_out(rule, live, acct.currency)}
    except TradingError as exc:
        s.rollback()
        raise _as_api_error(exc) from exc
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@router.delete("/positions/{position_id}/sell-rule")
def delete_sell_rule(pos: Position = Depends(require_position),
                     user: User = Depends(current_user),
                     sf: sessionmaker[Session] = Depends(get_sf)) -> dict:
    s: Session = sf()
    try:
        live = load_position(s, pos.id, user)
        sellwall.clear_rule(s, live)
        s.commit()
        return {"sell_rule": None}
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
