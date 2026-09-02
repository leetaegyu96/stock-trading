"""청/적신호 판정. 계산식은 docs/trading-rules.md v2 와 1:1 대응.
스텁(항상 False): G19·G21·G24·G25~30, R22·R25~30 — 후속에서 대체.
G8(괴리율 과매도 반등)·G9(저항 돌파)·R20(괴리율 과열 확장)은 #27 에서 실신호로 전환.
R7(손절)/R10(트레일링)은 포지션 상태에 의존하므로 engine 이 판정한다."""
from __future__ import annotations
import pandas as pd

from simcore.config import SignalParams, SignalScores
from simcore import indicators as ind

GREEN_COLS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G12",
              "G13", "G14", "G15", "G16", "G17", "G18", "G23"]
RED_COLS = ["R1", "R2", "R3", "R4", "R5", "R6", "R11", "R12", "R13", "R14",
            "R15", "R16", "R17", "R18", "R19", "R20", "R23", "R24"]
STUB_GREEN = ["G19", "G21", "G24"]
STUB_RED = ["R22"]

# 당일 "누적" 거래량을 전일/평균의 "완성" 거래량과 직접 비교하는 신호들.
# 장중 잠정봉에서는 좌변만 부분값이라 판정이 성립하지 않는다 — G5/R5/G23 은 surge
# (vol >= vol_avg*1.5), R24 는 (vol < 전일 vol) & (vol < vol_avg).
#
# 실측(일봉 3,278 종목일, 개장 30분 f=0.10 을 마감 f=1.00 과 대조):
#   R24 22.7% → 49.5% (판정 뒤집힘 26.8%)  ← 4점 적신호가 상시 점등
#   R5   3.3% → 0.0%,  G5 3.0% → 0.0%,  G23 0.7% → 0.0%  (장중엔 아예 발화 불가)
# 나머지 33개 신호는 뒤집힘 0.0%. OBV(G13/R13)는 방향이 종가차 부호로만 결정돼
# 거래량 배율에 불변이고, VWAP(G14/R14)도 0.0~0.1% 로 무시할 수준이라 제외 대상이 아니다.
#
# 누적량을 경과시간으로 나눠 "하루치 추정"으로 정규화하는 대안은 채택하지 않았다:
# 장중 거래량은 U자형이라 선형 추정이 개장 직후 과대추정하고, 무엇보다 리플레이에
# 장중 경로가 없어 그 추정기를 검증할 수단이 없다(검증 없는 장중 로직이 애초의 손실
# 원인이었다 — docs/reviews/2026-09-02-live-loss-autopsy.html).
#
# ── 이 처리의 한계(측정치, 개장 30분 기준) ──────────────────────────────
# 오차가 사라지는 게 아니라 부호가 뒤집힌다. R24 가 정당하게 발화하던 22.7% 의 경우
# 까지 4점을 잃기 때문이다. 마감 확정봉을 정답으로 놓고 비교하면:
#             적신호 평균      전량매도 발동률     매수 가능
#   마감        11.01점          50.5%           8.18%
#   수정 전     12.01 (+1.00)    61.9% (+11.4%p)  8.18%
#   수정 후     10.03 (-0.98)    37.2% (-13.3%p)  8.18%
# 다만 방향이 다르다 — 수정 전은 "과매도"(실제 손실의 원인), 수정 후는 "과소매도"이고
# 이는 매일 마감의 확정봉 판정(on_close)이 바로잡는다. 강제매도(R7/R10/R18)는 이
# 필터와 무관하게 유효하고, 매수 게이트 통과율은 8.18% 로 완전히 동일하다(거래량 관문은
# 실질적으로 G13 이 담당 — 라이브 매수 105건 전부가 G13 으로 통과).
# 오차를 실제로 줄이려면 시간대별 거래량 프로파일(장중 U자형 곡선)이 필요하며, 그건
# 장중 리플레이 하니스와 함께 별도로 다뤄야 한다 — 장중매매 재활성화의 전제.
VOLUME_SCALE_DEPENDENT = frozenset({"G5", "G23", "R5", "R24"})


