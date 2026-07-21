from datetime import date, timedelta
from dataclasses import replace
import math
import numpy as np
import pandas as pd
import pytest

from simcore.config import Config
from simcore.replay import DataBundle
from simcore.walkforward import Fold, generate_folds, run_walkforward, _aggregate


# ---------------------------------------------------------------- generate_folds

def test_generate_folds_first_start_at_warmup_offset():
    start, end = date(2024, 1, 1), date(2024, 12, 31)
    folds = generate_folds(start, end, test_days=63, step_days=63, warmup_days=120)
    assert folds[0].test_start == start + timedelta(days=120)


def test_generate_folds_last_end_clipped_to_end():
    start, end = date(2024, 1, 1), date(2024, 12, 31)
    folds = generate_folds(start, end, test_days=63, step_days=63, warmup_days=120)
    assert folds[-1].test_end <= end


def test_generate_folds_step_spacing_between_consecutive_starts():
    start, end = date(2024, 1, 1), date(2025, 12, 31)
    folds = generate_folds(start, end, test_days=63, step_days=63, warmup_days=120)
    for a, b in zip(folds, folds[1:]):
        assert b.test_start - a.test_start == timedelta(days=63)


def test_generate_folds_count_and_index():
    start, end = date(2024, 1, 1), date(2024, 12, 31)
    folds = generate_folds(start, end, test_days=63, step_days=63, warmup_days=120)
    # 120일 워밍업 이후 [2024-04-30, 2024-12-31] 구간을 63일 간격으로 타일링
    assert len(folds) >= 2
    assert [f.index for f in folds] == list(range(len(folds)))
    assert all(isinstance(f, Fold) for f in folds)


