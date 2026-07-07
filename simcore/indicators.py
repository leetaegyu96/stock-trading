"""기술 지표. 모든 함수는 pd.Series 를 받아 인덱스를 보존한 Series 를 반환한다."""
from __future__ import annotations
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    out = 100 - 100 / (1 + avg_gain / avg_loss)
    # 손실이 전혀 없으면 0/0 → NaN 이 되므로 100 으로 보정 (워밍업 NaN 은 유지)
    no_loss = (avg_loss == 0) & avg_gain.notna()
    out[no_loss] = 100.0
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> tuple[pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig


def bollinger(close: pd.Series, period: int = 20,
              num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return mid, mid + num_std * std, mid - num_std * std


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, k_smooth: int = 3,
               d_period: int = 3) -> tuple[pd.Series, pd.Series]:
    ll = low.rolling(k_period).min()
    hh = high.rolling(k_period).max()
    raw_k = 100 * (close - ll) / (hh - ll)
    k = raw_k.rolling(k_smooth).mean()
    d = k.rolling(d_period).mean()
    return k, d
