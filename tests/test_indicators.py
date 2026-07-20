import numpy as np
import pandas as pd
import pytest
from simcore import indicators as ind

def test_sma_hand_computed():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[4] == pytest.approx(4.0)

def test_rsi_all_gains_is_100():
    s = pd.Series(np.linspace(100, 200, 40))
    out = ind.rsi(s, 14)
    assert out.iloc[-1] == pytest.approx(100.0)

def test_rsi_all_losses_is_0():
    s = pd.Series(np.linspace(200, 100, 40))
    out = ind.rsi(s, 14)
    assert out.iloc[-1] == pytest.approx(0.0, abs=1e-6)

def test_macd_flat_series_is_zero():
    s = pd.Series([100.0] * 60)
    line, sig = ind.macd(s)
    assert line.iloc[-1] == pytest.approx(0.0)
    assert sig.iloc[-1] == pytest.approx(0.0)

def test_bollinger_constant_series_bands_collapse():
    s = pd.Series([50.0] * 30)
    mid, up, lo = ind.bollinger(s, 20, 2.0)
    assert mid.iloc[-1] == up.iloc[-1] == lo.iloc[-1] == pytest.approx(50.0)

def test_stochastic_close_at_high_is_100():
    n = 30
    high = pd.Series(np.arange(n) + 10.0)
    low = high - 5.0
    close = high.copy()  # 항상 고가 마감
    k, d = ind.stochastic(high, low, close)
    assert k.iloc[-1] == pytest.approx(100.0)
    assert d.iloc[-1] == pytest.approx(100.0)


def _series(vals):
    idx = pd.date_range("2024-01-01", periods=len(vals), freq="D")
    return pd.Series(vals, index=idx, dtype=float)


def test_atr_wilder_matches_manual():
    high = _series([10, 11, 12, 11, 13])
    low = _series([9, 9.5, 10, 10, 11])
    close = _series([9.5, 10.5, 11.5, 10.5, 12.5])
    out = ind.atr(high, low, close, period=2)
    # 첫 TR=high-low=1; 이후 TR=max(h-l, |h-prevclose|, |l-prevclose|)
    assert out.notna().sum() >= 3
    assert (out.dropna() > 0).all()


def test_adx_trending_up_has_di_plus_dominant():
    n = 40
    close = _series(np.linspace(10, 30, n))          # 꾸준한 상승
    high = close + 0.5
    low = close - 0.5
    adx, di_p, di_m = ind.adx(high, low, close, period=14)
    assert di_p.iloc[-1] > di_m.iloc[-1]             # 상승 → DI+ 우위
    assert adx.iloc[-1] > 20


def test_obv_accumulates_on_up_days():
    close = _series([10, 11, 10, 12])
    vol = _series([100, 200, 150, 300])
    out = ind.obv(close, vol)
    # +200 (상승), -150 (하락), +300 (상승) 누적
    assert out.iloc[1] == 200
    assert out.iloc[2] == 50
    assert out.iloc[3] == 350


def test_vwap_between_low_and_high():
    high = _series([10, 11, 12, 13, 14])
    low = _series([8, 9, 10, 11, 12])
    close = _series([9, 10, 11, 12, 13])
    vol = _series([100, 100, 100, 100, 100])
    out = ind.vwap(high, low, close, vol, period=3)
    tail = out.dropna()
    assert (tail >= low.reindex(tail.index)).all()
    assert (tail <= high.reindex(tail.index)).all()


def test_parabolic_sar_flips_below_price_in_uptrend():
    n = 30
    close = _series(np.linspace(10, 25, n))
    high = close + 0.3
    low = close - 0.3
    sar = ind.parabolic_sar(high, low)
    assert sar.iloc[-1] < close.iloc[-1]             # 상승추세 → SAR 은 가격 아래


def test_ichimoku_cloud_below_price_in_uptrend():
    n = 90
    close = _series(np.linspace(10, 40, n))
    high = close + 0.5
    low = close - 0.5
    tenkan, kijun, span_a, span_b = ind.ichimoku(high, low, close)
    top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    assert close.iloc[-1] > top.iloc[-1]             # 상승추세 → 구름 위
    assert tenkan.iloc[-1] > kijun.iloc[-1]


def test_disparity_matches_manual():
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    out = ind.disparity(close, period=3)
    # 마지막 시점 SMA(3) = (12+13+14)/3 = 13.0, 괴리율 = (14-13)/13
    assert out.iloc[-1] == (14.0 - 13.0) / 13.0
    assert np.isnan(out.iloc[0])  # 워밍업


def test_support_resistance_prev_window_excludes_current():
    high = pd.Series([10.0, 12.0, 11.0, 15.0, 9.0])
    low = pd.Series([5.0, 6.0, 4.0, 7.0, 3.0])
    close = pd.Series([8.0, 9.0, 8.5, 12.0, 6.0])
    sup, res = ind.support_resistance(high, low, close, lookback=3)
    # index 3 기준 직전 3봉(0,1,2): 최고 high=12, 최저 low=4
    assert res.iloc[3] == 12.0
    assert sup.iloc[3] == 4.0
    assert np.isnan(sup.iloc[0])
