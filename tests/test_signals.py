import numpy as np
import pandas as pd
from simcore.config import SignalParams
from simcore.signals import evaluate_frame, fired_at, min_history, GREEN_COLS, RED_COLS

P = SignalParams()

def make_df(closes, volumes=None, opens=None, highs=None, lows=None):
    n = len(closes)
    closes = pd.Series(closes, dtype=float)
    idx = pd.bdate_range("2024-01-02", periods=n)
    df = pd.DataFrame({
        "open": opens if opens is not None else closes.values,
        "high": highs if highs is not None else closes.values * 1.01,
        "low": lows if lows is not None else closes.values * 0.99,
        "close": closes.values,
        "volume": volumes if volumes is not None else np.full(n, 1000.0),
    }, index=idx)
    return df

def test_insufficient_history_all_false():
    df = make_df(np.linspace(100, 110, 30))  # 61봉 미만
    frame = evaluate_frame(df, P)
    assert not frame.iloc[-1].any()

def test_uptrend_fires_g1_g2_g4_and_not_r1_r2():
    df = make_df(np.linspace(100, 160, 100))  # 꾸준한 상승
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert {"G1", "G2", "G4"} <= set(green)
    assert "R1" not in red and "R2" not in red

def test_downtrend_fires_r1_r2_r4():
    df = make_df(np.linspace(160, 100, 100))
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert {"R1", "R2", "R4"} <= set(red)

def test_g5_volume_surge_bullish_candle():
    closes = np.full(100, 100.0)
    volumes = np.full(100, 1000.0)
    volumes[-1] = 2000.0                     # 평균의 2배
    opens = closes.copy(); opens[-1] = 99.0  # 양봉 (종가 100 > 시가 99)
    df = make_df(closes, volumes=volumes, opens=opens)
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert "G5" in green
    assert "R5" not in red

def test_g7_breakout_over_60d_high():
    closes = np.concatenate([np.full(80, 100.0), [105.0]])  # 마지막 날 신고가
    df = make_df(closes)
    green, _ = fired_at(evaluate_frame(df, P), df.index[-1])
    assert "G7" in green

def test_stub_columns_always_false():
    df = make_df(np.linspace(100, 160, 100))
    frame = evaluate_frame(df, P)
    for col in ["G8", "G9", "R8", "R9"]:
        assert col in frame.columns
        assert not frame[col].any()

def test_min_history_default_is_61():
    assert min_history(P) == 61
