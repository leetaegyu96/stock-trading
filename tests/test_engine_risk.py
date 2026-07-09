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
    cfg = Config()
    e = Engine(cfg, characters=KR_ONLY)
    e.start(D1, fx_rate=1300.0)
    e.evaluate_close(D1, Market.KR, {"A": SymbolSnapshot(
        "A", Market.KR, ("G1", "G4", "G7"), (), price, 0.0, 1000.0,
        green_score=18, red_score=0, buy_gate=True)})
    e.fill_open(D2, Market.KR, {"A": price}, fx_rate=1300.0)
    return e

def test_stop_loss_triggers_at_low():
    e = engine_with_position(100.0)
    e.check_stops(D3, Market.KR, {"A": bar("A", low=90.0, high=95.0)}, fx_rate=1300.0)
    t = e.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.STOP_LOSS
    assert t.price == pytest.approx(93.0)  # 평단 100 × (1-7%)

def test_stop_beats_trailing_update_same_day():
    # 저가가 잠금 손절선을 하회하면 그날 고가로 peak 를 올리기 전에 즉시 손절 트리거
    e = engine_with_position(100.0)
    e.check_stops(D3, Market.KR, {"A": bar("A", low=90.0, high=120.0)}, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.trades[-1].reason == TradeReason.STOP_LOSS
    assert "A" not in e.states["국내형"].portfolio.positions

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


def _buy_one(eng, sym="AAA", price=100.0):
    s = SymbolSnapshot(sym, Market.KR, ("G1", "G7", "G5", "G4"), (), price, 0.01, 1000.0,
                       green_score=19, red_score=0, buy_gate=True)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {sym: s})
    eng.fill_open(date(2026, 1, 5), Market.KR, {sym: price}, 1300.0)


def test_partial_sell_tier_keeps_position_no_cooldown():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    pos = eng.states["국내형"].portfolio.positions["AAA"]
    q0 = pos.quantity
    # red_score 10 (부분매도 구간 9~10)
    s = SymbolSnapshot("AAA", Market.KR, (), ("R1", "R2"), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=10, buy_gate=False)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    eng.fill_open(date(2026, 1, 7), Market.KR, {"AAA": 100.0}, 1300.0)
    assert "AAA" in eng.states["국내형"].portfolio.positions
    assert eng.states["국내형"].portfolio.positions["AAA"].quantity < q0
    assert "AAA" not in eng.states["국내형"].cooldowns       # 부분매도는 쿨다운 없음


def test_full_sell_tier_and_cooldown():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    s = SymbolSnapshot("AAA", Market.KR, (), ("R1", "R4", "R11"), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=15, buy_gate=False)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    eng.fill_open(date(2026, 1, 7), Market.KR, {"AAA": 100.0}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions
    assert "AAA" in eng.states["국내형"].cooldowns


def test_stop_loss_at_minus_7pct():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng, price=100.0)
    bar = DailyBar("AAA", date(2026, 1, 6), 100.0, 100.0, 92.0, 93.0, 1000.0)
    eng.check_stops(date(2026, 1, 6), Market.KR, {"AAA": bar}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions
    t = eng.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.STOP_LOSS
    assert "AAA" in eng.states["국내형"].cooldowns  # check_stops 경로도 쿨다운 등록(_sell 기본값)


def test_trailing_locks_in_gain():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng, price=100.0)
    # 고가 +25% → 잠금 손절 +10% 로 상향
    up = DailyBar("AAA", date(2026, 1, 6), 100.0, 125.0, 100.0, 124.0, 1000.0)
    eng.check_stops(date(2026, 1, 6), Market.KR, {"AAA": up}, 1300.0)
    pos = eng.states["국내형"].portfolio.positions["AAA"]
    assert pos.locked_stop_pct >= 0.10
    # 다음날 +8% 로 하락 → 잠금선(+10%) 하회 → 매도
    down = DailyBar("AAA", date(2026, 1, 7), 120.0, 120.0, 108.0, 109.0, 1000.0)
    eng.check_stops(date(2026, 1, 7), Market.KR, {"AAA": down}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions
    assert eng.states["국내형"].portfolio.trades[-1].reason == TradeReason.TRAILING_STOP
    assert "AAA" in eng.states["국내형"].cooldowns  # 트레일링 매도도 쿨다운 등록


def test_trailing_top_locks_peak_trail_percentage():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng, price=100.0)
    # 고가 +50% (peak_gain 0.50 >= trailing_top 0.40) → 최고가 대비 trail_pct(7%) 트레일 적용
    # 150*(1-0.07)/100 - 1 = 0.395 > 티어 매칭값(0.30) 이므로 트레일 값이 채택되어야 함
    up = DailyBar("AAA", date(2026, 1, 6), 100.0, 150.0, 100.0, 149.0, 1000.0)
    eng.check_stops(date(2026, 1, 6), Market.KR, {"AAA": up}, 1300.0)
    pos = eng.states["국내형"].portfolio.positions["AAA"]
    assert pos.locked_stop_pct >= 0.39
    # 다음날 저가 135 (135/100-1=0.35 < 0.395) → 트레일선 하회 → 매도
    down = DailyBar("AAA", date(2026, 1, 7), 145.0, 145.0, 135.0, 136.0, 1000.0)
    eng.check_stops(date(2026, 1, 7), Market.KR, {"AAA": down}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions
    assert eng.states["국내형"].portfolio.trades[-1].reason == TradeReason.TRAILING_STOP


def test_forced_sell_r5_and_r23():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    # red_score 낮아도 R5+R23 동시 → 강제 전량
    s = SymbolSnapshot("AAA", Market.KR, (), ("R5", "R23"), 100.0, -0.05, 1000.0,
                       green_score=0, red_score=8, buy_gate=False)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    eng.fill_open(date(2026, 1, 7), Market.KR, {"AAA": 100.0}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions


def test_r5_alone_without_r23_is_not_forced():
    # R5+R23 "동시" 조건은 부분집합(subset) 판정이어야 함 — R5 하나만으로는 강제매도가 아님
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    s = SymbolSnapshot("AAA", Market.KR, (), ("R5",), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=4, buy_gate=False)  # 4 < sell_partial_min(9)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    assert eng.states["국내형"].pending_sells == []
    assert "AAA" in eng.states["국내형"].portfolio.positions


def test_low_red_score_no_forced_condition_is_pure_hold():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    s = SymbolSnapshot("AAA", Market.KR, (), ("R1",), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=5, buy_gate=False)  # 5 < sell_partial_min(9)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    assert eng.states["국내형"].pending_sells == []


def test_partial_sell_rounding_up_to_full_close_still_sets_cooldown():
    # 부분매도 목표 수량(quantity*partial_sell_fraction 반올림)이 잔량 전체와 같아지는 경계
    # 상황(예: quantity==1)에서도, 실제로 포지션이 전량 청산됐다면 쿨다운이 걸려야 한다.
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    pos = eng.states["국내형"].portfolio.positions["AAA"]
    pos.quantity = 1
    s = SymbolSnapshot("AAA", Market.KR, (), ("R1", "R2"), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=10, buy_gate=False)  # 부분매도 구간(9~10)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    eng.fill_open(date(2026, 1, 7), Market.KR, {"AAA": 100.0}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions  # 반올림으로 전량 청산됨
    assert "AAA" in eng.states["국내형"].cooldowns                 # 그래도 쿨다운은 걸려야 함
