"""매도벽 — 평단 대비 −n%/+m% 자동매도 (SPEC §6.2, §6.3).

기준선이 매수가가 아니라 **평단**인 이유: 추가 매수로 평단이 움직이면 사용자가 정한
"이만큼 손해 보면 판다"의 기준도 함께 따라가야 하기 때문이다.

체결가는 발동선이 아니라 **발동 시점 현재가**다. 모의투자에서 "설정한 가격에 정확히
체결"을 보여주면 실제 시장에서의 갭·슬리피지 경험을 왜곡한다.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from v2.backend import trading
from v2.backend.models import Account, EventLog, Position, SellRule
from v2.backend.money import to_minor
from v2.backend.trading import TradingError, lock_account

STOP_LOSS = "AUTO_STOP_LOSS"
TAKE_PROFIT = "AUTO_TAKE_PROFIT"


# ---------------------------------------------------------------- 규칙 설정

def _as_pct(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        raise TradingError("INVALID_SELL_RULE", "퍼센트 값을 숫자로 읽을 수 없습니다.")


def _validate(stop: Decimal | None, target: Decimal | None) -> None:
    if stop is not None and not (Decimal("-100") < stop < 0):
        raise TradingError(
            "INVALID_SELL_RULE",
            "'이만큼 떨어지면 팔기'는 -100% 초과 0% 미만의 음수여야 합니다.")
    if target is not None and not (0 < target <= 900):
        raise TradingError(
            "INVALID_SELL_RULE",
            "'이만큼 오르면 팔기'는 0% 초과 900% 이하의 양수여야 합니다.")


def set_rule(session: Session, position: Position, stop_loss_pct=None,
             take_profit_pct=None, quantity: int | None = None,
             now: datetime | None = None) -> SellRule | None:
    """매도벽 설정/갱신. 둘 다 None 이면 기존 규칙을 **삭제**하고 None 을 반환한다."""
    now = now or datetime.now()
    stop = _as_pct(stop_loss_pct)
    target = _as_pct(take_profit_pct)
    if stop is None and target is None:
        return clear_rule(session, position, now)
    _validate(stop, target)

    qty = position.quantity if quantity is None else quantity
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        raise TradingError("INVALID_SELL_RULE", "팔 수량은 1주 이상의 정수여야 합니다.")
    if qty > position.quantity:
        raise TradingError(
            "INVALID_SELL_RULE",
            f"팔 수량({qty}주)이 보유 수량({position.quantity}주)보다 많습니다.")

    rule = session.execute(
        select(SellRule).where(SellRule.position_id == position.id)).scalar_one_or_none()
    if rule is None:
        rule = SellRule(position_id=position.id, created_at=now)
        session.add(rule)
    rule.stop_loss_pct = stop
    rule.take_profit_pct = target
    rule.quantity = qty
    rule.active = True          # 재설정은 '다시 감시 시작'을 뜻한다
    rule.updated_at = now
    session.flush()

    acct = session.get(Account, position.account_id)
    trading.log_event(session, acct, "RULE_SET", {
        "position_id": position.id, "symbol": position.symbol, "rule_id": rule.id,
        "stop_loss_pct": float(stop) if stop is not None else None,
        "take_profit_pct": float(target) if target is not None else None,
        "quantity": qty,
        "stop_price_minor": trigger_prices(rule, position)[0],
        "take_price_minor": trigger_prices(rule, position)[1]}, now)
    return rule


def clear_rule(session: Session, position: Position,
               now: datetime | None = None) -> None:
    """매도벽 해제. 규칙이 없으면 조용히 통과한다(멱등)."""
    now = now or datetime.now()
    rule = session.execute(
        select(SellRule).where(SellRule.position_id == position.id)).scalar_one_or_none()
    if rule is None:
        return None
    rule_id = rule.id
    session.delete(rule)
    session.flush()
    acct = session.get(Account, position.account_id)
    trading.log_event(session, acct, "RULE_CANCEL", {
        "position_id": position.id, "symbol": position.symbol, "rule_id": rule_id}, now)
    return None


# ---------------------------------------------------------------- 판정

def _trigger(avg_minor: int, pct: Decimal | None) -> int | None:
    if pct is None:
        return None
    raw = Decimal(avg_minor) * (Decimal(1) + pct / Decimal(100))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def trigger_prices(rule: SellRule, position: Position) -> tuple[int | None, int | None]:
    """(손절 발동가, 익절 발동가) — 최소단위. 평단 대비로 계산한다."""
    avg = int(position.avg_price_minor)
    return (_trigger(avg, _as_pct(rule.stop_loss_pct)),
            _trigger(avg, _as_pct(rule.take_profit_pct)))


def evaluate(rule: SellRule, position: Position, price_minor: int) -> str | None:
    """발동 여부. `price_minor` 는 **최소단위** 현재가.

    경계값(발동가와 정확히 같은 가격)은 **발동**시킨다 — 사용자가 그은 선에 닿았으면
    닿은 것이다. 둘 다 충족하면 손절을 우선한다(보수적 선택: SPEC §6.2).
    """
    if rule is None or not rule.active:
        return None
    stop, target = trigger_prices(rule, position)
    if stop is not None and price_minor <= stop:
        return STOP_LOSS
    if target is not None and price_minor >= target:
        return TAKE_PROFIT
    return None


# ---------------------------------------------------------------- 감시 1회

def _log_price_stale(session: Session, kind: str, symbol: str, rule_ids: list[int],
                     reason: str, now: datetime) -> None:
    """건너뛴 규칙의 **소유 계정마다** 한 줄씩 남긴다.

    계정에 묶지 않으면 사용자는 자기 활동 피드에서 "왜 발동선을 넘겼는데 안 팔렸지?"의
    답을 찾을 수 없다. 기록은 남았지만 볼 수 없는 기록은 없는 것과 같다.
    """
    owners = session.execute(
        select(SellRule.id, Position.account_id, Account.user_id)
        .join(Position, SellRule.position_id == Position.id)
        .join(Account, Position.account_id == Account.id)
        .where(SellRule.id.in_(rule_ids))).all() if rule_ids else []

    by_account: dict[tuple[int, int], list[int]] = {}
    for rule_id, account_id, user_id in owners:
        by_account.setdefault((account_id, user_id), []).append(rule_id)

    if not by_account:      # 규칙 소유자를 못 찾은 경우에도 사실 자체는 남긴다
        session.add(EventLog(
            user_id=None, account_id=None, kind="PRICE_STALE",
            detail_json={"market": kind, "symbol": symbol, "reason": reason,
                         "skipped_rule_ids": rule_ids},
            ts=now))
        return

    for (account_id, user_id), ids in by_account.items():
        session.add(EventLog(
            user_id=user_id, account_id=account_id, kind="PRICE_STALE",
            detail_json={"market": kind, "symbol": symbol, "reason": reason,
                         "skipped_rule_ids": ids},
            ts=now))


def _process_rule(sf, rule_id: int, price: float, now: datetime) -> str:
    """규칙 하나를 자체 트랜잭션에서 처리. 반환: 'fired' | 'checked' | 'skipped'."""
    s: Session = sf()
    try:
        rule = s.get(SellRule, rule_id)
        if rule is None or not rule.active:
            return "skipped"                    # 멱등: 이미 발동·해제된 규칙
        pos = s.get(Position, rule.position_id)
        if pos is None:
            return "skipped"
        # 계정 잠금을 수동매도와 공유해, 같은 포지션을 동시에 두 번 팔지 않게 한다.
        acct = lock_account(s, pos.account_id)
        s.refresh(rule)
        s.refresh(pos)
        if not rule.active or pos.quantity <= 0:
            return "skipped"

        price_minor = to_minor(price, acct.currency)
        action = evaluate(rule, pos, price_minor)
        if action is None:
            s.commit()
            return "checked"

        stop_minor, target_minor = trigger_prices(rule, pos)
        trigger_minor = stop_minor if action == STOP_LOSS else target_minor
        qty = min(int(rule.quantity), int(pos.quantity))
        symbol = pos.symbol
        avg_minor = int(pos.avg_price_minor)

        # 발동선 대비 얼마나 불리/유리하게 체결됐는지가 이 기능의 학습 포인트다.
        rule.active = False
        rule.updated_at = now
        s.flush()
        trade = trading.sell(s, acct, symbol, qty, price, reason=action,
                             sell_rule_id=rule_id, now=now,
                             trigger_price_minor=trigger_minor)
        trading.log_event(s, acct, "AUTO_SELL_FIRED", {
            "rule_id": rule_id, "symbol": symbol, "action": action,
            "trigger_price_minor": trigger_minor,
            "fill_price_minor": trade.price_minor,
            "gap_minor": trade.price_minor - int(trigger_minor or 0),
            "quantity": qty, "avg_price_minor": avg_minor,
            "realized_pnl_minor": trade.realized_pnl_minor}, now)
        s.commit()
        return "fired"
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def scan_once(sf, market_mod, now: datetime | None = None,
              markets: set[str] | None = None) -> dict[str, int]:
    """활성 매도벽 전체를 1회 감시한다(SPEC §6.3).

    같은 종목을 여러 사용자가 들고 있어도 **시세 조회는 종목당 1회**다. 시세가 신선하지
    않으면(조회 실패·폴백) 그 종목의 규칙은 전부 건너뛴다 — 오래된 가격으로 남의 돈을
    파는 일은 하지 않는다. 한 규칙에서 예외가 나도 나머지는 계속 처리한다.
    """
    now = now or datetime.now()
    stats = {"checked": 0, "fired": 0, "skipped": 0, "errors": 0}

    with sf() as s:                     # type: Session
        rows = s.execute(
            select(SellRule.id, Position.symbol, Account.kind)
            .join(Position, SellRule.position_id == Position.id)
            .join(Account, Position.account_id == Account.id)
            .where(SellRule.active.is_(True))
            .order_by(SellRule.id)).all()

    targets: dict[tuple[str, str], list[int]] = {}
    for rule_id, symbol, kind in rows:
        if markets and kind not in markets:
            continue
        targets.setdefault((kind, symbol), []).append(rule_id)
    if not targets:
        return stats

    prices: dict[tuple[str, str], float] = {}
    stale_symbols: list[tuple[str, str, list[int], str]] = []
    for (kind, symbol), rule_ids in targets.items():
        try:
            price, stale = market_mod.current_price(kind, symbol)
            if stale:
                stale_symbols.append((kind, symbol, rule_ids, "폴백 시세(오래된 종가)"))
                continue
            prices[(kind, symbol)] = float(price)
        except Exception as exc:
            stale_symbols.append((kind, symbol, rule_ids, f"조회 실패: {exc!r}"))

    if stale_symbols:
        with sf() as s:                 # type: Session
            for kind, symbol, rule_ids, reason in stale_symbols:
                _log_price_stale(s, kind, symbol, rule_ids, reason, now)
                stats["skipped"] += len(rule_ids)
            s.commit()

    for (kind, symbol), rule_ids in targets.items():
        price = prices.get((kind, symbol))
        if price is None:
            continue
        for rule_id in rule_ids:
            try:
                outcome = _process_rule(sf, rule_id, price, now)
            except Exception:
                stats["errors"] += 1    # 한 규칙의 실패가 나머지를 막지 않는다
                continue
            stats[outcome] = stats.get(outcome, 0) + 1
            if outcome == "fired":
                stats["checked"] += 1
    return stats