def min_history(p: SignalParams) -> int:
    return max(
        p.breakout_lookback + 1,
        p.sma_slow + 1,
        p.macd_slow + p.macd_signal,
        p.bb_period + 1,
        p.rsi_period + 2,
        p.stoch_k + p.stoch_k_smooth + p.stoch_d,
        p.adx_period * 2,
        p.ichimoku_senkou_b + p.ichimoku_kijun,   # 일목: 52+26
        p.atr_squeeze_lookback + 1,
        p.support_lookback + 1,
        p.box_lookback + 1,
    )


def evaluate_frame(df: pd.DataFrame, p: SignalParams) -> pd.DataFrame:
    close, open_, high, low, vol = (df["close"], df["open"], df["high"],
                                    df["low"], df["volume"])
    sma_f = ind.sma(close, p.sma_fast)
    sma_s = ind.sma(close, p.sma_slow)
    rsi = ind.rsi(close, p.rsi_period)
    macd_line, macd_sig = ind.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
    bb_mid, bb_up, bb_lo = ind.bollinger(close, p.bb_period, p.bb_std)
    k, d = ind.stochastic(high, low, close, p.stoch_k, p.stoch_k_smooth, p.stoch_d)
    vol_avg = ind.sma(vol, p.volume_avg_period)
    adx_, di_p, di_m = ind.adx(high, low, close, p.adx_period)
    obv_ = ind.obv(close, vol)
    vwap_ = ind.vwap(high, low, close, vol, p.vwap_period)
    sar = ind.parabolic_sar(high, low, p.sar_af_step, p.sar_af_max)
    _, _, span_a, span_b = ind.ichimoku(high, low, close, p.ichimoku_tenkan,
                                        p.ichimoku_kijun, p.ichimoku_senkou_b)
    atr_ = ind.atr(high, low, close, p.atr_period)
    disp = ind.disparity(close, p.disparity_period)
    sup, res = ind.support_resistance(high, low, close, p.sr_lookback)

    surge = vol >= vol_avg * p.volume_surge_ratio
    prev_high = close.rolling(p.breakout_lookback).max().shift(1)     # 신고가(60일)
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    cloud_bot = pd.concat([span_a, span_b], axis=1).min(axis=1)
    box_high = close.rolling(p.box_lookback).max().shift(1)
    box_low = close.rolling(p.box_lookback).min().shift(1)
    boxed = (box_high - box_low) / box_low < p.box_range_max
    support = low.rolling(p.support_lookback).min().shift(1)
    atr_avg = atr_.rolling(p.atr_squeeze_lookback).mean()
    atr_bo_high = close.rolling(p.atr_breakout_lookback).max().shift(1)

    out = pd.DataFrame(index=df.index)
    # ── 청신호 ──
    out["G1"] = sma_f > sma_s
    out["G2"] = close > sma_s
    out["G3"] = (rsi.shift(1) <= p.rsi_buy_cross) & (rsi > p.rsi_buy_cross)
    out["G4"] = macd_line > macd_sig
    out["G5"] = surge & (close > open_)
    out["G6"] = (close.shift(1) <= bb_mid.shift(1)) & (close > bb_mid)
    out["G7"] = close > prev_high
    out["G10"] = (k.shift(1) < p.stoch_oversold) & (k.shift(1) <= d.shift(1)) & (k > d)
    out["G11"] = adx_ >= p.adx_threshold
    out["G12"] = di_p > di_m
    out["G13"] = obv_ > obv_.shift(p.obv_slope_lookback)
    out["G14"] = (close.shift(1) <= vwap_.shift(1)) & (close > vwap_)
    out["G15"] = (close.shift(1) <= cloud_top.shift(1)) & (close > cloud_top)
    out["G16"] = (close.shift(1) <= sar.shift(1)) & (close > sar)
    out["G17"] = (atr_.shift(1) < atr_avg.shift(1)) & (close > atr_bo_high)
    out["G18"] = boxed & (close > box_high)
    out["G23"] = (close > prev_high) & surge
    out["G9"] = (close.shift(1) <= res.shift(1)) & (close > res)
    out["G8"] = (disp.shift(1) <= p.disparity_oversold) & (disp > p.disparity_oversold)
    # ── 적신호 ──
    out["R1"] = sma_f < sma_s
    out["R2"] = close < sma_s
    out["R3"] = (rsi.shift(1) >= p.rsi_overbought) & (rsi < rsi.shift(1))
    out["R4"] = macd_line < macd_sig
    out["R5"] = surge & (close < open_)
    out["R6"] = close < bb_lo
    out["R11"] = (adx_.shift(1) >= p.adx_threshold) & (adx_ < adx_.shift(1))
    out["R12"] = di_m > di_p
    out["R13"] = obv_ < obv_.shift(p.obv_slope_lookback)
    out["R14"] = (close.shift(1) >= vwap_.shift(1)) & (close < vwap_)
    out["R15"] = (close.shift(1) >= cloud_bot.shift(1)) & (close < cloud_bot)
    out["R16"] = (close.shift(1) >= sar.shift(1)) & (close < sar)
    out["R17"] = atr_ > atr_avg * p.atr_surge_ratio
    out["R18"] = close < support
    out["R19"] = open_ < close.shift(1) * (1 + p.gap_down_pct)
    out["R23"] = (close < open_) & ((open_ - close) / open_ >= p.big_body_pct)
    out["R24"] = (close > close.shift(1)) & (vol < vol.shift(1)) & (vol < vol_avg)
    out["R20"] = disp >= p.disparity_overbought
    # ── 스텁(항상 False) ──
    for stub in STUB_GREEN + STUB_RED:
        out[stub] = False

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


