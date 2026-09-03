"""리플레이 오케스트레이션: 과거 일봉을 날짜 루프로 엔진에 주입한다.
같은 달력 날짜의 KR·US 세션은 같은 스텝에서 처리한다(일 단위 근사)."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, time as _Time, timedelta
import pandas as pd

from simcore.config import Config
from simcore.engine import Engine
from simcore.intraday_path import PathOrder, day_slices
from simcore.models import DailyBar, Market, SymbolSnapshot
from simcore import signals as sigmod
from simcore import metrics
from simcore import data as datamod
from simcore.signal_status import holding_signal_row

# 잠정봉 신호 계산에 넘길 히스토리 길이. 지표 워밍업(일목 78거래일)에 여유를 더한 값 —
# 전체 히스토리를 매 슬라이스마다 재계산하면 O(일수 × 슬라이스 × 전체길이) 로 폭발한다.
_INTRADAY_WINDOW = 160


@dataclass
class DataBundle:
    kr: dict[str, pd.DataFrame]
    us: dict[str, pd.DataFrame]
    fx: pd.Series  # KRW per USD
    kr_index: pd.Series | None = None
    us_index: pd.Series | None = None


@dataclass(frozen=True)
class IntradayReplayOptions:
    """리플레이에서 장중 경로(`Engine.evaluate_intraday`)를 태우는 설정.

    `Config().rules.intraday_enabled` 가 True 일 때만 적용된다. 일봉에는 경로 정보가 없어
    `intraday_path` 모듈이 (O,H,L,C) 로 꺾은선을 **가정**하므로, 결과는 절대값이 아니라
    `order` 양방향의 폭(envelope)으로 읽어야 한다 — 자세한 한계는 그 모듈 docstring 참고.

    - `slices`: 하루당 장중 스캔 횟수. 비용이 슬라이스 수에 선형으로 늘어난다
      (종목마다 매 슬라이스 지표 재계산). 실무적으로 4~8 권장.
    - `order`: 가격 경로 가정. "low_first"(보수적, 기본) / "high_first".
    - `session_start` · `scan_minutes`: 합성 타임스탬프용. 엔진의 재매수 쿨다운
      (`intraday_reentry_cooldown_min`)이 실제 분 단위 간격으로 동작하게 한다.
    """
    slices: int = 4
    order: PathOrder = "low_first"
    session_start: _Time = _Time(9, 0)
    scan_minutes: int = 10
    # True = 손익절 틱만 돌린다(장중 매매 판정 없음). 라이브 스케줄러의 `tick_{market}`
    # 잡은 `intraday_enabled` 와 **무관하게 5분마다** on_tick→check_stops 를 호출하는데,
    # 리플레이는 그걸 하루 1회로만 모사해 왔다. 그 차이를 메우는 모드이므로
    # `intraday_enabled=False` 여도 동작한다.
    tick_only: bool = False


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
    """시장별 일봉. 깨진 봉(o/h/l/c ≤ 0 등)은 여기서 걸러낸다 — 호출자가 직접 만든
    DataBundle(예: DB에서 조립한 것)도 보호하기 위해서다. low=0 인 봉 하나가
    `check_stops` 에서 그 종목 보유분을 전부 허위 손절시킨다."""
    return {Market.KR: {s: datamod.sanitize_ohlcv(df) for s, df in bundle.kr.items()},
            Market.US: {s: datamod.sanitize_ohlcv(df) for s, df in bundle.us.items()}}


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


def _intraday_step(engine: Engine, config: Config, market: Market, d: Date,
                   todays: dict, opts: IntradayReplayOptions, fx: float,
                   running_px: dict[str, float]) -> None:
    """하루치 장중 스캔을 순서대로 실행한다 — 라이브의 on_tick + on_intraday 대응.

    각 슬라이스마다 ① 손익절 틱(현재가 유사봉, `on_tick` 과 동일한 o=h=l=c 형태)
    ② 잠정봉 스냅샷으로 `evaluate_intraday`. 잠정봉 신호는 라이브와 같은
    `fired_at_provisional` 로 뽑아 거래량 배율 의존 신호를 제외한다.
    """
    # 종목별 슬라이스 사전 계산 (경로 가정은 intraday_path 가 담당)
    sliced = {}
    for sym, (df, ts) in todays.items():
        bar = df.loc[ts]
        sliced[sym] = day_slices(float(bar["open"]), float(bar["high"]),
                                 float(bar["low"]), float(bar["close"]),
                                 float(bar["volume"]), opts.slices, opts.order)
    if not sliced:
        return
    base_dt = datetime.combine(d, opts.session_start)
    day_equity = engine.snapshot(running_px, fx)
    for k in range(opts.slices):
        now = base_dt + timedelta(minutes=opts.scan_minutes * (k + 1))
        # ① 손익절 틱. 라이브 on_tick 은 현재가만 아는 유사봉(o=h=l=c)을 쓰지만,
        #    리플레이는 직전 스캔 이후 지나간 구간(seg_low/seg_high)을 알고 있으므로
        #    그걸 쓴다 — 두 스캔 사이에 손절선을 찍고 되돌아온 경우를 놓치지 않기 위해서고,
        #    일봉 check_stops 가 이미 "저가 트리거 우선(보수적)"을 쓰는 관례와도 맞다.
        tick_bars = {sym: DailyBar(sym, d, s[k].close, s[k].seg_high, s[k].seg_low,
                                   s[k].close, 0.0)
                     for sym, s in sliced.items()}
        engine.check_stops(d, market, tick_bars, fx)
        if opts.tick_only:
            for sym, s_ in sliced.items():          # 최근가만 갱신(평가액 반영용)
                running_px[sym] = s_[k].close
            continue                                 # 장중 매매 판정 없음 — 틱만
        # ② 잠정봉 신호 판정
        snaps: dict[str, SymbolSnapshot] = {}
        for sym, (df, ts) in todays.items():
            sl = sliced[sym][k]
            loc = df.index.get_loc(ts)
            hist = df.iloc[max(0, loc - _INTRADAY_WINDOW):loc]     # 어제까지 확정분
            prov = pd.DataFrame([{"open": sl.open, "high": sl.high, "low": sl.low,
                                  "close": sl.close, "volume": sl.volume}], index=[ts])
            frame = sigmod.evaluate_frame(pd.concat([hist, prov]), config.signals)
            green, red = sigmod.fired_at_provisional(frame, ts)
            gs, rs, gate = sigmod.snapshot_scores(green, red, config.scores)
            prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else sl.close
            snaps[sym] = SymbolSnapshot(sym, market, green, red, sl.close,
                                        sl.close / prev_close - 1.0, sl.volume,
                                        green_score=gs, red_score=rs, buy_gate=gate)
            running_px[sym] = sl.close
        cur_equity = engine.snapshot(running_px, fx)
        # strengths={} → 체결강도 게이트는 스킵(리플레이엔 체결강도 데이터가 없다.
        # 라이브에서도 조회 실패 시 None 이면 같은 경로를 탄다).
        engine.evaluate_intraday(d, market, snaps, {}, fx, now,
                                 day_equity=day_equity, cur_equity=cur_equity)


def run_replay(config: Config, bundle: DataBundle, start: Date, end: Date,
               flows: list[FlowEvent] = (),
               intraday: IntradayReplayOptions | None = None) -> ReplayResult:
    md = _market_data(bundle)
    # 장중 매매 경로는 config 토글이 켜져 있을 때만. 단 tick_only(라이브 5분 손익절 틱
    # 모사)는 매매 토글과 무관하게 동작한다 — 라이브의 tick 잡이 그렇기 때문이다.
    if intraday is not None and intraday.tick_only:
        intraday_opts = intraday
    elif config.rules.intraday_enabled:
        intraday_opts = intraday or IntradayReplayOptions()
    else:
        intraday_opts = None
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
    # 보유 종목이 마지막 거래일의 universe 프레임에 없을 때(랭킹 이탈 등) red_score 를
    # 0 으로 리셋하지 않고 마지막으로 스냅샷이 있었던 날의 값을 승계하기 위한 누적맵
    # (orchestrator._prior_held_red_score 와 동일 원칙 — #7).
    last_red_by_market: dict[Market, dict[str, int]] = {m: {} for m in md}
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
            # 장중 경로(옵션): 개장 체결 후 ~ 마감 판정 전. 라이브의 시간 순서와 같다.
            if intraday_opts is not None:
                running_px = dict(last_close)
                running_px.update(opens)
                _intraday_step(engine, config, market, d,
                               {sym: (df, ts) for sym, df in todays.items()},
                               intraday_opts, fx, running_px)
                last_close.update(running_px)
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
                last_red_by_market[market][sym] = rs  # 마지막 스냅 시점 red_score 누적(승계용)
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
            red_score = (snap.red_score if snap is not None
                        else last_red_by_market.get(pos.market, {}).get(sym, 0))
            signal_status.append(holding_signal_row(
                date=last_day, character=name, symbol=sym, market=pos.market,
                pos=pos, red_score=red_score, close=last_close.get(sym),
                trail_pct=config.rules.trail_pct, trailing_top=config.rules.trailing_top))

    return ReplayResult(trades, equity, flows_by_char, green_hist, summary,
                        positions_by_char=positions_by_char,
                        cash_by_char=cash_by_char, last_close=dict(last_close),
                        signal_status=signal_status)
