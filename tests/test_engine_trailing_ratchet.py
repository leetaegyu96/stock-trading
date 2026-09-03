"""장중 틱이 트레일링 잠금선을 같은 날 올리고, 같은 날 되돌림이 그 선을 때리는 문제.

라이브 스케줄러는 `tick_{market}` 잡을 `intraday_enabled` 와 **무관하게** 등록해
5분마다 `on_tick`→`check_stops` 를 돌린다(o=h=l=c=현재가 유사봉). 그래서 잠금선이
장중에 계단식으로 올라가고, 같은 날 눌림이 그 올라간 선을 때려 청산된다.

반면 `run_replay` 는 하루 1회 일봉으로만 판정한다 — 저가를 **갱신 전** 잠금선과 비교한 뒤
peak 를 올리므로, 올라간 선은 다음 날부터 적용된다. 즉 **리플레이가 라이브보다 관대하다.**
이 테스트는 그 차이를 고정한다.
"""
from datetime import date

import pytest

from simcore.config import Config
from simcore.engine import Engine, CharacterSpec
from simcore.models import Currency, DailyBar, Market, SymbolSnapshot, TradeReason

D1, D2, D3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
KR = (CharacterSpec("국내형", (Market.KR,), Currency.KRW),)
FX = 1300.0


def _engine_holding_at(avg: float = 100.0) -> Engine:
    e = Engine(Config(), characters=KR)
    e.start(D1, fx_rate=FX)
    snap = SymbolSnapshot("A", Market.KR, ("G1", "G4", "G7"), (), avg, 0.0, 1e6,
                          green_score=18, red_score=0, buy_gate=True)
    e.evaluate_close(D1, Market.KR, {"A": snap})
    e.fill_open(D2, Market.KR, {"A": avg}, fx_rate=FX)
    return e


def _pos(e: Engine):
    return e.states["국내형"].portfolio.positions.get("A")


def _bar(low: float, high: float, close: float | None = None, d=D3) -> DailyBar:
    c = close if close is not None else high
    return DailyBar("A", d, high, high, low, c, 1e6)


def test_prior_runup_locks_stop_at_plus20():
    """peak +30% → 티어 (0.30, 0.20) → 평단 대비 +20% 잠금."""
    e = _engine_holding_at(100.0)
    e.check_stops(D2, Market.KR, {"A": _bar(low=99.0, high=130.0, d=D2)}, FX)
    p = _pos(e)
    assert p is not None and p.peak_price == pytest.approx(130.0)
    assert p.locked_stop_pct == pytest.approx(0.20)      # stop_px = 120


def test_daily_single_check_misses_the_same_day_ratcheted_stop():
    """하루 1회 판정(리플레이): 저가를 '갱신 전' 잠금선(120)과 비교 → 살아남는다."""
    e = _engine_holding_at(100.0)
    e.check_stops(D2, Market.KR, {"A": _bar(low=99.0, high=130.0, d=D2)}, FX)
    # 당일 고가 145(잠금선을 134.85로 올릴 값) + 저가 131
    e.check_stops(D3, Market.KR, {"A": _bar(low=131.0, high=145.0, close=140.0)}, FX)
    p = _pos(e)
    assert p is not None, "하루 1회 판정에서는 청산되지 않아야 한다"
    # 다만 잠금선은 올라간다 — 다음 날부터 적용
    assert p.locked_stop_pct == pytest.approx(145.0 * 0.93 / 100.0 - 1.0)


def test_intraday_ticks_ratchet_then_stop_out_the_same_day():
    """장중 틱(라이브): 고가를 먼저 밟아 잠금선이 134.85로 올라간 뒤, 같은 날 저가 131이
    그 선을 때려 **당일 트레일링 청산**된다 — 하루 1회 판정과 결과가 갈린다."""
    e = _engine_holding_at(100.0)
    e.check_stops(D2, Market.KR, {"A": _bar(low=99.0, high=130.0, d=D2)}, FX)
    # 틱 1: 시가~고가 구간 (저가 128 > 잠금선 120 → 미발동, peak 145 로 래칫)
    e.check_stops(D3, Market.KR, {"A": _bar(low=128.0, high=145.0, close=145.0)}, FX)
    p = _pos(e)
    assert p is not None and p.locked_stop_pct == pytest.approx(145.0 * 0.93 / 100.0 - 1.0)
    # 틱 2: 고가~저가 되돌림 구간 (저가 131 ≤ 올라간 잠금선 134.85 → 발동)
    e.check_stops(D3, Market.KR, {"A": _bar(low=131.0, high=140.0, close=131.0)}, FX)
    assert _pos(e) is None, "올라간 잠금선을 같은 날 되돌림이 때렸는데 청산되지 않았다"
    t = e.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.TRAILING_STOP
    assert t.trigger_rule == "R10"
    assert t.price == pytest.approx(134.85)              # 잠금선에서 체결


