"""청/적신호 판정. 계산식은 docs/trading-rules.md 2·3장과 1:1 대응.
G8/G9/R8/R9(감정·수급)는 스텁 — 항상 False 컬럼으로 존재하며 4단계에서 대체된다.
R7(손절)/R10(익절)은 포지션 평단가에 의존하므로 engine 이 판정한다."""
from __future__ import annotations
import pandas as pd

from simcore.config import SignalParams
from simcore import indicators as ind

GREEN_COLS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10"]
RED_COLS = ["R1", "R2", "R3", "R4", "R5", "R6", "R8", "R9"]


def min_history(p: SignalParams) -> int:
    return max(
        p.breakout_lookback + 1,
        p.sma_slow + 1,
        p.macd_slow + p.macd_signal,
        p.bb_period + 1,
        p.rsi_period + 2,
        p.stoch_k + p.stoch_k_smooth + p.stoch_d,
    )


def evaluate_frame(df: pd.DataFrame, p: SignalParams) -> pd.DataFrame:
    close, open_, high, low, vol = df["close"], df["open"], df["high"], df["low"], df["volume"]
    sma_f = ind.sma(close, p.sma_fast)
    sma_s = ind.sma(close, p.sma_slow)
    rsi = ind.rsi(close, p.rsi_period)
    macd_line, macd_sig = ind.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
    bb_mid, bb_up, bb_lo = ind.bollinger(close, p.bb_period, p.bb_std)
    k, d = ind.stochastic(high, low, close, p.stoch_k, p.stoch_k_smooth, p.stoch_d)
    vol_avg = ind.sma(vol, p.volume_avg_period)

    surge = vol >= vol_avg * p.volume_surge_ratio
    prev_high = close.rolling(p.breakout_lookback).max().shift(1)  # 당일 제외 직전 N일 최고 종가

    out = pd.DataFrame(index=df.index)
    out["G1"] = sma_f > sma_s
    out["G2"] = close > sma_s
    out["G3"] = (rsi.shift(1) <= p.rsi_buy_cross) & (rsi > p.rsi_buy_cross)
    out["G4"] = macd_line > macd_sig
    out["G5"] = surge & (close > open_)
    out["G6"] = (close.shift(1) <= bb_mid.shift(1)) & (close > bb_mid)
    out["G7"] = close > prev_high
    out["G8"] = False   # 스텁: 긍정 심리 급증
    out["G9"] = False   # 스텁: 외인·기관 순매수
    out["G10"] = (k.shift(1) < p.stoch_oversold) & (k.shift(1) <= d.shift(1)) & (k > d)

    out["R1"] = sma_f < sma_s
    out["R2"] = close < sma_s
    out["R3"] = (rsi.shift(1) >= p.rsi_overbought) & (rsi < rsi.shift(1))
    out["R4"] = macd_line < macd_sig
    out["R5"] = surge & (close < open_)
    out["R6"] = close < bb_lo
    out["R8"] = False   # 스텁: 부정 심리 급증
    out["R9"] = False   # 스텁: 외인·기관 순매도

    out = out.fillna(False).astype(bool)
    warmup = min_history(p) - 1
    if warmup > 0:
        out.iloc[:warmup] = False
    return out


def fired_at(frame: pd.DataFrame, d) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if d not in frame.index:
        return (), ()
    row = frame.loc[d]
    green = tuple(c for c in GREEN_COLS if bool(row[c]))
    red = tuple(c for c in RED_COLS if bool(row[c]))
    return green, red
