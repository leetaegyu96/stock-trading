"""signal_sell_enabled 토글 — 점수 매도만 끄고 강제매도는 남는다.

근거: docs/reviews/2026-09-02-live-loss-autopsy.html
라이브 6주에서 손실은 전부 적신호 점수 매도(특히 red>=11 전량매도)에서 나왔고,
손절/트레일만 남긴 구성이 3.2년 리플레이 + 3구간 워크포워드에서 일관되게 우세했다.
"""
from datetime import date, datetime
from dataclasses import replace

import pytest

from simcore.config import Config
from simcore.engine import Engine, CharacterSpec
from simcore.models import (Currency, DailyBar, DecisionType, Market, Side,
                            SymbolSnapshot, TradeReason)

D1, D2, D3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
KR_ONLY = (CharacterSpec("국내형", (Market.KR,), Currency.KRW),)


def _engine(signal_sell: bool, intraday: bool = False) -> Engine:
    cfg = Config(rules=replace(Config().rules,
                               signal_sell_enabled=signal_sell,
                               intraday_enabled=intraday))
    return Engine(cfg, characters=KR_ONLY)


def _with_position(signal_sell: bool, intraday: bool = False, price: float = 100.0):
    e = _engine(signal_sell, intraday)
    e.start(D1, fx_rate=1300.0)
    e.evaluate_close(D1, Market.KR, {"A": SymbolSnapshot(
        "A", Market.KR, ("G1", "G4", "G7"), (), price, 0.0, 1000.0,
        green_score=18, red_score=0, buy_gate=True)})
    e.fill_open(D2, Market.KR, {"A": price}, fx_rate=1300.0)
    assert "A" in e.states["국내형"].portfolio.positions
    return e


def _snap(red: tuple, red_score: int, close: float = 100.0) -> dict:
    return {"A": SymbolSnapshot("A", Market.KR, (), red, close, 0.0, 1000.0,
                                green_score=0, red_score=red_score, buy_gate=False)}


# ── 기본값은 기존 동작 그대로 ────────────────────────────────────────────
def test_default_is_enabled():
    assert Config().rules.signal_sell_enabled is True


# ── 마감 경로 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("red_score,expected", [(11, DecisionType.FULL_SELL),
                                                (9, DecisionType.PARTIAL_SELL)])
def test_close_score_sell_fires_when_enabled(red_score, expected):
    e = _with_position(signal_sell=True)
    e.evaluate_close(D2, Market.KR, _snap(("R1", "R13"), red_score))
    pend = e.states["국내형"].pending_sells
    assert len(pend) == 1 and pend[0].decision_type == expected


@pytest.mark.parametrize("red_score", [9, 11, 20, 42])
def test_close_score_sell_suppressed_when_disabled(red_score):
    e = _with_position(signal_sell=False)
    e.evaluate_close(D2, Market.KR, _snap(("R1", "R13"), red_score))
    assert e.states["국내형"].pending_sells == []


def test_close_forced_sell_survives_r18_when_disabled():
    """지지선 붕괴(R18)는 점수 매도가 꺼져도 강제 전량매도로 남아야 한다."""
    e = _with_position(signal_sell=False)
    e.evaluate_close(D2, Market.KR, _snap(("R18",), 5))
    pend = e.states["국내형"].pending_sells
    assert len(pend) == 1
    assert pend[0].decision_type == DecisionType.FORCED_SELL
    assert pend[0].trigger_rule == "R18"


def test_close_forced_sell_survives_r5_r23_when_disabled():
    e = _with_position(signal_sell=False)
    e.evaluate_close(D2, Market.KR, _snap(("R5", "R23"), 8))
    pend = e.states["국내형"].pending_sells
    assert len(pend) == 1 and pend[0].trigger_rule == "R5+R23"


def test_close_forced_stop_price_survives_when_disabled():
    """종가가 잠금 손절선(-7%) 아래면 점수 매도가 꺼져 있어도 강제 청산된다."""
    e = _with_position(signal_sell=False, price=100.0)
    e.evaluate_close(D2, Market.KR, _snap((), 0, close=92.0))
    pend = e.states["국내형"].pending_sells
    assert len(pend) == 1 and pend[0].trigger_rule == "R7"


# ── 손절/트레일링(check_stops)은 토글과 무관 ─────────────────────────────
def test_stop_loss_unaffected_by_toggle():
    e = _with_position(signal_sell=False, price=100.0)
    e.check_stops(D3, Market.KR, {"A": DailyBar("A", D3, 92.0, 95.0, 90.0, 92.0, 1000.0)},
                  fx_rate=1300.0)
    t = e.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.STOP_LOSS
    assert "A" not in e.states["국내형"].portfolio.positions


def test_trailing_still_ratchets_when_disabled():
    """점수 매도가 꺼져도 peak 추적·잠금 손절선 상향은 계속된다(+10% → 본전 잠금)."""
    e = _with_position(signal_sell=False, price=100.0)
    e.check_stops(D3, Market.KR, {"A": DailyBar("A", D3, 100.0, 115.0, 99.0, 112.0, 1000.0)},
                  fx_rate=1300.0)
    pos = e.states["국내형"].portfolio.positions["A"]
    assert pos.peak_price == pytest.approx(115.0)
    assert pos.locked_stop_pct == pytest.approx(0.0)   # +10% 티어 → 평단 잠금


# ── 장중 경로 ────────────────────────────────────────────────────────────
def _intraday(e: Engine, snaps: dict):
    eq = {"국내형": 100_000_000.0}
    e.evaluate_intraday(D2, Market.KR, snaps, {}, 1300.0,
                        datetime(2025, 1, 7, 10, 0), day_equity=eq, cur_equity=eq)


def test_intraday_score_sell_fires_when_enabled():
    e = _with_position(signal_sell=True, intraday=True)
    _intraday(e, _snap(("R1", "R13"), 14))
    sells = [t for t in e.states["국내형"].portfolio.trades if t.side == Side.SELL]
    assert len(sells) == 1 and sells[0].decision_type == DecisionType.INTRADAY_SELL


@pytest.mark.parametrize("red_score", [9, 11, 20, 42])
def test_intraday_score_sell_suppressed_when_disabled(red_score):
    e = _with_position(signal_sell=False, intraday=True)
    _intraday(e, _snap(("R1", "R13"), red_score))
    assert [t for t in e.states["국내형"].portfolio.trades if t.side == Side.SELL] == []
    assert "A" in e.states["국내형"].portfolio.positions


def test_intraday_forced_sell_survives_when_disabled():
    e = _with_position(signal_sell=False, intraday=True)
    _intraday(e, _snap(("R18",), 5))
    sells = [t for t in e.states["국내형"].portfolio.trades if t.side == Side.SELL]
    assert len(sells) == 1 and sells[0].trigger_rule == "R18"
    assert "A" not in e.states["국내형"].portfolio.positions


# ── 매수는 영향받지 않는다 ───────────────────────────────────────────────
def test_buys_unaffected_when_disabled():
    e = _engine(signal_sell=False)
    e.start(D1, fx_rate=1300.0)
    e.evaluate_close(D1, Market.KR, {"A": SymbolSnapshot(
        "A", Market.KR, ("G1", "G4", "G7"), (), 100.0, 0.0, 1000.0,
        green_score=18, red_score=0, buy_gate=True)})
    assert len(e.states["국내형"].pending_buys) == 1
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" in e.states["국내형"].portfolio.positions