def test_more_ticks_never_ratchet_below_fewer_ticks():
    """틱을 잘게 쪼개도 잠금선은 단조 증가만 한다(래칫) — 되돌아 내려가지 않는다."""
    e = _engine_holding_at(100.0)
    locks = []
    for hi in (115.0, 125.0, 118.0, 135.0):
        e.check_stops(D3, Market.KR, {"A": _bar(low=hi - 1.0, high=hi, close=hi)}, FX)
        p = _pos(e)
        if p is None:
            break
        locks.append(p.locked_stop_pct)
    assert locks == sorted(locks), f"잠금선이 내려갔다: {locks}"


# ── trailing_intraday_update=False — 장중 래칫만 끈다 ─────────────────────
def _engine_no_intraday_ratchet(avg: float = 100.0) -> Engine:
    from dataclasses import replace as dc_replace
    cfg = Config(rules=dc_replace(Config().rules, trailing_intraday_update=False))
    e = Engine(cfg, characters=KR)
    e.start(D1, fx_rate=FX)
    snap = SymbolSnapshot("A", Market.KR, ("G1", "G4", "G7"), (), avg, 0.0, 1e6,
                          green_score=18, red_score=0, buy_gate=True)
    e.evaluate_close(D1, Market.KR, {"A": snap})
    e.fill_open(D2, Market.KR, {"A": avg}, fx_rate=FX)
    return e


def test_intraday_tick_does_not_ratchet_when_disabled():
    e = _engine_no_intraday_ratchet(100.0)
    before = _pos(e).locked_stop_pct
    e.check_stops(D2, Market.KR, {"A": _bar(low=99.0, high=130.0, d=D2)}, FX,
                  update_trailing=False)
    assert _pos(e).locked_stop_pct == pytest.approx(before), "장중 틱이 잠금선을 올렸다"
    assert _pos(e).peak_price == pytest.approx(100.0)


def test_same_day_pullback_survives_when_intraday_ratchet_off():
    """래칫을 끄면 앞선 테스트의 '당일 트레일링 청산'이 일어나지 않는다."""
    e = _engine_no_intraday_ratchet(100.0)
    # 마감 판정으로 잠금선을 120 까지 올려둔다(래칫은 마감에서만)
    e.check_stops(D2, Market.KR, {"A": _bar(low=99.0, high=130.0, d=D2)}, FX,
                  update_trailing=True)
    assert _pos(e).locked_stop_pct == pytest.approx(0.20)
    # 장중 틱 1: 고가 145 — 래칫 꺼짐이라 잠금선 그대로 120
    e.check_stops(D3, Market.KR, {"A": _bar(low=128.0, high=145.0, close=145.0)}, FX,
                  update_trailing=False)
    assert _pos(e).locked_stop_pct == pytest.approx(0.20)
    # 장중 틱 2: 저가 131 > 120 → 생존 (래칫 켜졌을 때는 청산됐던 자리)
    e.check_stops(D3, Market.KR, {"A": _bar(low=131.0, high=140.0, close=131.0)}, FX,
                  update_trailing=False)
    assert _pos(e) is not None, "래칫을 껐는데도 당일 청산됐다"


def test_base_stop_loss_still_fires_when_ratchet_off():
    """래칫을 꺼도 손절 자체는 장중에 그대로 작동해야 한다 — 리스크 관리는 유지."""
    e = _engine_no_intraday_ratchet(100.0)
    e.check_stops(D3, Market.KR, {"A": _bar(low=90.0, high=101.0, close=90.0)}, FX,
                  update_trailing=False)
    assert _pos(e) is None
    t = e.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.STOP_LOSS
    assert t.price == pytest.approx(93.0)
