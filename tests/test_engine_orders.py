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
