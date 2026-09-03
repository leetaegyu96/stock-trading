"""run_replay 의 장중 경로 주입 (IntradayReplayOptions).

핵심 계약:
1. `intraday_enabled=False`(기본)면 기존 결과와 **완전히 동일**해야 한다.
2. 켜면 `Engine.evaluate_intraday` 가 실제로 호출되고 INTRADAY_* 거래가 나온다.
3. 일봉에는 경로 정보가 없으므로 결과는 `order` 양방향의 폭으로 읽는다.
"""
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

from simcore.config import Config
from simcore.models import DecisionType
from simcore.replay import DataBundle, IntradayReplayOptions, run_replay


def _bars(n=110, start="2025-01-01", trend=0.6, rng=0.02, vol=1e6):
    """완만한 상승 + 일중 변동폭이 있는 일봉 — 매수 게이트가 열리고 손절도 가능한 형태."""
    idx = pd.bdate_range(start, periods=n)
    base = pd.Series([100 + i * trend for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame({
        "open": base,
        "high": base * (1 + rng),
        "low": base * (1 - rng),
        "close": base * (1 + rng / 2),
        "volume": [vol] * n,
    }, index=idx)


@pytest.fixture
def bundle():
    idx = _bars().index
    return DataBundle(kr={"005930": _bars(), "000660": _bars(trend=0.4, rng=0.03)},
                      us={}, fx=pd.Series(1300.0, index=idx))


# 지표 워밍업(일목 78봉) 뒤 마지막 15거래일만 리플레이 — 계약 검증에 충분하고,
# 슬라이스마다 종목별 지표를 재계산하므로 구간을 넓히면 스위트가 급격히 느려진다.
_WINDOW = 15


def _run(bundle, cfg, **kw):
    idx = bundle.kr["005930"].index
    return run_replay(cfg, bundle, idx[-_WINDOW].date(), idx[-1].date(), **kw)


def _frame(res):
    """비교용 정규화 — 거래 목록과 자산곡선."""
    t = res.trades.reset_index(drop=True)
    return t, res.equity.round(6)


# ── 1. 기본값은 기존 동작 불변 ───────────────────────────────────────────
def test_disabled_by_default_matches_previous_behaviour(bundle):
    base = _run(bundle, Config())
    # 옵션을 넘겨도 intraday_enabled=False 면 무시된다
    with_opts = _run(bundle, Config(), intraday=IntradayReplayOptions(slices=6))
    tb, eb = _frame(base)
    tw, ew = _frame(with_opts)
    pd.testing.assert_frame_equal(tb, tw)
    pd.testing.assert_frame_equal(eb, ew)
    assert DecisionType.INTRADAY_SELL.value not in set(tb["decision_type"])
    assert DecisionType.INTRADAY_BUY.value not in set(tb["decision_type"])


def test_zero_slices_is_a_noop(bundle):
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    off = _run(bundle, Config())
    zero = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=0))
    pd.testing.assert_frame_equal(_frame(off)[0], _frame(zero)[0])


# ── 2. 켜면 장중 경로가 실제로 돈다 ──────────────────────────────────────
def test_enabled_produces_intraday_decisions(bundle):
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    res = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=4))
    kinds = set(res.trades["decision_type"])
    assert DecisionType.INTRADAY_BUY.value in kinds, (
        "장중 경로가 켜졌는데 INTRADAY_BUY 가 하나도 없다 — evaluate_intraday 미호출 의심")


def test_enabled_changes_the_outcome(bundle):
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    off = _run(bundle, Config())
    on = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=4))
    assert len(on.trades) != len(off.trades) or not on.equity.equals(off.equity)


def test_more_slices_means_more_evaluations(bundle):
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    few = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=2))
    many = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=8))
    assert len(many.trades) >= len(few.trades)


# ── 3. 경로 가정의 폭 ────────────────────────────────────────────────────
def test_path_order_is_an_assumption_not_a_fact(bundle):
    """두 경로 가정이 서로 다른 결과를 낸다 — 한쪽 값만 인용하면 안 된다는 근거."""
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    lo = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=6, order="low_first"))
    hi = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=6, order="high_first"))
    assert not lo.equity.equals(hi.equity)


