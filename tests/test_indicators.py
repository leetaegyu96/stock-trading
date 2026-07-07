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
