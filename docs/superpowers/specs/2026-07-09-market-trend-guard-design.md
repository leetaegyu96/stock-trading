# 시장지수 추세 필터 (하락장 가드) — 설계 스펙

- 날짜: 2026-07-09
- 상태: 사용자 승인 완료 (브레인스토밍 세션)
- 상위: 주식 모의투자 시뮬레이터 — 서브프로젝트 6(전략 튜닝)
- 목표: **범용형 손실·MDD 개선.** 손실 최소화 취지 강화 — 하락장에서 신규매수를 막아 큰 낙폭을 줄인다.

## 1. 배경

v1.3.0 신호 v2의 6개월 리플레이에서 범용형이 −12.1%(MDD −25.7%)로 손실. 최종 리뷰 결론은
전략 튜닝 사안 — 하락 구간에서도 게이트를 통과한 종목을 계속 신규매수해 상관 낙폭이 누적됐다.
`TradeRules.bear_market_guard` 플래그는 sp4에서 자리만 잡고 동작이 없었다(항상 off). 이번에 **시장지수
추세 필터**로 실제 동작을 부여한다.

## 2. 규칙

- 시장별 **대표 지수의 20일 이동평균**을 계산한다: KR = 코스피200(pykrx `1028`), US = S&P500(`^GSPC`).
- 어떤 거래일에 **지수 종가 < 지수 20일선**이면 그 시장은 그날 "하락장"으로 판정.
- `bear_market_guard=True`이고 해당 시장이 하락장이면 **그 시장의 신규매수를 전면 차단**한다.
  - 보유 종목·매도 판정·손절/트레일링·부분매도는 **그대로**(손실 방어는 계속 작동).
  - 매수 대기(pending_buys) 자체를 만들지 않는다(evaluate_close에서 후보 제외).
- `bear_market_guard=False`(기본)이면 기존과 동일(behavior 무변경) — 하위 호환.

## 3. 엔진 변경 (`simcore/engine.py`)

- `evaluate_close(d, market, snaps, market_bearish: bool = False)` — 파라미터 추가.
  매수 후보 루프에서 `self.config.rules.bear_market_guard and market_bearish`이면 신규매수 후보를
  추가하지 않는다(쿨다운 감소·매도 판정은 정상 수행). 기본값 False라 기존 호출 무영향.

## 4. 데이터 (`simcore/data.py`, `simcore/replay.py`)

- `data.py`: `load_index(symbol_or_code, market, start, end, cache) -> pd.Series`(지수 종가). KR은
  pykrx `get_index_ohlcv`(1028), US는 yfinance(`^GSPC`). 워밍업 패딩 포함. 캐시.
- `DataBundle`에 `kr_index: pd.Series | None = None`, `us_index: pd.Series | None = None` 추가.
- `run_replay`: 각 지수의 20일선을 계산하고, 시뮬 날짜별로 시장별 `market_bearish`를 판정해
  `engine.evaluate_close(..., market_bearish=flag)`로 전달. 지수 데이터가 없으면 False(가드 미작동).

## 5. 설정 (`simcore/config.py`)

- `TradeRules.bear_market_guard: bool` (기본 False 유지) — 이제 실제 동작.
- `SignalParams.market_trend_period: int = 20` (지수 이동평균 기간).
- A/B용 CLI 스위치: `--bear-guard`(플래그) → `bear_market_guard=True`로 설정.

## 6. 라이브 (`simcore/live/orchestrator.py`)

- 이번 범위에서 라이브는 `market_bearish=False`(가드 미작동, 기존과 동일)로 둔다 — 지수 실시간
  피드 연동은 후속. `bear_market_guard` 기본 False이므로 라이브 동작 무변경. (문서에 후속 명시.)

## 7. 실험 (A/B)

- 동일 구간(2026-01-09~2026-07-09)·유니버스로 두 번 리플레이:
  - **A(baseline)**: `bear_market_guard=False` (= v1.3.0 결과 재현).
  - **B(guard)**: `--bear-guard` (True).
- 캐릭터별 TWR·MDD·거래수·승률 비교, 특히 **범용형 손실·MDD 개선** 여부. `docs/experiments/`에 A/B 기록.

## 8. trading-rules.md

- "하락장 가드" 절 추가: 지수 20일선 이탈 시 신규매수 차단, 기본 off, `--bear-guard`로 활성.

## 9. 테스트

- 지수 20일선 하락장 판정(합성 지수 시계열).
- 엔진: `market_bearish=True` + guard on → 신규매수 후보 미생성(매도·쿨다운은 정상); guard off →
  기존대로 매수. 경계(지수==20일선).
- 리플레이 통합: 하락 지수 구간에서 매수 억제 확인(결정론 fixture).

## 10. 완료 기준

1. `python -m simcore --start 2026-01-09 --end 2026-07-09 --bear-guard` 정상 실행.
2. pytest 통과(신규 + 갱신).
3. A/B 결과를 `docs/experiments/`에 기록, 범용형 지표 변화 명시.
4. trading-rules.md 갱신, config와 1:1.

## 11. 범위 밖

- 라이브 지수 실시간 피드 연동(후속).
- 업종 강도·개별종목 추세 강화·VIX 등 추가 필터(후속).
