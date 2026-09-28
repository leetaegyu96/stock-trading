"""매수·수동매도의 회계 불변식 (SPEC §5, §6.1, §9.1)."""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from v2.backend import trading
from v2.backend.models import (Account, EquitySnapshot, EventLog, Position,
                               SellRule, Trade)
from v2.backend.trading import InvariantViolation, TradingError
from v2.tests.factories import (engine, needs_db, new_account, new_position,  # noqa: F401
                                new_user, session, session_factory)

pytestmark = needs_db

KR = "005930"
US = "AAPL"


def _kr_account(session, cash=100_000_000):
    acct = new_account(session, new_user(session), "KR", cash)
    session.commit()
    return acct


def _us_account(session, cash=10_000_000):      # 10만 달러(센트)
    acct = new_account(session, new_user(session), "US", cash)
    session.commit()
    return acct


# ---------------------------------------------------------------- 매수

def test_매수_현금차감과_평단에_수수료_포함(session):
    acct = _kr_account(session)
    trade = trading.buy(session, acct, KR, 10, 10_000)
    session.commit()

    assert trade.gross_minor == 100_000
    assert trade.fee_minor == 15                 # 100,000 × 0.015%
    assert trade.net_minor == -100_015
    assert acct.cash_minor == 100_000_000 - 100_015

    pos = trading.get_position(session, acct.id, KR)
    assert pos.quantity == 10
    assert pos.avg_price_minor == 10_002         # (100,000+15)/10 = 10,001.5 → 반올림


def test_추가매수_평단_가중평균(session):
    acct = _kr_account(session)
    trading.buy(session, acct, KR, 10, 10_000)
    trading.buy(session, acct, KR, 10, 12_000)
    session.commit()

    pos = trading.get_position(session, acct.id, KR)
    # (10×10,002 + 120,000 + 18) / 20 = 11,001.9 → 11,002
    assert pos.quantity == 20
    assert pos.avg_price_minor == 11_002


def test_현금_부족하면_INSUFFICIENT_CASH(session):
    acct = _kr_account(session, cash=100_000)     # 수수료까지 내기엔 15원 모자란다
    with pytest.raises(TradingError) as e:
        trading.buy(session, acct, KR, 10, 10_000)
    assert e.value.code == "INSUFFICIENT_CASH"
    assert "100,015원" in e.value.message
    session.rollback()
    assert session.get(Account, acct.id).cash_minor == 100_000


@pytest.mark.parametrize("qty", [0, -1, 1.5])
def test_잘못된_수량은_INVALID_QUANTITY(session, qty):
    acct = _kr_account(session)
    with pytest.raises(TradingError) as e:
        trading.buy(session, acct, KR, qty, 10_000)
    assert e.value.code == "INVALID_QUANTITY"


def test_다른_시장_종목은_MARKET_MISMATCH(session):
    acct = _kr_account(session)
    with pytest.raises(TradingError) as e:
        trading.buy(session, acct, US, 1, 190)
    assert e.value.code == "MARKET_MISMATCH"


def test_가격이_0이면_PRICE_UNAVAILABLE(session):
    acct = _kr_account(session)
    with pytest.raises(TradingError) as e:
        trading.buy(session, acct, KR, 1, 0)
    assert e.value.code == "PRICE_UNAVAILABLE"


def test_매수_이벤트와_자산스냅샷_기록(session):
    acct = _kr_account(session)
    trading.buy(session, acct, KR, 10, 10_000, stale=True)
    session.commit()

    ev = session.execute(select(EventLog).where(EventLog.kind == "BUY")).scalar_one()
    assert ev.account_id == acct.id and ev.detail_json["stale"] is True
    snap = session.execute(select(EquitySnapshot)).scalar_one()
    assert snap.equity_minor == acct.cash_minor + 10 * 10_000
    assert session.execute(select(Trade)).scalar_one().stale_price is True


# ---------------------------------------------------------------- 매도

def test_부분매도는_평단_유지하고_수량만_차감(session):
    acct = _kr_account(session)
    trading.buy(session, acct, KR, 10, 10_000)
    session.commit()
    cash_after_buy = acct.cash_minor

    trade = trading.sell(session, acct, KR, 4, 11_000)
    session.commit()

    # gross 44,000 · fee 7(=6.6 반올림) · tax 66 → 입금 43,927
    assert (trade.gross_minor, trade.fee_minor, trade.tax_minor) == (44_000, 7, 66)
    assert trade.net_minor == 43_927
    assert trade.realized_pnl_minor == (11_000 - 10_002) * 4 - 7 - 66
    assert acct.cash_minor == cash_after_buy + 43_927

    pos = trading.get_position(session, acct.id, KR)
    assert (pos.quantity, pos.avg_price_minor) == (6, 10_002)


