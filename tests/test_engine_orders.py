from datetime import date
from dataclasses import replace
import pytest
from simcore.config import Config
from simcore.models import Market, Currency, SymbolSnapshot, Side, TradeReason
from simcore.engine import Engine, CharacterSpec

D1, D2, D3, D4 = (date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8), date(2025, 1, 9))
KR_ONLY = (CharacterSpec("국내형", (Market.KR,), Currency.KRW),)

def snap(sym, green=(), red=(), close=100.0, chg=0.0, vol=1000.0, market=Market.KR,
         green_score=0, red_score=0, gate=False):
    return SymbolSnapshot(sym, market, tuple(green), tuple(red), close, chg, vol,
                          green_score=green_score, red_score=red_score, buy_gate=gate)

def make_engine(max_positions=5):
    cfg = Config()
    cfg = replace(cfg, rules=replace(cfg.rules, max_positions=max_positions))
    e = Engine(cfg, characters=KR_ONLY)
    e.start(D1, fx_rate=1300.0)
    return e

def test_buy_when_score_meets_min_and_gate_open():
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G4", "G7"),
                                                green_score=18, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    st = e.states["국내형"]
    assert "A" in st.portfolio.positions
    t = st.portfolio.trades[-1]
    assert t.side == Side.BUY and t.reason == TradeReason.SIGNAL_BUY and t.green_score == 18

def test_priority_higher_score_first_when_slots_limited():
    e = make_engine(max_positions=1)
    snaps = {
        "A": snap("A", green=("G1", "G4"), green_score=18, gate=True),
        "B": snap("B", green=("G1", "G4", "G7"), green_score=23, gate=True),  # 점수 더 높음 → 우선
    }
    e.evaluate_close(D1, Market.KR, snaps)
    e.fill_open(D2, Market.KR, {"A": 100.0, "B": 100.0}, fx_rate=1300.0)
    pos = e.states["국내형"].portfolio.positions
    assert list(pos) == ["B"]