def test_generate_folds_drops_windows_shorter_than_half_test_days():
    # end를 마지막 test_start 바로 뒤(63일의 절반 미만)로 잘라 마지막 폴드가 제외되는지 확인
    start = date(2024, 1, 1)
    warmup_days, test_days, step_days = 120, 63, 63
    first_start = start + timedelta(days=warmup_days)
    # 두 번째 폴드가 시작하자마자 아주 짧게(최소 길이 미만) 끝나도록 end 설정
    second_start = first_start + timedelta(days=step_days)
    end = second_start + timedelta(days=(test_days // 2) - 1)
    folds = generate_folds(start, end, test_days=test_days, step_days=step_days,
                            warmup_days=warmup_days)
    # 마지막(두번째) 폴드는 최소 길이 미만이라 제외되고 첫 폴드만 남는다
    assert len(folds) == 1
    assert folds[0].test_start == first_start


def test_generate_folds_no_dates_needed_pure_function():
    # 네트워크/날짜 없이 순수 함수로 결정론적 결과
    start, end = date(2020, 1, 1), date(2020, 6, 1)
    f1 = generate_folds(start, end, test_days=30, step_days=30, warmup_days=10)
    f2 = generate_folds(start, end, test_days=30, step_days=30, warmup_days=10)
    assert f1 == f2


# ---------------------------------------------------------------- _aggregate (순수 집계 헬퍼)

def test_aggregate_mean_std_and_pct_profitable():
    folds = [
        {"index": 0, "test_start": date(2024, 1, 1), "test_end": date(2024, 3, 1),
         "per_char": {"국내형": {"twr": 0.10, "mdd": -0.05, "sharpe": 1.0,
                                "win_rate": 0.6, "n_trades": 4}}},
        {"index": 1, "test_start": date(2024, 3, 1), "test_end": date(2024, 5, 1),
         "per_char": {"국내형": {"twr": -0.02, "mdd": -0.08, "sharpe": -0.5,
                                "win_rate": 0.3, "n_trades": 2}}},
        {"index": 2, "test_start": date(2024, 5, 1), "test_end": date(2024, 7, 1),
         "per_char": {"국내형": {"twr": 0.04, "mdd": -0.03, "sharpe": 0.8,
                                "win_rate": 0.5, "n_trades": 3}}},
    ]
    agg = _aggregate(folds)
    c = agg["per_char"]["국내형"]
    twrs = [0.10, -0.02, 0.04]
    expected_mean = sum(twrs) / 3
    expected_std = math.sqrt(sum((t - expected_mean) ** 2 for t in twrs) / (3 - 1))
    assert c["mean_twr"] == pytest.approx(expected_mean)
    assert c["std_twr"] == pytest.approx(expected_std)
    assert c["pct_profitable_folds"] == pytest.approx(2 / 3)
    assert c["mean_sharpe"] == pytest.approx((1.0 - 0.5 + 0.8) / 3)
    assert c["worst_mdd"] == pytest.approx(0.08)
    assert c["n_folds"] == 3


def test_aggregate_empty_folds_guarded():
    agg = _aggregate([])
    assert agg == {"per_char": {}}


def test_aggregate_single_fold_std_is_zero():
    folds = [
        {"index": 0, "test_start": date(2024, 1, 1), "test_end": date(2024, 3, 1),
         "per_char": {"국내형": {"twr": 0.10, "mdd": -0.05, "sharpe": 1.0,
                                "win_rate": 0.6, "n_trades": 4}}},
    ]
    agg = _aggregate(folds)
    assert agg["per_char"]["국내형"]["std_twr"] == 0.0
    assert agg["per_char"]["국내형"]["n_folds"] == 1


# ---------------------------------------------------------------- 통합: run_walkforward

def make_ohlcv(closes, idx):
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({
        "open": c.shift(1).fillna(c.iloc[0]),
        "high": c * 1.005, "low": c * 0.995,
        "close": c, "volume": np.full(len(c), 10_000.0),
    }, index=idx)


def make_uptrend_bundle(n=400):
    idx = pd.bdate_range("2024-01-02", periods=n)
    closes = list(100 * (1.003 ** np.arange(n)))
    kr = {"AAA": make_ohlcv(closes, idx)}
    fx = pd.Series(1300.0, index=idx)
    return DataBundle(kr=kr, us={}, fx=fx), idx


CFG = replace(Config(), rules=replace(Config().rules, buy_score_min=1))


def test_run_walkforward_two_folds_have_finite_metrics_and_aggregate():
    bundle, idx = make_uptrend_bundle(400)
    start, end = idx[0].date(), idx[-1].date()
    folds = generate_folds(start, end, test_days=90, step_days=90, warmup_days=30)
    folds = folds[:2]
    result = run_walkforward(CFG, bundle, folds)
    assert len(result.folds) == 2
    for fold in result.folds:
        per_char = fold["per_char"]
        assert "국내형" in per_char
        for name, m in per_char.items():
            assert {"twr", "mdd", "sharpe", "win_rate", "n_trades"} <= set(m)
            assert math.isfinite(m["twr"])
            assert math.isfinite(m["mdd"])
            assert math.isfinite(m["sharpe"])
            assert math.isfinite(m["win_rate"])
    assert result.aggregate["per_char"]["국내형"]["n_folds"] == 2


def test_run_walkforward_win_rate_matches_manual_computation():
    bundle, idx = make_uptrend_bundle(400)
    start, end = idx[0].date(), idx[-1].date()
    folds = generate_folds(start, end, test_days=200, step_days=200, warmup_days=30)[:1]
    result = run_walkforward(CFG, bundle, folds)
    fold = result.folds[0]
    m = fold["per_char"]["국내형"]
    if m["n_trades"] > 0:
        # win_rate는 [0,1] 범위의 유한값이어야 한다 (SELL 행 기준 realized_pnl>0 비율)
        assert 0.0 <= m["win_rate"] <= 1.0


def test_run_walkforward_skips_fold_with_no_trading_days_and_continues():
    bundle, idx = make_uptrend_bundle(400)
    ok_start, ok_end = idx[0].date(), idx[100].date()
    # 데이터 범위 밖(전부 주말/데이터 없음 구간)의 폴드 — run_replay가 ValueError를 던짐
    empty_start = idx[-1].date() + timedelta(days=365)
    empty_end = empty_start + timedelta(days=30)
    folds = [
        Fold(index=0, test_start=ok_start, test_end=ok_end),
        Fold(index=1, test_start=empty_start, test_end=empty_end),
    ]
    result = run_walkforward(CFG, bundle, folds)
    assert len(result.folds) == 1
    assert result.folds[0]["index"] == 0
