"""장중 회전 억제 브레이크 — intraday_buy_enabled / intraday_max_buys_per_day.

배경: 장중 경로를 켜면 국내형이 −17.6~−18.0%p 나빠지는데, 비용은 3.3%뿐이고 매수가는
오히려 개선된다. 악화의 거의 전부가 **회전 증가**에서 온다.
docs/experiments/kr-intraday-degradation-2026-09-03.md
"""
from datetime import date, datetime
from dataclasses import replace

import pytest

from simcore.config import Config
from simcore.engine import Engine, CharacterSpec
from simcore.models import Currency, DecisionType, Market, Side, SymbolSnapshot

D1, D2 = date(2025, 1, 6), date(2025, 1, 7)
KR_ONLY = (CharacterSpec("국내형", (Market.KR,), Currency.KRW),)
NOW = datetime(2025, 1, 7, 10, 0)


def _engine(**rules) -> Engine:
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True, **rules))
    e = Engine(cfg, characters=KR_ONLY)
    e.start(D1, fx_rate=1300.0)
    return e


def _snap(sym: str, price: float = 100.0) -> SymbolSnapshot:
    return SymbolSnapshot(sym, Market.KR, ("G1", "G4", "G7"), (), price, 0.0, 1e6,
                          green_score=28, red_score=0, buy_gate=True)


def _intraday(e: Engine, snaps: dict, now: datetime = NOW):
    eq = {"국내형": 100_000_000.0}
    e.evaluate_intraday(D2, Market.KR, snaps, {}, 1300.0, now,
                        day_equity=eq, cur_equity=eq)


def _positions(e: Engine) -> dict:
    return e.states["국내형"].portfolio.positions


def _blocked(e: Engine, sym: str) -> str:
    for c in e.last_candidates.get("국내형", []):
        if c.symbol == sym:
            return c.block_reason
    return ""


# ── 기본값은 기존 동작 ────────────────────────────────────────────────────
def test_defaults_keep_intraday_buying():
    r = Config().rules
    assert r.intraday_buy_enabled is True
    assert r.intraday_max_buys_per_day == 0        # 0 = 무제한


def test_default_config_still_buys_intraday():
    e = _engine()
    _intraday(e, {"A": _snap("A")})
    assert "A" in _positions(e)


# ── 장중 매수 금지 ────────────────────────────────────────────────────────
def test_buy_disabled_blocks_all_intraday_buys():
    e = _engine(intraday_buy_enabled=False)
    _intraday(e, {"A": _snap("A"), "B": _snap("B")})
    assert _positions(e) == {}
    assert _blocked(e, "A") == "장중매수OFF"


def test_buy_disabled_still_allows_intraday_sells():
    """매도·손절은 장중에 그대로 살아 있어야 한다 — 비대칭 구성의 핵심."""
    e = _engine(intraday_buy_enabled=False)
    # 마감 경로로 포지션을 연다(장중 매수는 막혀 있으므로)
    e.evaluate_close(D1, Market.KR, {"A": _snap("A")})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" in _positions(e)
    red = SymbolSnapshot("A", Market.KR, (), ("R1", "R13", "R2"), 95.0, -0.05, 1e6,
                         green_score=0, red_score=14, buy_gate=False)
    _intraday(e, {"A": red})
    sells = [t for t in e.states["국내형"].portfolio.trades if t.side == Side.SELL]
    assert len(sells) == 1
    assert sells[0].decision_type == DecisionType.INTRADAY_SELL


def test_buy_disabled_does_not_touch_close_path_buying():
    """마감 경로 매수는 이 스위치와 무관하다."""
    e = _engine(intraday_buy_enabled=False)
    e.evaluate_close(D1, Market.KR, {"A": _snap("A")})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" in _positions(e)


# ── 하루 매수 상한 ────────────────────────────────────────────────────────
def test_daily_cap_limits_total_intraday_buys():
    e = _engine(intraday_max_buys_per_day=2)
    _intraday(e, {s: _snap(s) for s in ("A", "B", "C", "D")})
    assert len(_positions(e)) == 2


def test_daily_cap_counts_across_symbols_not_per_symbol():
    """종목별 캡(intraday_max_buys_per_symbol)과 달리 전 종목 합산이다."""
    e = _engine(intraday_max_buys_per_day=1)
    _intraday(e, {"A": _snap("A")})
    assert len(_positions(e)) == 1
    _intraday(e, {"B": _snap("B")}, now=datetime(2025, 1, 7, 11, 0))
    assert len(_positions(e)) == 1, "다른 종목인데 하루 상한이 안 걸렸다"
    assert _blocked(e, "B") == "일일매수상한"


def test_daily_cap_resets_next_day():
    e = _engine(intraday_max_buys_per_day=1)
    _intraday(e, {"A": _snap("A")})
    assert len(_positions(e)) == 1
    # 다음 날 — _intraday_roll_day 가 카운터를 리셋한다
    d3 = date(2025, 1, 8)
    eq = {"국내형": 100_000_000.0}
    e.evaluate_intraday(d3, Market.KR, {"B": _snap("B")}, {}, 1300.0,
                        datetime(2025, 1, 8, 10, 0), day_equity=eq, cur_equity=eq)
    assert "B" in _positions(e), "다음 날인데 상한이 이월됐다"


def test_zero_means_unlimited():
    e = _engine(intraday_max_buys_per_day=0)
    _intraday(e, {s: _snap(s) for s in ("A", "B", "C")})
    assert len(_positions(e)) == 3


def test_daily_cap_does_not_block_sells():
    e = _engine(intraday_max_buys_per_day=1)
    e.evaluate_close(D1, Market.KR, {"A": _snap("A")})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    red = SymbolSnapshot("A", Market.KR, (), ("R1", "R13", "R2"), 95.0, -0.05, 1e6,
                         green_score=0, red_score=14, buy_gate=False)
    _intraday(e, {"A": red})
    assert "A" not in _positions(e)


# ── 두 브레이크의 우선순위(관측용 사유 문자열) ────────────────────────────
def test_buy_off_reported_before_daily_cap():
    e = _engine(intraday_buy_enabled=False, intraday_max_buys_per_day=1)
    _intraday(e, {"A": _snap("A")})
    assert _blocked(e, "A") == "장중매수OFF"