def fired_at_provisional(frame: pd.DataFrame, d) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """장중 잠정봉용 발화 목록 — `VOLUME_SCALE_DEPENDENT` 를 제외한다.

    잠정봉의 거래량은 당일 누적(부분)이라 완성 거래량과 비교하는 신호는 값이 정의되지
    않는다. 값을 지어내는 대신 "판정하지 않는다"(미발화 처리). 마감 확정봉을 다루는
    `fired_at` 은 영향받지 않는다."""
    green, red = fired_at(frame, d)
    return (tuple(c for c in green if c not in VOLUME_SCALE_DEPENDENT),
            tuple(c for c in red if c not in VOLUME_SCALE_DEPENDENT))


def score(codes, scores: SignalScores) -> tuple[int, dict]:
    by_cat: dict[str, int] = {}
    for c in codes:
        cat = scores.category.get(c)
        if cat is None:
            continue
        by_cat[cat] = by_cat.get(cat, 0) + scores.points.get(c, 0)
    capped = {cat: min(pts, scores.caps.get(cat, pts)) for cat, pts in by_cat.items()}
    return sum(capped.values()), capped


def buy_gate_ok(green_codes, scores: SignalScores) -> bool:
    fired = set(green_codes)
    return all(bool(fired & members) for members in scores.buy_gate.values())


def snapshot_scores(green, red, scores: SignalScores) -> tuple[int, int, bool]:
    gs, _ = score(green, scores)
    rs, _ = score(red, scores)
    return gs, rs, buy_gate_ok(green, scores)


def signal_confidence(score: int, scores: SignalScores, side: str = "green") -> float:
    """저장된 green_score/red_score 를 [0,1] 로 정규화(순수 표시용 파생값, read-only).

    MAX 는 하드코딩하지 않고 side(코드가 "G"/"R" 로 시작)에 해당하는 카테고리들의
    caps 합으로 매 호출마다 동적으로 계산한다(config.py 의 category/caps 가 바뀌면
    자동 반영). 매매 판정에는 쓰이지 않는다."""
    prefix = "G" if side == "green" else "R"
    categories = {cat for c, cat in scores.category.items() if c.startswith(prefix)}
    max_score = sum(scores.caps.get(cat, 0) for cat in categories)
    if max_score <= 0:
        return 0.0
    return round(min(1.0, max(0.0, score / max_score)), 2)
