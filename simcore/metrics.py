"""성과 지표. 입출금 왜곡을 제거한 시간가중수익률(TWR)이 기본 수익률이다."""
from __future__ import annotations
import pandas as pd


def time_weighted_return(equity: pd.Series, flows: pd.Series | None = None) -> float:
    """시간가중수익률. equity: 일자별 마감 총자산(KRW), flows: 일자별 순입출금(KRW).

    - 입출금은 당일 장 시작 전 반영 가정: r_t = V_t / (V_{t-1} + F_t), TWR = ∏r_t − 1.
    - flows 는 equity.index 로 reindex 되며, equity 에 없는 날짜의 flow 는 무시되고
      flow 가 없는 날짜는 0 으로 처리된다 (호출자가 인덱스를 맞출 책임).
    - 기저(V_{t-1} + F_t) ≤ 0 인 구간(예: 전액 출금)은 수익률을 정의할 수 없어
      그 구간의 배율을 1로 두고 건너뛴다.
    """
    eq = equity.dropna()
    if len(eq) < 2:
        return 0.0
    if flows is None:
        f = pd.Series(0.0, index=eq.index)
    else:
        f = flows.reindex(eq.index).astype("float64").fillna(0.0)
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
        net_flows = float(flows.reindex(eq.index[1:]).astype("float64").fillna(0.0).sum())
    return float(eq.iloc[-1] - eq.iloc[0] - net_flows)


def benchmark_return(index: "pd.Series | None", start, end) -> float | None:
    """구간 [start, end] 의 벤치마크(지수) 수익률. index 가 없거나 비어있으면 None.

    거래일이 아닌 start/end 도 asof() 로 직전 값에 정렬해 처리한다.
    시작/끝 값을 asof 로 구할 수 없거나(NaN, 범위 밖) 시작값이 0 이면 None.
    """
    if index is None or len(index) == 0:
        return None
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    try:
        v0 = index.asof(start_ts)
        v1 = index.asof(end_ts)
    except Exception:
        return None
    if v0 is None or v1 is None or pd.isna(v0) or pd.isna(v1) or v0 == 0:
        return None
    return float(v1 / v0 - 1.0)


def risk_metrics(
    equity: pd.Series,
    trades: pd.DataFrame | None = None,
    flows: pd.Series | None = None,
    periods_per_year: int = 252,
) -> dict:
    """위험조정 지표 모음. 무위험수익률=0 가정.

    - cagr/volatility/sharpe/sortino/calmar: equity 의 일간수익률 기반.
    - profit_factor/avg_win/avg_loss/win_loss_ratio/expectancy/max_consecutive_losses:
      trades 의 SELL(실현손익) 행 기반. trades 가 없거나 "side" 컬럼이 없으면
      realized_pnl 전체를 그대로 사용한다.
    - recovery_days: 최대낙폭 저점 이후 직전 고점을 회복하기까지의 일수
      (미회복이면 마지막 시점까지의 일수).
    """
    eq = equity.dropna()
    ret = eq.pct_change().dropna()

    if len(ret) > 0 and eq.iloc[0] != 0:
        cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (periods_per_year / len(ret)) - 1.0)
    else:
        cagr = 0.0

    if len(ret) > 0:
        volatility = float(ret.std(ddof=0) * (periods_per_year ** 0.5))
    else:
        volatility = 0.0
    sharpe = float((ret.mean() * periods_per_year) / volatility) if volatility > 0 else 0.0

    downside = ret[ret < 0]
    if len(downside) > 0:
        downside_std = float(downside.std(ddof=0))
    else:
        downside_std = 0.0
    sortino_denom = downside_std * (periods_per_year ** 0.5)
    sortino = float((ret.mean() * periods_per_year) / sortino_denom) if sortino_denom > 0 else 0.0

    mdd = max_drawdown(eq)
    if mdd != 0:
        calmar = float(cagr / abs(mdd))
    else:
        # mdd==0 (낙폭 없음) → calmar(위험조정 지표) 측정 불가, 0 반환 (cagr 로 대체하지 않음)
        calmar = 0.0

    profit_factor = 0.0
    avg_win = 0.0
    avg_loss = 0.0
    win_loss_ratio = 0.0
    expectancy = 0.0
    max_consecutive_losses = 0

    if trades is not None and len(trades) > 0 and "realized_pnl" in trades.columns:
        # "side" 컬럼이 있으면 SELL(실현손익 발생) 행만 명시적으로 필터링한다.
        # 호출자(report.py/queries)는 side+realized_pnl 을 갖춘 DataFrame 을 넘기는 것이 계약이며,
        # side 컬럼이 없는 경우에만 realized_pnl 전체를 그대로 사용한다.
        if "side" in trades.columns:
            pnl = trades.loc[trades["side"] == "SELL", "realized_pnl"].astype("float64")
        else:
            pnl = trades["realized_pnl"].astype("float64")
        pnl = pnl.dropna()
        if len(pnl) > 0:
            wins = pnl[pnl > 0]
            losses = pnl[pnl < 0]
            win_sum = float(wins.sum())
            loss_sum = float(losses.sum())  # <= 0
            profit_factor = win_sum / abs(loss_sum) if loss_sum != 0 else 0.0
            avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
            avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.0
            win_loss_ratio = avg_win / avg_loss if avg_loss != 0 else 0.0
            expectancy = float(pnl.mean())

            cur_losses = 0
            best_losses = 0
            for v in pnl:
                if v < 0:
                    cur_losses += 1
                    best_losses = max(best_losses, cur_losses)
                else:
                    cur_losses = 0
            max_consecutive_losses = best_losses

    recovery_days = 0
    if len(eq) >= 2:
        cummax = eq.cummax()
        dd = eq / cummax - 1.0
        trough_idx = dd.idxmin()
        if dd.loc[trough_idx] == 0:
            recovery_days = 0  # 낙폭 없음 (전 구간 신고점)
        else:
            peak_val = cummax.loc[trough_idx]
            after_trough = eq.loc[trough_idx:].iloc[1:]  # 저점 자신은 제외
            recovered = after_trough[after_trough >= peak_val]
            if len(recovered) > 0:
                recovery_days = (recovered.index[0] - trough_idx).days
            else:
                recovery_days = (eq.index[-1] - trough_idx).days

    return {
        "cagr": cagr,
        "volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "expectancy": expectancy,
        "max_consecutive_losses": max_consecutive_losses,
        "recovery_days": recovery_days,
    }
