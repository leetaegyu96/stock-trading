"""일봉 OHLC → 장중 슬라이스 근사. 리플레이에서 장중 경로(`evaluate_intraday`)를
태우기 위한 것으로, **실거래 판정에는 쓰이지 않는다**.

## 왜 필요한가

`run_replay` 는 하루 1사이클(마감 판정 → 다음 개장 체결)만 시뮬레이션했다. 그래서
`Orchestrator.on_intraday` / `Engine.evaluate_intraday` 는 **한 번도 백테스트된 적이 없는
코드 경로**였고, 2026-07-21~09-02 라이브에서 매도 312건 중 276건(88%)이 그 미검증 경로에서
나와 손실의 대부분을 만들었다(`docs/reviews/2026-09-02-live-loss-autopsy.html`).
이 모듈은 그 경로를 리플레이에서 실행 가능하게 만든다.

## 이 근사가 할 수 있는 것과 없는 것

일봉에는 **경로 정보가 없다.** (O, H, L, C) 는 하루의 네 통계량일 뿐, 고가와 저가 중 무엇이
먼저였는지, 그 사이를 어떻게 오갔는지 담고 있지 않다. 따라서 이 모듈이 만드는 경로는
**가정**이다.

- **검증할 수 있는 것**: 장중 로직의 *메커니즘*(스캔이 도는가, 가드가 걸리는가, 휩쏘 캡·
  재매수 쿨다운·킬스위치가 동작하는가), 규칙 변경의 *방향성*(평가 빈도를 올리면 손익이
  어느 쪽으로 움직이는가), 그리고 하루 1사이클 대비 *상대 비교*.
- **검증할 수 없는 것**: 정확한 손익. 실제 장중 경로는 여기 만든 꺾은선보다 훨씬 많이
  배회하므로 체결가·체결 횟수가 다르다. 이 하니스의 숫자를 절대값으로 인용하면 안 된다.

그래서 `order` 를 두 가지로 제공한다. **두 방향을 모두 돌려 그 폭(envelope)을 보는 것이
올바른 사용법**이며, 한쪽 값만 인용하는 것은 근사를 사실로 오인하는 것이다.

## 경로 구성

꺾은선 O → A → B → C 를 가격 이동거리에 비례해 등간격 샘플링한다(등속 이동 가정).

- `low_first`  (기본): O → L → H → C. 저가를 먼저 밟으므로 손절이 더 자주 걸린다 —
  `Engine.check_stops` 가 이미 "저가 트리거 우선(보수적)"을 쓰는 관례와 같은 방향.
- `high_first`         : O → H → L → C. 고가를 먼저 밟아 트레일링 피크가 먼저 올라간다.

슬라이스 k(1..n)는 구간 **내부**의 k/(n+1) 지점에 놓는다. 종가는 슬라이스에 포함하지 않고
마감 경로(`evaluate_close`)에 맡긴다 — 장중 스캔과 마감 판정의 역할을 섞지 않기 위해서다.

거래량은 `V * k/(n+1)` 로 **선형 누적**한다. 실제 장중 거래량은 개장·마감에 몰리는 U자형
이라 선형은 개장 직후를 과소평가한다. 다만 v1.16.1 이후 거래량 배율에 민감한 신호
(`signals.VOLUME_SCALE_DEPENDENT`)는 잠정봉 판정에서 제외되므로, 이 근사가 신호에 미치는
영향은 제한적이다(OBV·VWAP 은 배율에 사실상 불변 — trading-rules §17-1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PathOrder = Literal["low_first", "high_first"]
PATH_ORDERS: tuple[PathOrder, ...] = ("low_first", "high_first")


@dataclass(frozen=True)
class IntradaySlice:
    """장중 한 스캔 시점의 잠정봉. `Orchestrator.on_intraday` 가 만드는 것과 같은 모양.

    `high`/`low` 는 **경로를 따라 실제로 지나간** 구간의 극값이다(샘플 지점만의 극값이
    아니다). 두 슬라이스 사이에서 저가를 찍고 되돌아온 경우까지 반영해야 손절 판정이
    현실과 맞는다 — 샘플 지점만 보면 그 저가를 통째로 놓친다.
    """
    index: int          # 1-based 슬라이스 번호
    fraction: float     # 세션 경과 비율 (0, 1)
    open: float         # 당일 시가 (고정)
    high: float         # 개장~현재까지 지나간 고가
    low: float          # 개장~현재까지 지나간 저가
    close: float        # 현재가
    volume: float       # 당일 누적 거래량 (선형 근사)
    seg_high: float     # 직전 슬라이스~현재 사이에 지나간 고가
    seg_low: float      # 직전 슬라이스~현재 사이에 지나간 저가


def _waypoints(open_: float, high: float, low: float, close: float,
               order: PathOrder) -> list[float]:
    if order == "low_first":
        return [open_, low, high, close]
    if order == "high_first":
        return [open_, high, low, close]
    raise ValueError(f"알 수 없는 경로 순서: {order!r} (가능: {PATH_ORDERS})")


def _traverse(points: list[float], t0: float, t1: float) -> tuple[float, float, float]:
    """꺾은선을 가격 이동거리 기준 등속으로 t0→t1 만큼 지나갈 때의 (저가, 고가, 도착가).

    구간 안에 있는 **꼭짓점까지 포함**해 극값을 잡는다 — 샘플 지점만 보면 두 스캔 사이에
    찍고 되돌아온 고저를 놓친다.
    """
    segs = [abs(points[i + 1] - points[i]) for i in range(len(points) - 1)]
    total = sum(segs)
    if total <= 0:                       # 완전 평탄한 날(O=H=L=C)
        return points[0], points[0], points[0]

    def at(t: float) -> float:
        target = min(max(t, 0.0), 1.0) * total
        walked = 0.0
        for i, seg in enumerate(segs):
            if walked + seg >= target or i == len(segs) - 1:
                frac = (target - walked) / seg if seg > 0 else 0.0
                return points[i] + (points[i + 1] - points[i]) * min(max(frac, 0.0), 1.0)
            walked += seg
        return points[-1]                # 도달 불가(방어)

    start, endp = at(t0), at(t1)
    lo = min(start, endp)
    hi = max(start, endp)
    # 구간 내부에 걸친 꼭짓점 반영
    walked = 0.0
    for i, seg in enumerate(segs):
        walked += seg
        v_t = walked / total             # 꼭짓점 points[i+1] 의 진행도
        if t0 < v_t < t1:
            lo = min(lo, points[i + 1])
            hi = max(hi, points[i + 1])
    return lo, hi, endp


def day_slices(open_: float, high: float, low: float, close: float, volume: float,
               n: int, order: PathOrder = "low_first") -> list[IntradaySlice]:
    """일봉 하나 → 장중 슬라이스 n 개. n<=0 이면 빈 리스트.

    반환되는 각 슬라이스의 high/low 는 **그 시점까지의 누적** 극값이라 단조 확장한다
    (장중에 관측 가능한 정보만 담는다 — 미래의 고저를 미리 알려주지 않는다).
    """
    if n <= 0:
        return []
    if not (low <= open_ <= high and low <= close <= high):
        raise ValueError(
            f"OHLC 정합성 위반: open={open_} high={high} low={low} close={close}")
    pts = _waypoints(open_, high, low, close, order)
    out: list[IntradaySlice] = []
    run_hi, run_lo = open_, open_
    prev_t = 0.0
    for k in range(1, n + 1):
        t = k / (n + 1)                  # 구간 내부만 — 종가는 마감 경로가 맡는다
        seg_lo, seg_hi, px = _traverse(pts, prev_t, t)
        run_hi, run_lo = max(run_hi, seg_hi), min(run_lo, seg_lo)
        out.append(IntradaySlice(index=k, fraction=t, open=open_,
                                 high=run_hi, low=run_lo, close=px,
                                 volume=volume * t,
                                 seg_high=seg_hi, seg_low=seg_lo))
        prev_t = t
    return out
