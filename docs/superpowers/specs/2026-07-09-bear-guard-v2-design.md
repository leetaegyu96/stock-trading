# 하락장 가드 v2 (캐릭터 시장 전체 하락 시만 차단) — 설계 스펙

- 날짜: 2026-07-09
- 상태: 사용자 승인(방향 "ㄱㄱ") — sp6 A/B 후속 튜닝
- 상위: 서브프로젝트 6 후속. v1.5.0 A/B에서 가드가 해외형엔 유효했으나 범용형엔 역효과
  (TWR −12→−17, MDD −25.7→−34.7) — 한쪽 시장만 하락해도 범용형 전체 신규매수가 막혀
  과도 발동한 것이 유력 원인.

## 1. 규칙 변경

- v1(현행): `evaluate_close(market_bearish)` — 지금 처리 중인 시장이 하락장이면 그 시장 신규매수 차단.
- **v2(변경)**: 가드는 **"캐릭터가 거래하는 모든 시장이 하락장"일 때만** 그 캐릭터의 신규매수를 차단.
  - 국내형(KR만)·해외형(US만): 판정 동일(자기 시장 하락 = 전 시장 하락) → **동작 무변경**.
  - 범용형(KR+US): **둘 다 하락장일 때만** 차단. 한쪽만 하락이면 정상 매수(다른 시장 기회 유지 +
    하락 시장 종목도 개별 신호로 걸러짐).
- 기본 OFF(`bear_market_guard=False`) 불변. 매도·손절·쿨다운 영향 없음(기존과 동일).

## 2. 인터페이스

- `engine.evaluate_close(d, market, snaps, bearish_by_market: dict[Market, bool] | None = None)`
  — 기존 `market_bearish: bool` 파라미터를 **대체**. None(기본)이면 가드 미작동.
  가드 조건: `rules.bear_market_guard and bearish_by_market and all(bearish_by_market.get(m, False) for m in st.spec.markets)`
  (캐릭터별 판정이므로 `st` 루프 안에서 평가; 매수 후보 생성만 skip).
- `replay.run_replay`: 각 스텝에서 **두 시장 모두의** 하락장 플래그를 dict로 만들어 전달
  (`{Market.KR: _bearish(KR, ts), Market.US: _bearish(US, ts)}`). 지수 없으면 False(기존 폴백 유지).
- 라이브 orchestrator: 인자 미전달(None) → 무변경.

## 3. 하위 호환

- v1 `market_bearish`는 v1.5.0에서 도입된 지 하루 안 된 내부 파라미터로, 외부 사용자 없음 →
  **대체**(deprecated 유지 불필요). sp6 엔진 테스트 4건은 v2 의미로 갱신.
- 기본 None → 가드 off 시 완전 무변경.

## 4. 실험 (A/B v2)

- 동일 구간(2026-01-09~07-09)·유니버스: OFF vs **ON(v2)**. v1.5.0 기록의 v1 결과와 3자 비교
  (OFF / v1 / v2). 핵심: **범용형이 v1(−17.1%/−34.7%) 대비 개선**되고 OFF(−12.1%/−25.7%)에
  근접 또는 개선하는지. 해외형·국내형은 단일 시장이라 v1과 동일해야 함(회귀 확인 겸용).
- `docs/experiments/replay_bear_guard_ab_2026-01-09_2026-07-09.md`에 v2 결과 추가.

## 5. 문서·테스트

- trading-rules.md 하락장 가드 절을 v2 규칙으로 갱신.
- 테스트: 다중시장 캐릭터가 한쪽 시장만 하락 시 매수 허용 / 양쪽 하락 시 차단, 단일시장 동작
  불변, 기본 None 무변경. 리플레이 통합(지수 dict 전달).

## 6. 완료 기준

1. pytest 통과(갱신 포함). 2. A/B v2 실행·기록(3자 비교표). 3. trading-rules 갱신.
