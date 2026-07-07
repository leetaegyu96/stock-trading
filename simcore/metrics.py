"""성과 지표. 입출금 왜곡을 제거한 시간가중수익률(TWR)이 기본 수익률이다."""
from __future__ import annotations
import pandas as pd


def time_weighted_return(equity: pd.Series, flows: pd.Series | None = None) -> float:
    eq = equity.dropna()
    if len(eq) < 2:
        return 0.0
    if flows is None:
        f = pd.Series(0.0, index=eq.index)
    else:
        f = flows.reindex(eq.index).fillna(0.0)
    twr = 1.0
    prev = eq.iloc[0]
    for d in eq.index[1:]:
        base = prev + f.loc[d]  # 입출금은 당일 장 시작 전 반영
        if base > 0:
            twr *= eq.loc[d] / base
        prev = eq.loc[d]
    return twr - 1.0


def max_drawdown(equity: pd.Series) -> float:
    eq = equity.dropna()
    if len(eq) < 2:
        return 0.0
    dd = eq / eq.cummax() - 1.0
    return float(dd.min())


def simple_pnl_krw(equity: pd.Series, flows: pd.Series | None = None) -> float:
    eq = equity.dropna()
    if len(eq) < 2:
        return 0.0
    net_flows = 0.0
    if flows is not None:
        net_flows = float(flows.reindex(eq.index[1:]).fillna(0.0).sum())
    return float(eq.iloc[-1] - eq.iloc[0] - net_flows)
