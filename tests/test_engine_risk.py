from datetime import date
from dataclasses import replace
import pytest
from simcore.config import Config
from simcore.models import Market, Currency, DailyBar, SymbolSnapshot, TradeReason
from simcore.engine import Engine, CharacterSpec
from simcore.portfolio import InsufficientCashError

D1, D2, D3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
KR_ONLY = (CharacterSpec("국내형", (Market.KR,), Currency.KRW),)

def bar(sym, low, high, d=D3, close=None):
    c = close if close is not None else (low + high) / 2
    return DailyBar(sym, d, c, high, low, c, 1000.0)

def engine_with_position(price=100.0):
    cfg = replace(Config(), rules=replace(Config().rules, buy_threshold=1))
    e = Engine(cfg, characters=KR_ONLY)
    e.start(D1, fx_rate=1300.0)
    e.evaluate_close(D1, Market.KR, {"A": SymbolSnapshot(
        "A", Market.KR, ("G1",), (), price, 0.0, 1000.0)})
    e.fill_open(D2, Market.KR, {"A": price}, fx_rate=1300.0)
    return e

def test_stop_loss_triggers_at_low():
    e = engine_with_position(100.0)
    e.check_stops(D3, Market.KR, {"A": bar("A", low=90.0, high=95.0)}, fx_rate=1300.0)
    t = e.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.STOP_LOSS
    assert t.price == pytest.approx(93.0)  # 평단 100 × (1-7%)

def test_take_profit_triggers_at_high():
    e = engine_with_position(100.0)
    e.check_stops(D3, Market.KR, {"A": bar("A", low=110.0, high=120.0)}, fx_rate=1300.0)
    t = e.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.TAKE_PROFIT
    assert t.price == pytest.approx(115.0)

def test_stop_beats_take_when_both_hit_same_day():
    e = engine_with_position(100.0)
    e.check_stops(D3, Market.KR, {"A": bar("A", low=90.0, high=120.0)}, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.trades[-1].reason == TradeReason.STOP_LOSS

def test_deposit_flow():
    e = engine_with_position()
    before = e.states["국내형"].portfolio.cash[Currency.KRW]
    e.apply_flow(D3, "국내형", 50_000_000, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.cash[Currency.KRW] == pytest.approx(before + 50_000_000)

def test_withdrawal_with_user_selected_liquidation():
    e = engine_with_position(100.0)
    st = e.states["국내형"]
    cash = st.portfolio.cash[Currency.KRW]
    # 현금보다 큰 출금 → 청산 지정 없으면 에러
    with pytest.raises(InsufficientCashError):
        e.apply_flow(D3, "국내형", -(cash + 1_000_000), fx_rate=1300.0)
    # 사용자가 A 청산을 지정하면 성공
    e.apply_flow(D3, "국내형", -(cash + 1_000_000), fx_rate=1300.0,
                 open_prices={"A": 100.0}, liquidate=("A",))
    assert "A" not in st.portfolio.positions
    t = [t for t in st.portfolio.trades if t.reason == TradeReason.USER_WITHDRAWAL]
    assert len(t) == 1
    assert "A" in st.cooldowns  # 출금 청산도 쿨다운 적용

def test_snapshot_reports_equity_per_character():
    e = engine_with_position(100.0)
    eq = e.snapshot({"A": 110.0}, fx_rate=1300.0)
    assert eq["국내형"] > 100_000_000  # 10% 평가이익 반영
