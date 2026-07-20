"""리플레이 오케스트레이션: 과거 일봉을 날짜 루프로 엔진에 주입한다.
같은 달력 날짜의 KR·US 세션은 같은 스텝에서 처리한다(일 단위 근사)."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date as Date
import pandas as pd

from simcore.config import Config
from simcore.engine import Engine
from simcore.models import DailyBar, Market, SymbolSnapshot
from simcore import signals as sigmod
from simcore import metrics
from simcore import data as datamod


@dataclass
class DataBundle:
    kr: dict[str, pd.DataFrame]
    us: dict[str, pd.DataFrame]
    fx: pd.Series  # KRW per USD
    kr_index: pd.Series | None = None
    us_index: pd.Series | None = None


@dataclass(frozen=True)
class FlowEvent:
    date: Date
    character: str
    amount_krw: float
    liquidate: tuple[str, ...] = ()


@dataclass
class ReplayResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    flows_by_char: dict[str, pd.Series]
    green_hist: pd.Series
    summary: dict
    positions_by_char: dict = field(default_factory=dict)
    cash_by_char: dict = field(default_factory=dict)
    last_close: dict = field(default_factory=dict)
    signal_status: list = field(default_factory=list)


def _market_data(bundle: DataBundle) -> dict[Market, dict[str, pd.DataFrame]]:
    return {Market.KR: bundle.kr, Market.US: bundle.us}


_INDEX_NAME = {Market.KR: "KOSPI200", Market.US: "S&P500"}


def _char_benchmark(markets: tuple[Market, ...], indexes: dict[Market, pd.Series | None],
                     start: Date, end: Date) -> tuple[float | None, str]:
    """캐릭터의 시장 구성에 따른 벤치마크 수익률/이름.

    - 단일시장: 해당 시장 지수의 구간 수익률 (없으면 None/"").
    - 다중시장(범용형): 각 시장 지수 수익률의 단순평균("혼합").
      한쪽 지수만 있으면 그 지수 값을 그대로 사용(이름도 그 지수 이름).
      둘 다 없으면 None/"".
    """
    rets: dict[Market, float] = {}
    for m in markets:
        r = metrics.benchmark_return(indexes.get(m), start, end)
        if r is not None:
            rets[m] = r
    if not rets:
        return None, ""
    if len(markets) == 1:
        m = markets[0]
        return rets[m], _INDEX_NAME[m]
    if len(rets) == len(markets):
        return sum(rets.values()) / len(rets), "혼합"
    only_m = next(iter(rets))
    return rets[only_m], _INDEX_NAME[only_m]


def run_replay(config: Config, bundle: DataBundle, start: Date, end: Date,
               flows: list[FlowEvent] = ()) -> ReplayResult:
    md = _market_data(bundle)
    # 1) 신호 표를 종목당 한 번 벡터화 계산
    frames = {m: {sym: sigmod.evaluate_frame(df, config.signals)
                  for sym, df in data.items()}
              for m, data in md.items()}
    # 1-2) 시장 지수 SMA(시장별 기간) → 시장별 하락장(가드) 판정
    periods = {Market.KR: config.signals.market_trend_period_kr,
               Market.US: config.signals.market_trend_period_us}
    bearish_fn = datamod.make_bearish_fn(
        {Market.KR: bundle.kr_index, Market.US: bundle.us_index}, periods)
    # 2) 시뮬 날짜 = 두 시장 거래일 합집합 (start~end)
    all_dates = sorted({d for data in md.values() for df in data.values()
                        for d in df.index if start <= d.date() <= end})
    if not all_dates:
        raise ValueError("리플레이 구간에 거래일이 없습니다")
    flow_map: dict[Date, list[FlowEvent]] = {}
    for f in flows:
        flow_map.setdefault(f.date, []).append(f)

    engine = Engine(config)
    fx0 = float(bundle.fx.asof(all_dates[0]))
    engine.start(all_dates[0].date(), fx0)

    last_close: dict[str, float] = {}
    last_snaps_by_market: dict[Market, dict[str, SymbolSnapshot]] = {}
    equity_rows, green_counts = [], []
    for ts in all_dates:
        d = ts.date()
        fx = float(bundle.fx.asof(ts))
        opens_today: dict[str, float] = {}
        for market, data in md.items():
            opens = {sym: float(df.loc[ts, "open"])
                     for sym, df in data.items() if ts in df.index}
            opens_today.update(opens)
            if not opens:
                continue
            # (a) 입출금은 첫 시장 개장 전 1회 처리 (아래 공통 블록에서)
        for f in flow_map.get(d, []):
            engine.apply_flow(d, f.character, f.amount_krw, fx,
                              open_prices=opens_today, liquidate=f.liquidate)
        bearish = bearish_fn(ts)
        for market, data in md.items():
            todays = {sym: df for sym, df in data.items() if ts in df.index}
            if not todays:
                continue
            opens = {sym: float(df.loc[ts, "open"]) for sym, df in todays.items()}
            engine.fill_open(d, market, opens, fx)
            bars = {sym: DailyBar(sym, d, float(df.loc[ts, "open"]),
                                  float(df.loc[ts, "high"]), float(df.loc[ts, "low"]),
                                  float(df.loc[ts, "close"]), float(df.loc[ts, "volume"]))
                    for sym, df in todays.items()}
            engine.check_stops(d, market, bars, fx)
            snaps: dict[str, SymbolSnapshot] = {}
            for sym, df in todays.items():
                green, red = sigmod.fired_at(frames[market][sym], ts)
                gs, rs, gate = sigmod.snapshot_scores(green, red, config.scores)
                loc = df.index.get_loc(ts)
                prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else float(df.loc[ts, "close"])
                close = float(df.loc[ts, "close"])
                snaps[sym] = SymbolSnapshot(
                    sym, market, green, red, close,
                    close / prev_close - 1.0, float(df.loc[ts, "volume"]),
                    green_score=gs, red_score=rs, buy_gate=gate)
                last_close[sym] = close
                green_counts.append(gs)             # green_score 분포 기록
            last_snaps_by_market[market] = snaps    # 마지막 거래일 값으로 매 스텝 덮어씀
            engine.evaluate_close(d, market, snaps, bearish_by_market=bearish)
        eq = engine.snapshot(last_close, fx)
        equity_rows.append({"date": ts, **eq})

    # ---- 결과 집계 ----
    equity = pd.DataFrame(equity_rows).set_index("date")
    trades = pd.DataFrame([{
        "date": t.date, "character": t.character, "symbol": t.symbol,
        "market": t.market.value, "side": t.side.value, "quantity": t.quantity,
        "price": t.price, "fee": t.fee, "tax": t.tax, "reason": t.reason.value,
        "green_count": t.green_count, "red_count": t.red_count,
        "green_score": t.green_score, "red_score": t.red_score,
        "fired": ";".join(t.fired), "realized_pnl": t.realized_pnl,
        "decision_type": t.decision_type.value, "trigger_rule": t.trigger_rule,
    } for st in engine.states.values() for t in st.portfolio.trades])

    indexes = {Market.KR: bundle.kr_index, Market.US: bundle.us_index}
    flows_by_char, summary = {}, {}
    for name, st in engine.states.items():
        f = pd.Series({pd.Timestamp(fl.date): fl.amount_krw
                       for fl in st.portfolio.flows[1:]})  # 첫 입금(초기자금) 제외
        f = f.groupby(level=0).sum()
        flows_by_char[name] = f
        eq = equity[name]
        char_trades = trades[trades.character == name] if not trades.empty else trades
        twr = metrics.time_weighted_return(eq, f)
        bmk_ret, bmk_name = _char_benchmark(st.spec.markets, indexes, start, end)
        bmk_delta = (twr - bmk_ret) if bmk_ret is not None else None
        summary[name] = {
            "twr": twr,
            "mdd": metrics.max_drawdown(eq),
            "pnl_krw": metrics.simple_pnl_krw(eq, f),
            "n_trades": int(len(char_trades)),
            "benchmark_return": bmk_ret,
            "benchmark_delta": bmk_delta,
            "benchmark_name": bmk_name,
        }
    green_hist = pd.Series(green_counts).value_counts().sort_index()

    positions_by_char = {}
    cash_by_char = {}
    for name, st in engine.states.items():
        positions_by_char[name] = [
            {"symbol": p.symbol, "market": p.market.value, "quantity": p.quantity,
             "avg_price": p.avg_price, "opened": p.opened,
             "peak_price": p.peak_price, "locked_stop_pct": p.locked_stop_pct}
            for p in st.portfolio.positions.values()
        ]
        cash_by_char[name] = {cur.value: amt for cur, amt in st.portfolio.cash.items()}

    # ---- 마지막 거래일의 후보/보유 상태 (감사 Phase B — 대시보드 의사결정판) ----
    last_day = all_dates[-1].date()
    signal_status: list[dict] = []
    for name, st in engine.states.items():
        for c in engine.last_candidates.get(name, []):
            signal_status.append({
                "date": last_day, "character": name, "symbol": c.symbol,
                "market": c.market.value, "kind": "후보",
                "green_score": c.green_score, "red_score": c.red_score,
                "buy_gate": c.buy_gate, "status": c.status,
                "block_reason": c.block_reason, "stop_px": None, "trail_px": None,
                "close": last_close.get(c.symbol),
            })
        for sym, pos in st.portfolio.positions.items():
            snap = last_snaps_by_market.get(pos.market, {}).get(sym)
            red_score = snap.red_score if snap is not None else 0
            stop_px = pos.avg_price * (1 + pos.locked_stop_pct)
            peak_gain = pos.peak_price / pos.avg_price - 1.0
            trail_px = (pos.peak_price * (1 - config.rules.trail_pct)
                        if peak_gain >= config.rules.trailing_top else None)
            signal_status.append({
                "date": last_day, "character": name, "symbol": sym,
                "market": pos.market.value, "kind": "보유",
                "green_score": 0, "red_score": red_score,
                "buy_gate": False, "status": "", "block_reason": "",
                "stop_px": stop_px, "trail_px": trail_px,
                "close": last_close.get(sym),
            })

    return ReplayResult(trades, equity, flows_by_char, green_hist, summary,
                        positions_by_char=positions_by_char,
                        cash_by_char=cash_by_char, last_close=dict(last_close),
                        signal_status=signal_status)
