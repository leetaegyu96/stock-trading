"""매도벽 판정·자동매도 (SPEC §6.2, §6.3, §9.1)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from v2.backend import sellwall, trading
from v2.backend.models import EventLog, Position, SellRule, Trade
from v2.backend.sellwall import STOP_LOSS, TAKE_PROFIT
from v2.backend.trading import TradingError
from v2.tests.factories import (FakeMarket, account_with_position, engine,  # noqa: F401
                                needs_db, new_account, new_position, new_user,
                                session, session_factory)

pytestmark = needs_db

KR = "005930"
OTHER = "000660"


def _rule(session, pos, stop=-5, target=15, qty=None):
    rule = sellwall.set_rule(session, pos, stop, target, qty)
    session.commit()
    return rule


# ---------------------------------------------------------------- 규칙 설정

def test_기본_수량은_보유_전량이고_발동가는_평단_기준(session):
    acct, pos = account_with_position(session, avg_price_minor=10_000, quantity=10)
    rule = _rule(session, pos)
    assert rule.quantity == 10 and rule.active is True
    assert sellwall.trigger_prices(rule, pos) == (9_500, 11_500)


@pytest.mark.parametrize("stop,target", [
    (5, 15),          # 손절이 양수
    (-5, -15),        # 익절이 음수
    (-100, 15),       # 손절 범위 밖
    (-5, 901),        # 익절 범위 밖
])
def test_범위를_벗어난_퍼센트는_INVALID_SELL_RULE(session, stop, target):
    _, pos = account_with_position(session)
    with pytest.raises(TradingError) as e:
        sellwall.set_rule(session, pos, stop, target)
    assert e.value.code == "INVALID_SELL_RULE"
    session.rollback()


def test_보유수량보다_많은_수량은_INVALID_SELL_RULE(session):
    _, pos = account_with_position(session, quantity=10)
    with pytest.raises(TradingError) as e:
        sellwall.set_rule(session, pos, -5, None, quantity=11)
    assert e.value.code == "INVALID_SELL_RULE"
    session.rollback()


def test_둘_다_없으면_규칙_삭제(session):
    _, pos = account_with_position(session)
    _rule(session, pos)
    assert sellwall.set_rule(session, pos, None, None) is None
    session.commit()
    assert session.execute(select(SellRule)).scalars().all() == []
    kinds = [e.kind for e in session.execute(select(EventLog)).scalars()]
    assert "RULE_SET" in kinds and "RULE_CANCEL" in kinds


def test_한쪽만_설정해도_된다(session):
    _, pos = account_with_position(session, avg_price_minor=10_000)
    rule = _rule(session, pos, stop=None, target=20)
    assert sellwall.trigger_prices(rule, pos) == (None, 12_000)


def test_재설정하면_다시_활성화(session):
    _, pos = account_with_position(session)
    rule = _rule(session, pos)
    rule.active = False
    session.commit()
    again = sellwall.set_rule(session, pos, -3, 7)
    session.commit()
    assert again.id == rule.id and again.active is True


# ---------------------------------------------------------------- 판정

def test_경계값은_발동한다(session):
    _, pos = account_with_position(session, avg_price_minor=10_000)
    rule = _rule(session, pos)
    assert sellwall.evaluate(rule, pos, 9_500) == STOP_LOSS      # 정확히 손절선
    assert sellwall.evaluate(rule, pos, 11_500) == TAKE_PROFIT   # 정확히 익절선
    assert sellwall.evaluate(rule, pos, 9_501) is None
    assert sellwall.evaluate(rule, pos, 11_499) is None


def test_비활성_규칙은_발동하지_않는다(session):
    _, pos = account_with_position(session, avg_price_minor=10_000)
    rule = _rule(session, pos)
    rule.active = False
    assert sellwall.evaluate(rule, pos, 9_000) is None


def test_둘_다_충족하면_손절_우선(session):
    """평단 기준 정상 규칙으로는 동시 충족이 나올 수 없으므로, 판정 함수의
    **분기 우선순위 자체**를 비정상 규칙으로 고정한다(SPEC §6.2: 보수적 선택)."""
    _, pos = account_with_position(session, avg_price_minor=10_000)
    weird = SellRule(position_id=pos.id, stop_loss_pct=Decimal("-1"),
                     take_profit_pct=Decimal("-2"), quantity=1, active=True)
    stop, target = sellwall.trigger_prices(weird, pos)
    assert stop == 9_900 and target == 9_800
    assert sellwall.evaluate(weird, pos, 9_850) == STOP_LOSS


# ---------------------------------------------------------------- 감시 1회

def test_익절_발동은_발동선이_아니라_현재가로_체결(session, session_factory):
    acct, pos = account_with_position(session, avg_price_minor=10_000, quantity=10)
    _rule(session, pos)                      # 익절선 11,500
    market = FakeMarket({KR: 12_000})        # 갭 상승 — 발동선보다 유리하게 열렸다

    stats = sellwall.scan_once(session_factory, market)
    assert stats == {"checked": 1, "fired": 1, "skipped": 0, "errors": 0}

    trade = session.execute(select(Trade)).scalar_one()
    assert trade.reason == TAKE_PROFIT
    assert trade.price_minor == 12_000       # 발동선(11,500)이 아니다
    assert trade.quantity == 10

    ev = session.execute(
        select(EventLog).where(EventLog.kind == "AUTO_SELL_FIRED")).scalar_one()
    assert ev.detail_json["trigger_price_minor"] == 11_500
    assert ev.detail_json["fill_price_minor"] == 12_000
    assert ev.detail_json["gap_minor"] == 500


def test_손절_발동시_규칙은_비활성화되고_포지션은_차감(session, session_factory):
    acct, pos = account_with_position(session, avg_price_minor=10_000, quantity=10)
    _rule(session, pos, qty=4)               # 손절선 9,500 · 4주만 판다
    market = FakeMarket({KR: 9_000})

    stats = sellwall.scan_once(session_factory, market)
    assert (stats["fired"], stats["errors"]) == (1, 0)

    session.expire_all()
    assert session.get(Position, pos.id).quantity == 6
    assert session.execute(select(SellRule)).scalar_one().active is False
    assert session.execute(select(Trade)).scalar_one().reason == STOP_LOSS


def test_발동_조건_미충족이면_체결하지_않는다(session, session_factory):
    _, pos = account_with_position(session, avg_price_minor=10_000)
    _rule(session, pos)
    stats = sellwall.scan_once(session_factory, FakeMarket({KR: 10_100}))
    assert stats == {"checked": 1, "fired": 0, "skipped": 0, "errors": 0}
    assert session.execute(select(Trade)).scalars().all() == []


def test_시세_실패면_발동하지_않고_PRICE_STALE_기록(session, session_factory):
    _, pos = account_with_position(session, avg_price_minor=10_000)
    _rule(session, pos)
    stats = sellwall.scan_once(session_factory, FakeMarket({KR: None}))

    assert stats == {"checked": 0, "fired": 0, "skipped": 1, "errors": 0}
    assert session.execute(select(Trade)).scalars().all() == []
    ev = session.execute(
        select(EventLog).where(EventLog.kind == "PRICE_STALE")).scalar_one()
    assert ev.detail_json["symbol"] == KR
    assert session.execute(select(SellRule)).scalar_one().active is True


def test_폴백_시세로는_자동매도하지_않는다(session, session_factory):
    """stale=True 는 '마지막 종가'라는 뜻이다. 남의 돈을 옛 가격으로 팔지 않는다."""
    _, pos = account_with_position(session, avg_price_minor=10_000)
    _rule(session, pos)
    market = FakeMarket()
    market.set(KR, 20_000, stale=True)       # 익절선을 훌쩍 넘지만 오래된 가격

    stats = sellwall.scan_once(session_factory, market)
    assert (stats["fired"], stats["skipped"]) == (0, 1)
    assert session.execute(select(Trade)).scalars().all() == []
    assert session.execute(
        select(EventLog).where(EventLog.kind == "PRICE_STALE")).scalar_one()


def test_멱등_이미_발동한_규칙은_다시_팔지_않는다(session, session_factory):
    _, pos = account_with_position(session, avg_price_minor=10_000, quantity=10)
    _rule(session, pos, qty=4)
    market = FakeMarket({KR: 12_000})

    first = sellwall.scan_once(session_factory, market)
    second = sellwall.scan_once(session_factory, market)

    assert first["fired"] == 1
    assert second == {"checked": 0, "fired": 0, "skipped": 0, "errors": 0}
    assert len(session.execute(select(Trade)).scalars().all()) == 1


def test_같은_종목은_사용자가_여럿이어도_시세_1회_조회(session, session_factory):
    _, pos_a = account_with_position(session, avg_price_minor=10_000)
    user_b = new_user(session)
    acct_b = new_account(session, user_b, "KR")
    pos_b = new_position(session, acct_b, KR, 5, 10_000)
    _rule(session, pos_a)
    _rule(session, pos_b)

    market = FakeMarket({KR: 12_000})
    stats = sellwall.scan_once(session_factory, market)

    assert market.calls == [("KR", KR)]       # 종목당 1회
    assert stats["fired"] == 2


def test_한_규칙의_예외가_나머지를_막지_않는다(session, session_factory, monkeypatch):
    acct, pos_a = account_with_position(session, symbol=KR, avg_price_minor=10_000)
    pos_b = new_position(session, acct, OTHER, 10, 10_000)
    _rule(session, pos_a)
    _rule(session, pos_b)

    real_sell = trading.sell

    def _flaky(sess, account, symbol, *args, **kwargs):
        if symbol == KR:
            raise RuntimeError("일부러 낸 오류")
        return real_sell(sess, account, symbol, *args, **kwargs)

    monkeypatch.setattr(trading, "sell", _flaky)
    stats = sellwall.scan_once(session_factory,
                               FakeMarket({KR: 12_000, OTHER: 12_000}))

    assert stats["errors"] == 1 and stats["fired"] == 1
    symbols = [t.symbol for t in session.execute(select(Trade)).scalars()]
    assert symbols == [OTHER]


def test_markets_필터로_해당_시장만_감시(session, session_factory):
    _, pos = account_with_position(session, avg_price_minor=10_000)
    _rule(session, pos)
    market = FakeMarket({KR: 12_000})
    stats = sellwall.scan_once(session_factory, market, markets={"US"})
    assert stats == {"checked": 0, "fired": 0, "skipped": 0, "errors": 0}
    assert market.calls == []


def test_보유수량이_줄었으면_남은_전량만_판다(session, session_factory):
    acct, pos = account_with_position(session, avg_price_minor=10_000, quantity=10)
    _rule(session, pos)                       # 10주 팔기로 설정
    trading.sell(session, acct, KR, 7, 11_000)   # 사용자가 먼저 7주 수동 매도
    session.commit()

    sellwall.scan_once(session_factory, FakeMarket({KR: 12_000}))
    pos_id = pos.id
    session.expunge_all()
    auto = session.execute(
        select(Trade).where(Trade.reason == TAKE_PROFIT)).scalar_one()
    assert auto.quantity == 3
    assert session.get(Position, pos_id) is None