def test_deterministic_for_same_options(bundle):
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    o = IntradayReplayOptions(slices=5, order="low_first")
    pd.testing.assert_frame_equal(_frame(_run(bundle, cfg, intraday=o))[1],
                                  _frame(_run(bundle, cfg, intraday=o))[1])


# ── 4. 규칙 토글이 장중 경로에도 걸린다 ──────────────────────────────────
def test_signal_sell_off_suppresses_intraday_score_sells(bundle):
    """v1.16.0 의 signal_sell_enabled=False 가 장중 경로에서도 유효한지 — 이제 검증 가능."""
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True,
                               signal_sell_enabled=False))
    res = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=6))
    assert DecisionType.INTRADAY_SELL.value not in set(res.trades["decision_type"])


def test_volume_scale_signals_never_reach_intraday_trades(bundle):
    """v1.16.1 — 잠정봉에서 G5/G23/R5/R24 는 거래 사유에 실리지 않는다."""
    from simcore import signals as sigmod
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    res = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=6))
    intraday = res.trades[res.trades["decision_type"].isin(
        [DecisionType.INTRADAY_BUY.value, DecisionType.INTRADAY_SELL.value])]
    assert not intraday.empty, "장중 거래가 없어 이 검증이 공회전한다"
    for fired in intraday["fired"]:
        codes = set(str(fired).split(";")) - {""}
        assert not (codes & sigmod.VOLUME_SCALE_DEPENDENT)


# ── 5. 회계 불변식 ───────────────────────────────────────────────────────
def test_no_negative_cash_and_positions_consistent(bundle):
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    res = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=6))
    for name, cash in res.cash_by_char.items():
        for cur, amt in cash.items():
            assert amt >= -1e-6, f"{name} {cur} 현금 음수 {amt}"
    for name, poss in res.positions_by_char.items():
        for p in poss:
            assert p["quantity"] > 0
    assert (res.equity > 0).all().all()


def test_max_positions_respected_intraday(bundle):
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True, max_positions=1))
    res = _run(bundle, cfg, intraday=IntradayReplayOptions(slices=6))
    for poss in res.positions_by_char.values():
        assert len(poss) <= 1


# ── 6. tick_only — 라이브 5분 손익절 틱 모사 ─────────────────────────────
def test_tick_only_runs_stop_checks_per_slice(bundle, monkeypatch):
    """tick_only 는 intraday_enabled 와 무관하게 슬라이스마다 check_stops 를 돌린다.

    라이브 스케줄러의 `tick_{market}` 잡이 매매 토글과 무관하게 5분마다 돌기 때문이다.
    (실제 청산 결과가 달라지는지는 엔진 단위 테스트에서 검증 —
    tests/test_engine_trailing_ratchet.py)
    """
    from simcore.engine import Engine
    calls = {"n": 0}
    orig = Engine.check_stops

    def spy(self, *a, **kw):
        calls["n"] += 1
        return orig(self, *a, **kw)

    monkeypatch.setattr(Engine, "check_stops", spy)
    _run(bundle, Config())
    daily_only = calls["n"]
    calls["n"] = 0
    _run(bundle, Config(), intraday=IntradayReplayOptions(slices=6, tick_only=True))
    with_ticks = calls["n"]
    assert with_ticks > daily_only, (
        f"tick_only 가 무시됐다 — check_stops 호출이 {daily_only} → {with_ticks}")


def test_tick_only_makes_no_intraday_trading_decisions(bundle):
    """손익절만 — 장중 매수/매도 판정은 일어나지 않는다."""
    res = _run(bundle, Config(), intraday=IntradayReplayOptions(slices=6, tick_only=True))
    kinds = set(res.trades["decision_type"])
    assert DecisionType.INTRADAY_BUY.value not in kinds
    assert DecisionType.INTRADAY_SELL.value not in kinds


def test_tick_only_is_deterministic(bundle):
    o = IntradayReplayOptions(slices=6, tick_only=True, order="low_first")
    pd.testing.assert_frame_equal(_frame(_run(bundle, Config(), intraday=o))[1],
                                  _frame(_run(bundle, Config(), intraday=o))[1])