def test_전량매도시_포지션과_매도벽_함께_삭제(session):
    acct = _kr_account(session)
    trading.buy(session, acct, KR, 10, 10_000)
    pos = trading.get_position(session, acct.id, KR)
    session.add(SellRule(position_id=pos.id, stop_loss_pct=-5, take_profit_pct=15,
                         quantity=10, active=True))
    session.commit()

    trading.sell(session, acct, KR, 10, 11_000)
    session.commit()

    assert trading.get_position(session, acct.id, KR) is None
    assert session.execute(select(SellRule)).scalars().all() == []


def test_보유수량_초과_매도는_INSUFFICIENT_QUANTITY(session):
    acct = _kr_account(session)
    trading.buy(session, acct, KR, 3, 10_000)
    session.commit()
    with pytest.raises(TradingError) as e:
        trading.sell(session, acct, KR, 4, 10_000)
    assert e.value.code == "INSUFFICIENT_QUANTITY"


def test_보유하지_않은_종목_매도(session):
    acct = _kr_account(session)
    with pytest.raises(TradingError) as e:
        trading.sell(session, acct, KR, 1, 10_000)
    assert e.value.code == "INSUFFICIENT_QUANTITY"


def test_KR매도에는_거래세_US매도에는_없음(session):
    kr = _kr_account(session)
    trading.buy(session, kr, KR, 10, 10_000)
    kr_trade = trading.sell(session, kr, KR, 10, 10_000)
    session.commit()
    assert kr_trade.tax_minor == 150            # 100,000 × 0.15%

    us = _us_account(session)
    trading.buy(session, us, US, 10, 190.50)    # 센트 단위로 환산되어 저장된다
    us_trade = trading.sell(session, us, US, 10, 190.50)
    session.commit()
    assert us_trade.tax_minor == 0
    assert us_trade.gross_minor == 190_500      # 19,050센트 × 10주
    assert us_trade.fee_minor == 171            # 190,500 × 0.09% = 171.45 → 171


def test_매도_이유와_규칙id_기록(session):
    acct = _kr_account(session)
    trading.buy(session, acct, KR, 10, 10_000)
    trade = trading.sell(session, acct, KR, 10, 12_000,
                         reason="AUTO_TAKE_PROFIT", sell_rule_id=42)
    session.commit()
    assert (trade.reason, trade.sell_rule_id) == ("AUTO_TAKE_PROFIT", 42)


# ---------------------------------------------------------------- 불변식

def test_원장과_잔고가_일치한다(session):
    acct = _kr_account(session)
    trading.buy(session, acct, KR, 10, 10_000)
    trading.buy(session, acct, KR, 5, 11_000)
    trading.sell(session, acct, KR, 7, 12_000)
    session.commit()

    assert trading.ledger_cash(session, acct) == acct.cash_minor
    trading.assert_invariants(session, acct)


def test_현금이_음수면_불변식_위반(session):
    # DB CHECK 까지 가기 전에 코드가 먼저 막는지 본다(세션에 붙지 않은 임시 객체).
    ghost = Account(id=10 ** 9, user_id=1, kind="KR", currency="KRW",
                    cash_minor=-1, seed_minor=0)
    with pytest.raises(InvariantViolation):
        trading.assert_invariants(session, ghost)


def test_DB도_음수_현금을_거부한다(session):
    """코드 버그로 불변식 검사를 건너뛰더라도 DB CHECK 가 마지막 방어선이다."""
    acct = _kr_account(session, cash=1_000)
    acct.cash_minor = -1
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_원장과_잔고가_어긋나면_불변식_위반(session):
    acct = _kr_account(session)
    trading.buy(session, acct, KR, 10, 10_000)
    session.commit()
    acct.cash_minor += 1            # 원장에 없는 현금
    with pytest.raises(InvariantViolation):
        trading.assert_invariants(session, acct)
    session.rollback()


# ---------------------------------------------------------------- 동시성

def test_동시_매수_2건에_잔고_음수_없음(session_factory, session):
    """같은 계정을 두 탭에서 동시에 주문해도 계정 행 잠금이 직렬화한다(SPEC §5.2).

    한 건만 통과할 만큼만 현금을 준다 — 잠금이 없으면 둘 다 통과해 잔고가 음수가 된다.
    """
    acct = _kr_account(session, cash=150_000)     # 100,015원짜리 주문은 1건만 가능
    acct_id = acct.id
    session.commit()

    results: list[object] = []
    ready = threading.Barrier(2)

    def _order():
        s = session_factory()
        try:
            ready.wait(timeout=5)
            trading.buy(s, acct_id, KR, 10, 10_000)
            s.commit()
            results.append("ok")
        except TradingError as exc:
            s.rollback()
            results.append(exc.code)
        except Exception as exc:                  # 예기치 못한 실패도 드러나게
            s.rollback()
            results.append(repr(exc))
        finally:
            s.close()

    threads = [threading.Thread(target=_order) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert sorted(results) == ["INSUFFICIENT_CASH", "ok"]
    session.expire_all()
    fresh = session.get(Account, acct_id)
    assert fresh.cash_minor == 150_000 - 100_015
    assert fresh.cash_minor >= 0
    assert len(session.execute(select(Trade)).scalars().all()) == 1
    trading.assert_invariants(session, fresh)