def test_sizing_splits_cash_by_remaining_slots():
    e = make_engine(max_positions=5)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G4", "G7"),
                                                green_score=18, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 10000.0}, fx_rate=1300.0)
    qty = e.states["국내형"].portfolio.positions["A"].quantity
    # 예산 = 1억/5 = 2000만 → 수수료 감안 정수 주
    assert qty == int((100_000_000 / 5) // (10000.0 * 1.00015))

def test_sell_when_red_score_reaches_full_threshold():
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G4", "G7"),
                                                green_score=18, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R4", "R11"), red_score=15)})
    e.fill_open(D3, Market.KR, {"A": 95.0}, fx_rate=1300.0)
    st = e.states["국내형"]
    assert "A" not in st.portfolio.positions
    t = st.portfolio.trades[-1]
    assert t.reason == TradeReason.SIGNAL_SELL and t.red_score == 15

def test_red_signals_ignored_for_unheld_symbol():
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", red=("R1", "R2", "R4", "R5"), red_score=20)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.trades[:] == []  # 롱 온리: 미보유 적신호 무시

def test_cooldown_blocks_rebuy_for_two_sessions():
    e = make_engine()
    def buy_snap():
        return snap("A", green=("G1", "G4", "G7"), green_score=18, gate=True)
    e.evaluate_close(D1, Market.KR, {"A": buy_snap()})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R4", "R11"), red_score=15)})
    e.fill_open(D3, Market.KR, {"A": 100.0}, fx_rate=1300.0)   # 매도 체결(전량 → 쿨다운 시작)
    # 매도 당일(D3) 마감: 쿨다운 2→1, 매수 후보 제외
    e.evaluate_close(D3, Market.KR, {"A": buy_snap()})
    e.fill_open(D4, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" not in e.states["국내형"].portfolio.positions
    # 다음 마감: 쿨다운 1→0, 이제 후보 가능
    e.evaluate_close(D4, Market.KR, {"A": buy_snap()})
    e.fill_open(date(2025, 1, 10), Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" in e.states["국내형"].portfolio.positions

def test_forced_sell_when_close_breaches_locked_stop():
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G4", "G7"),
                                                green_score=18, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    # 종가 92 = 평단 100 대비 -8% (< 잠금손절선 -7%) → close 기준 강제 매도 예약(전량)
    e.evaluate_close(D2, Market.KR, {"A": snap("A", close=92.0)})
    st = e.states["국내형"]
    assert len(st.pending_sells) == 1 and st.pending_sells[0].partial is False

def test_cooldown_decrements_even_when_symbol_missing_from_snaps():
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G4", "G7"),
                                                green_score=18, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R4", "R11"), red_score=15)})
    e.fill_open(D3, Market.KR, {"A": 100.0}, fx_rate=1300.0)   # 매도 체결, 쿨다운 시작
    # A 가 거래정지로 이틀간 스냅샷에서 빠져도 쿨다운은 시장 마감마다 감소해야 함
    e.evaluate_close(D3, Market.KR, {"B": snap("B")})
    e.evaluate_close(D4, Market.KR, {"B": snap("B")})
    assert "A" not in e.states["국내형"].cooldowns


def _snap(sym, green, red, close, gs, rs, gate, change=0.01, vol=1000.0):
    return SymbolSnapshot(sym, Market.KR, tuple(green), tuple(red), close, change, vol,
                          green_score=gs, red_score=rs, buy_gate=gate)


def test_buy_requires_score_and_gate():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    # 18점이지만 게이트 미충족 → 매수 안 함
    s1 = _snap("AAA", ["G1", "G4", "G7"], [], 100.0, 18, 0, gate=False)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": s1})
    assert all(b.symbol != "AAA" for b in eng.states["국내형"].pending_buys)
    # 18점 + 게이트 → 매수 후보
    s2 = _snap("BBB", ["G1", "G7", "G5", "G4"], [], 100.0, 19, 0, gate=True)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"BBB": s2})
    assert any(b.symbol == "BBB" for b in eng.states["국내형"].pending_buys)


def test_buy_below_threshold_rejected():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    s = _snap("AAA", ["G1", "G7", "G5"], [], 100.0, 17, 0, gate=True)  # 17<18
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": s})
    assert not eng.states["국내형"].pending_buys


def test_buy_priority_by_score():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    snaps = {
        "LOW": _snap("LOW", ["G1", "G7", "G5"], [], 100.0, 18, 0, True, change=0.09),
        "HIGH": _snap("HIGH", ["G1", "G4", "G7", "G5"], [], 100.0, 23, 0, True, change=0.01),
    }
    eng.evaluate_close(date(2026, 1, 2), Market.KR, snaps)
    eng.fill_open(date(2026, 1, 5), Market.KR, {"LOW": 100.0, "HIGH": 100.0}, 1300.0)
    # 슬롯 5개라 둘 다 매수되지만, 우선순위 정렬상 HIGH 가 먼저
    assert "HIGH" in eng.states["국내형"].portfolio.positions


ALL_GUARD = frozenset({"국내형", "해외형", "범용형"})


def _buy_snap(sym="AAA"):
    return SymbolSnapshot(sym, Market.KR, ("G1", "G7", "G5", "G4"), (), 100.0, 0.01, 1000.0,
                          green_score=19, red_score=0, buy_gate=True)


def test_bear_guard_blocks_new_buys_when_enabled():
    cfg = replace(Config(), rules=replace(Config().rules, bear_guard_characters=ALL_GUARD))
    eng = Engine(cfg); eng.start(__import__("datetime").date(2026, 1, 2), 1300.0)
    from datetime import date
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: True, Market.US: True})
    assert not eng.states["국내형"].pending_buys        # 하락장 → 매수 차단


def test_bear_guard_off_allows_buys_in_downtrend():
    from datetime import date
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)   # guard off(기본)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: True, Market.US: True})
    assert any(b.symbol == "AAA" for b in eng.states["국내형"].pending_buys)


def test_bear_guard_enabled_but_not_bearish_allows_buys():
    cfg = replace(Config(), rules=replace(Config().rules, bear_guard_characters=ALL_GUARD))
    from datetime import date
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: False, Market.US: False})
    assert any(b.symbol == "AAA" for b in eng.states["국내형"].pending_buys)


def test_bear_guard_still_allows_sells_in_downtrend():
    cfg = replace(Config(), rules=replace(Config().rules, bear_guard_characters=ALL_GUARD))
    from datetime import date
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    # 보유 만들기
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()})  # 평시 매수예약
    eng.fill_open(date(2026, 1, 5), Market.KR, {"AAA": 100.0}, 1300.0)
    # 하락장 + 강한 적신호 → 매도는 정상 예약
    s = SymbolSnapshot("AAA", Market.KR, (), ("R1", "R4", "R11"), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=15, buy_gate=False)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s},
                       bearish_by_market={Market.KR: True, Market.US: True})
    assert any(ps.symbol == "AAA" for ps in eng.states["국내형"].pending_sells)


