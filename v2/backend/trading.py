"""매수·수동매도 (SPEC §5, §6.1).

모든 금액은 `money.py` 의 정수 최소단위 함수로만 계산한다. 부동소수로 현금을 누적하면
원장(trades)과 잔고(accounts.cash_minor)가 서서히 어긋나고, 그 어긋남은 나중에 절대
되짚을 수 없다. 그래서 매 체결 직후 불변식을 검사해 **틀리면 즉시 터뜨린다**.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from v2.backend.models import (Account, EquitySnapshot, EventLog, Position, Trade)
from v2.backend.money import buy_costs, sell_costs, to_minor


class TradingError(Exception):
    """도메인 오류. `code` 는 SPEC §7 의 오류 코드 문자열 그대로이며 HTTP 계층이
    이 값을 그대로 API 오류 코드로 내보낸다. `message` 는 초보가 읽을 한국어."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class InvariantViolation(TradingError):
    """회계 불변식 위반 — 사용자 입력이 아니라 **코드 버그**다. 여기까지 왔다면
    트랜잭션을 반드시 롤백해야 한다(HTTP 계층에서는 500)."""

    def __init__(self, message: str) -> None:
        super().__init__("INVARIANT_VIOLATION", message)


# ---------------------------------------------------------------- 보조

def market_of(symbol: str) -> str:
    """종목코드로 시장 추정. KR 은 숫자 6자리, US 는 알파벳 티커."""
    return "KR" if symbol.isdigit() else "US"


def fmt_money(minor: int, currency: str) -> str:
    """오류 메시지용 금액 표기. 초보가 읽는 문장에 들어가므로 통화 기호까지 붙인다."""
    if currency == "KRW":
        return f"{minor:,}원"
    return f"${Decimal(minor) / 100:,.2f}"


def _round(v: Decimal) -> int:
    return int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _check_quantity(quantity: Any) -> int:
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise TradingError("INVALID_QUANTITY", "수량은 1주 이상의 정수여야 합니다.")
    return quantity


def _price_minor(price: Any, currency: str) -> int:
    try:
        minor = to_minor(price, currency)
    except Exception:
        raise TradingError("PRICE_UNAVAILABLE", "가격을 확인할 수 없습니다.")
    if minor <= 0:
        raise TradingError("PRICE_UNAVAILABLE", "가격을 확인할 수 없습니다.")
    return minor


