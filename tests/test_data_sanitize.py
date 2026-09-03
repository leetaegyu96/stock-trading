"""깨진 일봉 정제 — sanitize_ohlcv.

pykrx 가 드물게 `open=high=low=0` 이고 close 만 있는 봉을 준다. 그대로 쓰면
`Engine.check_stops` 가 `low(0) <= stop_px` 로 그 종목 보유분을 전부 허위 손절시킨다.
"""
import pandas as pd
import pytest

from simcore.data import sanitize_ohlcv


def _df(rows):
    idx = pd.bdate_range("2025-01-01", periods=len(rows))
    return pd.DataFrame(rows, index=idx,
                        columns=["open", "high", "low", "close", "volume"])


def test_drops_zero_price_bars():
    df = _df([[100, 105, 98, 103, 1e6],
              [0, 0, 0, 295411, 0],          # pykrx 공백 봉
              [104, 108, 102, 107, 1e6]])
    out = sanitize_ohlcv(df)
    assert len(out) == 2
    assert (out[["open", "high", "low", "close"]] > 0).all().all()


def test_drops_nan_bars():
    df = _df([[100, 105, 98, 103, 1e6],
              [float("nan"), 105, 98, 103, 1e6]])
    assert len(sanitize_ohlcv(df)) == 1


def test_repairs_rounding_inconsistency():
    """close 가 high 보다 1 위인 반올림 오차는 버리지 않고 보정한다."""
    df = _df([[719589, 744064, 716652, 744065, 1e6]])
    out = sanitize_ohlcv(df)
    assert len(out) == 1
    assert out["high"].iloc[0] == 744065      # close 까지 포함해 확장
    assert out["low"].iloc[0] == 716652


def test_leaves_clean_bars_untouched():
    df = _df([[100, 105, 98, 103, 1e6], [104, 108, 102, 107, 2e6]])
    pd.testing.assert_frame_equal(sanitize_ohlcv(df), df)


def test_empty_frame_is_passthrough():
    df = _df([]).astype(float)
    assert sanitize_ohlcv(df).empty


def test_all_bad_yields_empty():
    assert sanitize_ohlcv(_df([[0, 0, 0, 100, 0]])).empty


def test_low_zero_bar_would_have_stopped_every_position():
    """정제 전에는 low=0 이 손절선 아래라 무조건 발동한다 — 이 버그의 형태를 고정."""
    from simcore.config import Config
    bad = _df([[0, 0, 0, 295411, 0]])
    stop_px = 100_000 * (1 + Config().rules.stop_loss_pct)
    assert bad["low"].iloc[0] <= stop_px          # 정제 전: 발동
    assert sanitize_ohlcv(bad).empty              # 정제 후: 봉 자체가 사라짐


def test_non_ohlcv_frame_is_untouched():
    """FX·지수 시리즈처럼 OHLC 컬럼이 없는 프레임은 그대로 통과한다(_cached 공용 경로)."""
    fx = pd.DataFrame({"Close": [1300.0, 1310.0]},
                      index=pd.bdate_range("2025-01-01", periods=2))
    pd.testing.assert_frame_equal(sanitize_ohlcv(fx), fx)


def test_partial_columns_are_untouched():
    df = pd.DataFrame({"open": [1.0], "close": [2.0]},
                      index=pd.bdate_range("2025-01-01", periods=1))
    pd.testing.assert_frame_equal(sanitize_ohlcv(df), df)