def test_bear_guard_v2_multimarket_one_bearish_allows_buys():
    # 범용형: KR만 하락 → US·KR 모두 신규매수 허용(all() 미충족)
    from datetime import date
    cfg = replace(Config(), rules=replace(Config().rules, bear_guard_characters=ALL_GUARD))
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: True, Market.US: False})
    assert any(b.symbol == "AAA" for b in eng.states["범용형"].pending_buys)   # 범용형 허용
    assert not eng.states["국내형"].pending_buys                                # 국내형(KR만)은 차단


def test_bear_guard_v2_multimarket_both_bearish_blocks():
    from datetime import date
    cfg = replace(Config(), rules=replace(Config().rules, bear_guard_characters=ALL_GUARD))
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: True, Market.US: True})
    assert not eng.states["범용형"].pending_buys
    assert not eng.states["국내형"].pending_buys


def test_forced_sell_r5r23_records_forced_decision():
    from simcore.models import DecisionType
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1","G4","G7"), green_score=18, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    # R5+R23 강제(점수 8이어도) — red_score 낮게
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R5","R23"), red_score=8)})
    e.fill_open(D3, Market.KR, {"A": 95.0}, fx_rate=1300.0)
    t = [x for x in e.states["국내형"].portfolio.trades if x.side.value=="SELL"][-1]
    assert t.decision_type == DecisionType.FORCED_SELL and t.trigger_rule == "R5+R23"

def test_graded_full_and_partial_and_buy_decision():
    from simcore.models import DecisionType
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1","G4","G7"), green_score=19, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    buy = [x for x in e.states["국내형"].portfolio.trades if x.side.value=="BUY"][-1]
    assert buy.decision_type == DecisionType.BUY and "19" in buy.trigger_rule
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1","R4","R11"), red_score=15)})
    e.fill_open(D3, Market.KR, {"A": 99.0}, fx_rate=1300.0)
    t = [x for x in e.states["국내형"].portfolio.trades if x.side.value=="SELL"][-1]
    assert t.decision_type == DecisionType.FULL_SELL


def test_partial_sell_promotes_to_full_when_rounding_liquidates_whole_position():
    """1주 잔량에서 등급 판정이 PARTIAL_SELL(부분매도)이어도, 반올림 수량
    (max(1, int(1*0.5))==1)이 잔량 전체를 청산하면 라벨이 FULL_SELL로 승격되어야
    한다 — 그렇지 않으면 "부분 매도" 문구가 남아 수량·설명이 불일치한다."""
    from simcore.models import DecisionType
    e = make_engine(max_positions=1)
    # 고가 종목 1주만 매수되도록 가격을 잡는다 (예산 1억 / 1슬롯).
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G4", "G7"),
                                                green_score=19, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 90_000_000.0}, fx_rate=1300.0)
    st = e.states["국내형"]
    assert st.portfolio.positions["A"].quantity == 1

    # red_score=9 → sell_partial_min(9)<=9<11(sell_full_min) → PARTIAL_SELL 판정.
    # close 를 매수가 근처로 둬야 트레일링 스탑(R7 강제매도)로 오분류되지 않는다.
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R4"), red_score=9,
                                                close=91_000_000.0)})
    assert st.pending_sells[0].partial is True
    e.fill_open(D3, Market.KR, {"A": 91_000_000.0}, fx_rate=1300.0)

    assert "A" not in st.portfolio.positions           # 전량 청산됨
    t = [x for x in st.portfolio.trades if x.side.value == "SELL"][-1]
    assert t.quantity == 1
    assert t.decision_type == DecisionType.FULL_SELL   # 라벨 승격


def test_bear_guard_only_listed_characters_blocked():
    # 집합에 든 캐릭터만 차단. 국내형(KR)만 가드 대상 → KR 마감에서 실제 차단 분기 검증.
    # 범용형(KR+US)은 집합 밖이라 양시장 하락에도 매수 허용.
    from datetime import date
    cfg = replace(Config(), rules=replace(Config().rules,
                  bear_guard_characters=frozenset({"국내형"})))
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: True, Market.US: True})
    assert not eng.states["국내형"].pending_buys                              # 대상+전시장하락 → 차단
    assert any(b.symbol == "AAA" for b in eng.states["범용형"].pending_buys)  # 집합 밖 → 허용