def lock_account(session: Session, account: Account | int) -> Account:
    """계정 행을 `SELECT ... FOR UPDATE` 로 잠근다(SPEC §5.2).

    두 탭에서 동시에 주문하거나 감시 잡과 수동 매도가 겹칠 때 잔고가 음수가 되는 것을
    막는 유일한 방어선이다. 매수·매도·자동매도가 모두 이 함수를 공유한다."""
    account_id = account.id if isinstance(account, Account) else int(account)
    row = session.execute(
        select(Account).where(Account.id == account_id).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise TradingError("NOT_FOUND", "계좌를 찾을 수 없습니다.")
    return row


def get_position(session: Session, account_id: int, symbol: str) -> Position | None:
    return session.execute(
        select(Position).where(Position.account_id == account_id,
                               Position.symbol == symbol)
    ).scalar_one_or_none()


def log_event(session: Session, account: Account, kind: str, detail: dict,
              now: datetime | None = None) -> EventLog:
    ev = EventLog(user_id=account.user_id if account else None,
                  account_id=account.id if account else None,
                  kind=kind, detail_json=detail, ts=now or datetime.now())
    session.add(ev)
    return ev


# ---------------------------------------------------------------- 불변식

def ledger_cash(session: Session, account: Account) -> int:
    """원장이 말하는 현금 = 초기자금 + Σ(체결 net). 잔고와 반드시 같아야 한다."""
    total = session.execute(
        select(func.coalesce(func.sum(Trade.net_minor), 0))
        .where(Trade.account_id == account.id)
    ).scalar_one()
    return int(account.seed_minor) + int(total)


def position_value(session: Session, account: Account,
                   prices_minor: dict[str, int] | None = None) -> int:
    """보유 평가액. 시세를 모르는 종목은 평단(=취득원가)으로 친다 — 스냅샷이 시세
    조회 실패 때문에 통째로 비는 것보다 원가 기준이라도 남기는 편이 낫다."""
    prices_minor = prices_minor or {}
    rows = session.execute(
        select(Position).where(Position.account_id == account.id)).scalars().all()
    return sum(p.quantity * int(prices_minor.get(p.symbol, p.avg_price_minor))
               for p in rows)


def assert_invariants(session: Session, account: Account) -> None:
    """SPEC §2.2 불변식 1~3. 위반이면 예외 → 호출자가 롤백한다."""
    session.flush()
    if account.cash_minor < 0:
        raise InvariantViolation(
            f"현금이 음수입니다(account={account.id}, cash={account.cash_minor}).")
    rows = session.execute(
        select(Position).where(Position.account_id == account.id)).scalars().all()
    for p in rows:
        if p.quantity <= 0:
            raise InvariantViolation(
                f"수량이 0 이하인 포지션이 남아 있습니다(position={p.id}, {p.symbol}).")
    expected = ledger_cash(session, account)
    if expected != account.cash_minor:
        raise InvariantViolation(
            f"원장과 잔고 불일치(account={account.id}): 원장 {expected} ≠ 잔고 "
            f"{account.cash_minor}.")


def record_equity(session: Session, account: Account,
                  prices_minor: dict[str, int] | None = None,
                  now: datetime | None = None) -> EquitySnapshot:
    """자산곡선 한 점. (account_id, ts) 가 유니크라 같은 시각 재기록은 덮어쓴다."""
    ts = now or datetime.now()
    equity = int(account.cash_minor) + position_value(session, account, prices_minor)
    existing = session.execute(
        select(EquitySnapshot).where(EquitySnapshot.account_id == account.id,
                                     EquitySnapshot.ts == ts)).scalar_one_or_none()
    if existing is not None:
        existing.equity_minor = equity
        return existing
    snap = EquitySnapshot(account_id=account.id, ts=ts, equity_minor=equity)
    session.add(snap)
    return snap


# ---------------------------------------------------------------- 매수

def buy(session: Session, account: Account | int, symbol: str, quantity: int,
        price, stale: bool = False, now: datetime | None = None) -> Trade:
    """시장가 즉시 체결 매수(SPEC §5).

    `price` 는 **사람 단위 가격**(원 / 달러)이며 내부에서 최소단위로 변환한다.
    체결가는 주문 시점 현재가이고 슬리피지는 0 이다(모의투자).
    """
    quantity = _check_quantity(quantity)
    now = now or datetime.now()
    acct = lock_account(session, account)
    if market_of(symbol) != acct.kind:
        raise TradingError(
            "MARKET_MISMATCH",
            f"{acct.kind} 캐릭터로는 {symbol} 을(를) 살 수 없습니다. 같은 시장의 종목만 거래됩니다.")

    price_minor = _price_minor(price, acct.currency)
    gross = price_minor * quantity
    fee = buy_costs(gross, acct.kind)
    need = gross + fee
    if need > acct.cash_minor:
        raise TradingError(
            "INSUFFICIENT_CASH",
            f"현금이 부족합니다. {fmt_money(need, acct.currency)}이 필요한데 잔고는 "
            f"{fmt_money(acct.cash_minor, acct.currency)}입니다.")

    acct.cash_minor -= need

    pos = get_position(session, acct.id, symbol)
    if pos is None:
        # 평단에 매수 수수료를 포함해, 손익이 '실제로 쓴 돈' 기준이 되게 한다(SPEC §5.1).
        pos = Position(account_id=acct.id, symbol=symbol, quantity=quantity,
                       avg_price_minor=_round(Decimal(need) / quantity), opened_at=now)
        session.add(pos)
    else:
        new_qty = pos.quantity + quantity
        pos.avg_price_minor = _round(
            (Decimal(pos.quantity) * pos.avg_price_minor + need) / new_qty)
        pos.quantity = new_qty

    trade = Trade(account_id=acct.id, symbol=symbol, side="BUY", quantity=quantity,
                  price_minor=price_minor, fee_minor=fee, tax_minor=0,
                  gross_minor=gross, net_minor=-need, realized_pnl_minor=None,
                  reason="MANUAL", sell_rule_id=None, stale_price=bool(stale),
                  executed_at=now)
    session.add(trade)
    log_event(session, acct, "BUY", {
        "symbol": symbol, "quantity": quantity, "price_minor": price_minor,
        "fee_minor": fee, "net_minor": -need, "stale": bool(stale),
        "avg_price_minor": pos.avg_price_minor}, now)
    session.flush()
    assert_invariants(session, acct)
    record_equity(session, acct, {symbol: price_minor}, now)
    return trade


# ---------------------------------------------------------------- 매도

def sell(session: Session, account: Account | int, symbol: str, quantity: int,
         price, reason: str = "MANUAL", sell_rule_id: int | None = None,
         stale: bool = False, now: datetime | None = None,
         trigger_price_minor: int | None = None) -> Trade:
    """수동·자동 공용 매도(SPEC §6.1). 자동매도는 `reason` 과 `sell_rule_id` 만 다르다.

    부분 매도는 평단을 유지하고 수량만 줄인다(평단은 '얼마에 샀나'이지 '얼마가 남았나'가
    아니다). 전량 매도면 포지션 행을 지우고 매도벽도 함께 사라진다(CASCADE).
    """
    quantity = _check_quantity(quantity)
    now = now or datetime.now()
    acct = lock_account(session, account)
    if market_of(symbol) != acct.kind:
        raise TradingError(
            "MARKET_MISMATCH",
            f"{acct.kind} 캐릭터로는 {symbol} 을(를) 팔 수 없습니다.")

    pos = get_position(session, acct.id, symbol)
    if pos is None:
        raise TradingError("INSUFFICIENT_QUANTITY", f"{symbol} 보유 수량이 없습니다.")
    if quantity > pos.quantity:
        raise TradingError(
            "INSUFFICIENT_QUANTITY",
            f"보유 수량이 부족합니다. {quantity}주를 팔려 했지만 {pos.quantity}주만 갖고 있습니다.")

    price_minor = _price_minor(price, acct.currency)
    gross = price_minor * quantity
    fee, tax = sell_costs(gross, acct.kind)       # 거래세는 KR 매도에만 붙는다
    net = gross - fee - tax
    avg = int(pos.avg_price_minor)
    realized = (price_minor - avg) * quantity - fee - tax

    acct.cash_minor += net
    if quantity == pos.quantity:
        session.delete(pos)                        # 수량 0 인 포지션은 남기지 않는다
    else:
        pos.quantity -= quantity                   # 평단은 그대로

    trade = Trade(account_id=acct.id, symbol=symbol, side="SELL", quantity=quantity,
                  price_minor=price_minor, fee_minor=fee, tax_minor=tax,
                  gross_minor=gross, net_minor=net, realized_pnl_minor=realized,
                  reason=reason, sell_rule_id=sell_rule_id, stale_price=bool(stale),
                  trigger_price_minor=trigger_price_minor, executed_at=now)
    session.add(trade)
    log_event(session, acct, "SELL", {
        "symbol": symbol, "quantity": quantity, "price_minor": price_minor,
        "fee_minor": fee, "tax_minor": tax, "net_minor": net,
        "realized_pnl_minor": realized, "reason": reason,
        "sell_rule_id": sell_rule_id, "stale": bool(stale)}, now)
    session.flush()
    assert_invariants(session, acct)
    record_equity(session, acct, {symbol: price_minor}, now)
    return trade
