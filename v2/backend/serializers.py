"""ORM → API 응답 변환. **경계에서 최소단위를 사람 단위로 바꾸는 유일한 지점**이다.

내부는 전부 정수 최소단위(SPEC §2.1)지만, 프론트는 minor 를 전혀 모른다 —
KRW 는 원(정수), USD 는 달러(소수 2자리)로 내려간다. 이 변환이 여러 곳에 흩어지면
어딘가 한 곳이 반올림을 다르게 해 화면 숫자가 어긋난다.

발동가(`stop_price`/`take_price`)를 서버가 계산해 내려주는 이유: 발동을 판정하는 쪽과
화면에 표시하는 쪽이 다른 식을 쓰면 "표시는 9,500인데 9,499에 팔렸다" 같은 불신이 생긴다.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from simcore.names import SYMBOL_NAMES
from v2.backend import sellwall
from v2.backend.models import Account, EventLog, Position, SellRule, Trade
from v2.backend.money import to_major


def money(minor: int | None, currency: str) -> float | int | None:
    """최소단위 → 사람 단위. KRW 는 정수, USD 는 소수 2자리."""
    if minor is None:
        return None
    v = to_major(int(minor), currency)
    return int(v) if currency == "KRW" else float(round(v, 2))


def name_of(symbol: str) -> str:
    return SYMBOL_NAMES.get(symbol, symbol)


def pct(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def sell_rule_out(rule: SellRule | None, position: Position, currency: str) -> dict | None:
    if rule is None:
        return None
    stop_minor, take_minor = sellwall.trigger_prices(rule, position)
    return {
        "id": rule.id,
        "position_id": rule.position_id,
        "stop_loss_pct": pct(rule.stop_loss_pct),
        "take_profit_pct": pct(rule.take_profit_pct),
        "stop_price": money(stop_minor, currency),
        "take_price": money(take_minor, currency),
        "quantity": rule.quantity,
        "active": bool(rule.active),
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat(),
    }


def position_out(pos: Position, currency: str, price_minor: int | None,
                 stale: bool, rule: SellRule | None) -> dict:
    """현재가를 모르면(조회 실패) 평단으로 평가하고 stale=True 로 알린다."""
    avg = int(pos.avg_price_minor)
    cur = int(price_minor) if price_minor is not None else avg
    cost = avg * pos.quantity
    value = cur * pos.quantity
    pnl = value - cost
    return {
        "id": pos.id,
        "account_id": pos.account_id,
        "symbol": pos.symbol,
        "name": name_of(pos.symbol),
        "quantity": pos.quantity,
        "avg_price": money(avg, currency),
        "current_price": money(cur, currency),
        "market_value": money(value, currency),
        "cost_basis": money(cost, currency),
        "unrealized_pnl": money(pnl, currency),
        "unrealized_pnl_pct": round(pnl / cost * 100, 2) if cost else 0.0,
        "opened_at": pos.opened_at.isoformat(),
        "stale": bool(stale),
        "sell_rule": sell_rule_out(rule, pos, currency),
    }


def trade_out(t: Trade, currency: str) -> dict:
    return {
        "id": t.id,
        "account_id": t.account_id,
        "symbol": t.symbol,
        "name": name_of(t.symbol),
        "side": t.side,
        "quantity": t.quantity,
        "price": money(t.price_minor, currency),
        "fee": money(t.fee_minor, currency),
        "tax": money(t.tax_minor, currency),
        "gross": money(t.gross_minor, currency),
        "net": money(t.net_minor, currency),
        "realized_pnl": money(t.realized_pnl_minor, currency),
        "reason": t.reason,
        "sell_rule_id": t.sell_rule_id,
        "trigger_price": money(t.trigger_price_minor, currency),
        "stale": bool(t.stale_price),
        "executed_at": t.executed_at.isoformat(),
    }


def account_summary(session: Session, acct: Account,
                    prices_minor: dict[str, int] | None = None,
                    stale: bool = False, spark_limit: int = 30) -> dict:
    """캐릭터 카드 1장. 평가액은 넘겨받은 현재가로, 없으면 평단으로 계산한다."""
    from v2.backend.models import EquitySnapshot      # 순환 import 회피

    prices_minor = prices_minor or {}
    positions = session.query(Position).filter_by(account_id=acct.id).all()
    market_value = sum(
        int(prices_minor.get(p.symbol, p.avg_price_minor)) * p.quantity for p in positions)
    cash = int(acct.cash_minor)
    total = cash + market_value
    seed = int(acct.seed_minor)
    spark = [int(r.equity_minor) for r in session.query(EquitySnapshot)
             .filter_by(account_id=acct.id)
             .order_by(EquitySnapshot.ts.desc()).limit(spark_limit).all()][::-1]
    return {
        "id": acct.id,
        "kind": acct.kind,
        "currency": acct.currency,
        "cash": money(cash, acct.currency),
        "market_value": money(market_value, acct.currency),
        "total_asset": money(total, acct.currency),
        "seed": money(seed, acct.currency),
        "pnl": money(total - seed, acct.currency),
        "return_pct": round((total - seed) / seed * 100, 2) if seed else 0.0,
        "position_count": len(positions),
        "equity_spark": [money(v, acct.currency) for v in spark],
        "stale": bool(stale),
    }


def event_out(e: EventLog) -> dict:
    return {"id": e.id, "account_id": e.account_id, "kind": e.kind,
            "detail": e.detail_json or {}, "ts": e.ts.isoformat()}
