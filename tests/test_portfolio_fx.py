"""통화 왕복 환전 제거 (v1.18.0).

예전에는 범용형(KRW 베이스)의 US 매도마다 달러 전액을 원화로 되돌리고, 다음 US 매수에서
다시 달러로 바꿔 왕복 0.2% 를 물었다. 3.2년 리플레이 기준 초기자본의 5.0%p.
이제 매도 대금은 그 통화로 두고, 매수는 부족분만 환전한다.
"""
from datetime import date
from dataclasses import replace

import pytest

from simcore.config import Config
from simcore.engine import Engine, CharacterSpec
from simcore.models import Currency, Market, SymbolSnapshot, TradeReason
from simcore.portfolio import InsufficientCashError, Portfolio

D1, D2, D3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
FX = 1300.0
BOTH = (CharacterSpec("범용형", (Market.KR, Market.US), Currency.KRW),)


def _pf() -> Portfolio:
    return Portfolio("범용형", Currency.KRW, Config())


# ── Portfolio 단위 ───────────────────────────────────────────────────────
def test_buying_power_counts_the_other_currency():
    p = _pf()
    p.cash[Currency.KRW] = 1_300_000.0
    p.cash[Currency.USD] = 1_000.0
    # USD 기준: 보유 1000$ + 130만원 환전분(수수료 0.1% 차감)
    assert p.buying_power(Currency.USD, FX) == pytest.approx(1000 + 1000 * 0.999)
    # KRW 기준: 130만원 + 1000$ 환전분
    assert p.buying_power(Currency.KRW, FX) == pytest.approx(1_300_000 + 1_300_000 * 0.999)


def test_buying_power_is_plain_cash_when_other_currency_empty():
    p = _pf()
    p.cash[Currency.KRW] = 500_000.0
    assert p.buying_power(Currency.KRW, FX) == pytest.approx(500_000.0)


def test_convert_to_krw_takes_only_what_is_needed():
    p = _pf()
    p.cash[Currency.USD] = 1_000.0
    p.convert_to_krw(650_000.0, FX)
    assert p.cash[Currency.KRW] == pytest.approx(650_000.0)
    # 650,000 / (1300 * 0.999) 만큼만 소모 — 전액이 아니다
    assert p.cash[Currency.USD] == pytest.approx(1000 - 650_000 / (1300 * 0.999))
    assert p.cash[Currency.USD] > 0


def test_convert_to_krw_rejects_when_short():
    p = _pf()
    p.cash[Currency.USD] = 1.0
    with pytest.raises(ValueError, match="환전"):
        p.convert_to_krw(1_000_000.0, FX)


def test_ensure_cash_noop_when_already_enough():
    p = _pf()
    p.cash[Currency.USD] = 500.0
    assert p.ensure_cash(Currency.USD, 400.0, FX) is True
    assert p.cash[Currency.KRW] == 0.0        # 환전이 일어나지 않았다


def test_ensure_cash_converts_only_the_shortfall():
    p = _pf()
    p.cash[Currency.USD] = 100.0
    p.cash[Currency.KRW] = 1_300_000.0
    assert p.ensure_cash(Currency.USD, 300.0, FX) is True
    assert p.cash[Currency.USD] == pytest.approx(300.0)
    assert p.cash[Currency.KRW] > 0           # 전액이 아니라 부족분(200$)만 환전


def test_ensure_cash_reports_failure_instead_of_raising():
    p = _pf()
    p.cash[Currency.USD] = 1.0
    assert p.ensure_cash(Currency.USD, 10_000.0, FX) is False


# ── 출금 회귀 가드 ───────────────────────────────────────────────────────
def test_withdraw_can_reach_into_usd():
    """달러를 들고 있어도 원화 출금이 되어야 한다 — 왕복 제거의 부작용 방지."""
    p = _pf()
    p.cash[Currency.KRW] = 100_000.0
    p.cash[Currency.USD] = 1_000.0
    p.withdraw(D1, 500_000.0, FX)
    assert p.cash[Currency.KRW] == pytest.approx(0.0, abs=1e-6)
    assert p.cash[Currency.USD] > 0


def test_withdraw_still_fails_when_total_is_short():
    p = _pf()
    p.cash[Currency.KRW] = 1_000.0
    p.cash[Currency.USD] = 1.0
    with pytest.raises(InsufficientCashError):
        p.withdraw(D1, 10_000_000.0, FX)


# ── 엔진 통합: 매도 후 달러가 남는가 ─────────────────────────────────────
def _engine_with_us_position(price=100.0):
    e = Engine(Config(), characters=BOTH)
    e.start(D1, fx_rate=FX)
    snap = SymbolSnapshot("AAPL", Market.US, ("G1", "G4", "G7"), (), price, 0.0, 1e6,
                          green_score=18, red_score=0, buy_gate=True)
    e.evaluate_close(D1, Market.US, {"AAPL": snap})
    e.fill_open(D2, Market.US, {"AAPL": price}, fx_rate=FX)
    return e


