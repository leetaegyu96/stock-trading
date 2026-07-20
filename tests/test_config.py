from dataclasses import replace
from simcore.config import Config, SignalScores, TradeRules

IMPLEMENTED_GREEN = ["G1","G2","G3","G4","G5","G6","G7","G10","G11","G12",
                     "G13","G14","G15","G16","G17","G18","G23"]
IMPLEMENTED_RED = ["R1","R2","R3","R4","R5","R6","R11","R12","R13","R14",
                   "R15","R16","R17","R18","R19","R23","R24"]


def test_defaults_match_trading_rules():
    c = Config()
    assert c.rules.buy_score_interest == 12
    assert c.rules.buy_score_candidate == 15
    assert c.rules.buy_score_min == 18
    assert c.rules.sell_partial_min == 9
    assert c.rules.sell_full_min == 11
    assert c.rules.partial_sell_fraction == 0.5
    assert c.rules.stop_loss_pct == -0.07
    assert c.rules.trail_pct == 0.07
    assert c.rules.trailing_top == 0.40
    assert c.rules.max_positions == 5
    assert c.rules.cooldown_days == 2
    assert c.rules.bear_guard_characters == frozenset()
    assert c.costs.kr_commission == 0.00015
    assert c.costs.kr_tax == 0.0015
    assert c.costs.us_commission == 0.0009
    assert c.costs.fx_fee == 0.001
    assert c.costs.slippage == 0.0
    assert c.initial_capital_krw == 100_000_000


def test_override_with_replace():
    c = Config()
    c2 = replace(c, rules=replace(c.rules, buy_score_min=20))
    assert c2.rules.buy_score_min == 20
    assert c.rules.buy_score_min == 18  # 원본 불변


def test_every_implemented_signal_has_score_and_category():
    sc = Config().scores
    for code in IMPLEMENTED_GREEN + IMPLEMENTED_RED:
        assert code in sc.points, f"{code} 점수 없음"
        assert code in sc.category, f"{code} 카테고리 없음"
        assert sc.category[code] in sc.caps, f"{code} 카테고리 상한 없음"


def test_buy_gate_sets_are_implemented_greens():
    sc = Config().scores
    assert set(sc.buy_gate) == {"추세", "돌파", "거래량"}
    for members in sc.buy_gate.values():
        assert members, "게이트 집합이 비어있음"
        assert members <= set(IMPLEMENTED_GREEN)


def test_v2_rules_thresholds_ordered():
    r = TradeRules()
    assert r.buy_score_interest < r.buy_score_candidate < r.buy_score_min
    assert r.sell_partial_min < r.sell_full_min
    assert 0 < r.partial_sell_fraction < 1
    assert r.stop_loss_pct < 0
    # 트레일링 단계: 임계 내림차순, 잠금값 임계보다 낮음
    tiers = r.trailing_tiers
    assert list(tiers) == sorted(tiers, key=lambda t: -t[0])
    for thr, lock in tiers:
        assert lock < thr


def test_v1_fields_removed():
    r = TradeRules()
    assert not hasattr(r, "buy_threshold")
    assert not hasattr(r, "sell_threshold")
    assert not hasattr(r, "take_profit_pct")


def test_intraday_defaults_off_and_conservative():
    r = Config().rules
    assert r.intraday_enabled is False
    assert r.intraday_scan_minutes == 10
    assert r.intraday_max_buys_per_symbol == 3
    assert r.intraday_max_sells_per_symbol == 3
    assert r.intraday_reentry_cooldown_min == 30
    assert r.intraday_daily_loss_halt_pct == -0.05
    assert r.intraday_disparity_period == 20
    assert r.intraday_sr_lookback == 20
    assert r.intraday_strength_buy_min == 100.0
