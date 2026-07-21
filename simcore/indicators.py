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


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = _true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    di_plus = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_
    di_minus = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus)
    adx_ = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx_, di_plus, di_minus


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = close.diff().apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    return (direction * volume).cumsum()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series, period: int = 20) -> pd.Series:
    typical = (high + low + close) / 3.0
    pv = (typical * volume).rolling(period).sum()
    vv = volume.rolling(period).sum()
    return pv / vv


def parabolic_sar(high: pd.Series, low: pd.Series,
                  af_step: float = 0.02, af_max: float = 0.2) -> pd.Series:
    n = len(high)
    sar = [float("nan")] * n
    if n < 2:
        return pd.Series(sar, index=high.index)
    h = high.to_numpy(); l = low.to_numpy()
    up = True                      # 초기 추세: 상승 가정
    af = af_step
    ep = h[0]                      # extreme point
    sar_val = l[0]
    for i in range(1, n):
        prev = sar_val
        sar_val = prev + af * (ep - prev)
        if up:
            sar_val = min(sar_val, l[i - 1], l[max(i - 2, 0)])
            if l[i] < sar_val:     # 하락 반전
                up = False; sar_val = ep; ep = l[i]; af = af_step
            elif h[i] > ep:
                ep = h[i]; af = min(af + af_step, af_max)
        else:
            sar_val = max(sar_val, h[i - 1], h[max(i - 2, 0)])
            if h[i] > sar_val:     # 상승 반전
                up = True; sar_val = ep; ep = h[i]; af = af_step
            elif l[i] < ep:
                ep = l[i]; af = min(af + af_step, af_max)
        sar[i] = sar_val
    return pd.Series(sar, index=high.index)


def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
             tenkan: int = 9, kijun: int = 26,
             senkou_b: int = 52) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    def mid(period):
        return (high.rolling(period).max() + low.rolling(period).min()) / 2.0
    tenkan_line = mid(tenkan)
    kijun_line = mid(kijun)
    span_a = ((tenkan_line + kijun_line) / 2.0).shift(kijun)   # 현재 봉에 정렬
    span_b = mid(senkou_b).shift(kijun)
    return tenkan_line, kijun_line, span_a, span_b


def disparity(close: pd.Series, period: int) -> pd.Series:
    """가격괴리율 = (종가 − 이동평균) / 이동평균. 워밍업 구간 NaN."""
    ma = sma(close, period)
    return (close - ma) / ma


def support_resistance(high: pd.Series, low: pd.Series, close: pd.Series,
                       lookback: int) -> tuple[pd.Series, pd.Series]:
    """직전 lookback 구간(현재 봉 제외) 최저가=지지, 최고가=저항."""
    support = low.shift(1).rolling(lookback).min()
    resistance = high.shift(1).rolling(lookback).max()
    return support, resistance