def test_us_sell_keeps_proceeds_in_usd():
    e = _engine_with_us_position()
    pf = e.states["범용형"].portfolio
    assert "AAPL" in pf.positions
    e._sell(e.states["범용형"], D3, "AAPL", 110.0, TradeReason.SIGNAL_SELL, FX)
    assert pf.cash[Currency.USD] > 0, "US 매도 대금이 원화로 되돌아갔다 — 왕복 환전 재발"


def test_rebuy_after_sell_does_not_round_trip(monkeypatch):
    """매도→재매수에서 환전이 일어나지 않아야 한다(달러가 이미 있으므로)."""
    e = _engine_with_us_position()
    st = e.states["범용형"]
    pf = st.portfolio
    e._sell(st, D3, "AAPL", 110.0, TradeReason.SIGNAL_SELL, FX)
    usd_after_sell = pf.cash[Currency.USD]
    krw_after_sell = pf.cash[Currency.KRW]

    calls = []
    orig = pf.convert_to_usd
    monkeypatch.setattr(pf, "convert_to_usd",
                        lambda amt, fx: (calls.append(amt), orig(amt, fx))[1])
    from simcore.engine import PendingBuy
    from simcore.models import DecisionType
    b = PendingBuy("MSFT", Market.US, 3, 18, ("G1", "G4", "G7"), 0.0, 1e6,
                   decision_type=DecisionType.BUY)
    # 슬롯을 크게 잡아 필요한 달러가 보유분보다 작게 — 환전 없이 체결되어야 한다
    assert e._buy(st, D3, b, 50.0, FX, slots=5) is True
    assert calls == [], f"보유 달러로 충분한데 환전이 일어났다: {calls}"
    assert pf.cash[Currency.KRW] == pytest.approx(krw_after_sell)
    assert pf.cash[Currency.USD] < usd_after_sell


def test_buy_converts_only_the_shortfall():
    e = Engine(Config(), characters=BOTH)
    e.start(D1, fx_rate=FX)
    st = e.states["범용형"]
    pf = st.portfolio
    pf.cash[Currency.USD] = 1_000.0            # 원화 1억 + 달러 1000
    from simcore.engine import PendingBuy
    b = PendingBuy("MSFT", Market.US, 3, 18, ("G1",), 0.0, 1e6)
    krw_before = pf.cash[Currency.KRW]
    assert e._buy(st, D3, b, 100.0, FX, slots=1) is True
    assert pf.cash[Currency.USD] == pytest.approx(0.0, abs=1.0), "보유 달러를 먼저 안 썼다"
    assert pf.cash[Currency.KRW] < krw_before   # 부족분만 원화에서 환전


def test_buying_power_includes_usd_for_kr_buy():
    """달러를 들고 있으면 국내 매수 여력도 그만큼 커진다(과소평가 방지)."""
    e = Engine(Config(), characters=BOTH)
    e.start(D1, fx_rate=FX)
    st = e.states["범용형"]
    pf = st.portfolio
    pf.cash[Currency.KRW] = 0.0
    pf.cash[Currency.USD] = 10_000.0
    from simcore.engine import PendingBuy
    b = PendingBuy("005930", Market.KR, 3, 18, ("G1",), 0.0, 1e6)
    assert e._buy(st, D3, b, 10_000.0, FX, slots=1) is True
    assert "005930" in pf.positions
    assert pf.cash[Currency.USD] < 10_000.0     # 필요한 만큼 원화로 환전됨


# ── 단일 시장 캐릭터는 영향 없음 ─────────────────────────────────────────
@pytest.mark.parametrize("name,markets,base", [
    ("국내형", (Market.KR,), Currency.KRW),
    ("해외형", (Market.US,), Currency.USD),
])
def test_single_market_characters_unaffected(name, markets, base):
    e = Engine(Config(), characters=(CharacterSpec(name, markets, base),))
    e.start(D1, fx_rate=FX)
    pf = e.states[name].portfolio
    other = Currency.USD if base == Currency.KRW else Currency.KRW
    assert pf.cash[other] == 0.0
    market = markets[0]
    sym = "005930" if market == Market.KR else "AAPL"
    snap = SymbolSnapshot(sym, market, ("G1", "G4", "G7"), (), 100.0, 0.0, 1e6,
                          green_score=18, red_score=0, buy_gate=True)
    e.evaluate_close(D1, market, {sym: snap})
    e.fill_open(D2, market, {sym: 100.0}, fx_rate=FX)
    assert sym in pf.positions
    assert pf.cash[other] == 0.0, "단일 시장 캐릭터에 반대 통화 잔고가 생겼다"
