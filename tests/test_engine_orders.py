from datetime import date
from dataclasses import replace
import pytest
from simcore.config import Config
from simcore.models import Market, Currency, SymbolSnapshot, Side, TradeReason
from simcore.engine import Engine, CharacterSpec

D1, D2, D3, D4 = (date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8), date(2025, 1, 9))
KR_ONLY = (CharacterSpec("국내형", (Market.KR,), Currency.KRW),)

def snap(sym, green=(), red=(), close=100.0, chg=0.0, vol=1000.0, market=Market.KR):
    return SymbolSnapshot(sym, market, tuple(green), tuple(red), close, chg, vol)

def make_engine(buy_threshold=3, max_positions=5):
    cfg = Config()
    cfg = replace(cfg, rules=replace(cfg.rules, buy_threshold=buy_threshold,
                                     max_positions=max_positions))
    e = Engine(cfg, characters=KR_ONLY)
    e.start(D1, fx_rate=1300.0)
    return e

def test_buy_when_green_meets_threshold():
    e = make_engine(buy_threshold=3)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G2", "G4"))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    st = e.states["국내형"]
    assert "A" in st.portfolio.positions
    t = st.portfolio.trades[-1]
    assert t.side == Side.BUY and t.reason == TradeReason.SIGNAL_BUY and t.green_count == 3

def test_no_buy_below_threshold():
    e = make_engine(buy_threshold=3)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G2"))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.positions == {}

def test_priority_more_greens_first_when_slots_limited():
    e = make_engine(buy_threshold=2, max_positions=1)
    snaps = {
        "A": snap("A", green=("G1", "G2")),
        "B": snap("B", green=("G1", "G2", "G4")),  # 신호 더 많음 → 우선
    }
    e.evaluate_close(D1, Market.KR, snaps)
    e.fill_open(D2, Market.KR, {"A": 100.0, "B": 100.0}, fx_rate=1300.0)
    pos = e.states["국내형"].portfolio.positions
    assert list(pos) == ["B"]

def test_sizing_splits_cash_by_remaining_slots():
    e = make_engine(buy_threshold=1, max_positions=5)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D2, Market.KR, {"A": 10000.0}, fx_rate=1300.0)
    qty = e.states["국내형"].portfolio.positions["A"].quantity
    # 예산 = 1억/5 = 2000만 → 수수료 감안 정수 주
    assert qty == int((100_000_000 / 5) // (10000.0 * 1.00015))

def test_sell_when_red_meets_threshold():
    e = make_engine(buy_threshold=1)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R2", "R4"))})
    e.fill_open(D3, Market.KR, {"A": 95.0}, fx_rate=1300.0)
    st = e.states["국내형"]
    assert "A" not in st.portfolio.positions
    t = st.portfolio.trades[-1]
    assert t.reason == TradeReason.SIGNAL_SELL and t.red_count == 3

def test_red_signals_ignored_for_unheld_symbol():
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", red=("R1", "R2", "R4", "R5"))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.trades[:] == []  # 롱 온리: 미보유 적신호 무시

def test_cooldown_blocks_rebuy_for_two_sessions():
    e = make_engine(buy_threshold=1)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R2", "R4"))})
    e.fill_open(D3, Market.KR, {"A": 100.0}, fx_rate=1300.0)   # 매도 체결
    # 매도 당일(D3) 마감: 쿨다운 2→1, 매수 후보 제외
    e.evaluate_close(D3, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D4, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" not in e.states["국내형"].portfolio.positions
    # 다음 마감: 쿨다운 1→0, 이제 후보 가능
    e.evaluate_close(D4, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(date(2025, 1, 10), Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" in e.states["국내형"].portfolio.positions

def test_r7_close_based_counts_toward_sell_threshold():
    e = make_engine(buy_threshold=1)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    # 종가 92 = 평단 100 대비 -8% → R7 추가, R1·R2 와 합쳐 3개 도달
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R2"), close=92.0)})
    st = e.states["국내형"]
    assert len(st.pending_sells) == 1 and "R7" in st.pending_sells[0].fired
