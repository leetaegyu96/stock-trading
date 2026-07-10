# 하락장 가드 튜닝 (캐릭터별 스위치 + 시장별 MA 기간) — 설계 스펙

- 날짜: 2026-07-10
- 상태: 사용자 승인 — gv2(v1.6.0) 후속 튜닝
- 상위: 가드 v2 A/B에서 범용형 과발동은 해소됐으나, 가드 ON 시 국내형 TWR이
  OFF 대비 −8.5%p(+38.88→+30.38) 손해. 해외형은 개선(+16→+27, MDD −11→−6.5).
  → 캐릭터별로 가드 적용 여부와 시장별 MA 기간을 최적화해 config 기본값으로 채택한다.

## 1. 목표·채택 규칙

- 캐릭터별 최적 조합(가드 on/off + 시장별 MA 기간)을 6개월 스윕으로 찾는다.
- **채택 규칙(캐릭터별)**: `TWR ≥ OFF−1.0%p` 이면서 `MDD 개선(|MDD| 감소)`인 설정 중
  → |MDD| 최소, 동률 시 TWR 최대. 후보가 없으면 그 캐릭터는 가드 off.
- **시장별 기간 충돌 해소**: 기간은 시장 단위 공유값이므로, 단일시장 캐릭터
  (국내형=KR, 해외형=US)의 최적 기간을 먼저 확정하고, 범용형은 그 고정 기간 하에서
  on/off만 판단한다. (범용형은 양시장 동시 하락 조건이라 발동 빈도가 낮아 기간 민감도 낮음)
- **12개월 검증**(2025-07-10~2026-07-09): 채택 조합 vs OFF 재실행.
  `MDD 개선 방향 유지 AND TWR ≥ OFF−3.0%p`인 캐릭터만 기본값 확정, 실패 캐릭터는 off 강등.

## 2. Config 변경

- `SignalParams.market_trend_period: int = 20` → **대체**:
  `market_trend_period_kr: int` / `market_trend_period_us: int` (평면 필드, 기존 스타일).
  기본값은 스윕 결과로 확정(구현 단계에서는 둘 다 20).
- `TradeRules.bear_market_guard: bool = False` → **대체**:
  `bear_guard_characters: frozenset[str] = frozenset()` — 가드를 적용할 캐릭터 이름 집합.
  빈 집합 = 전체 off. 구현 단계 기본값은 빈 집합(현행 동작 보존),
  스윕·검증 후 **마지막 태스크에서 최적 조합을 기본값으로 갱신**.

## 3. 엔진·판정 공용화

- `engine.evaluate_close` 가드 조건:
  `st.spec.name in rules.bear_guard_characters and bearish_by_market and all(bearish_by_market.get(m, False) for m in st.spec.markets)`.
- 리플레이의 `_bearish`(지수 close asof < SMA asof, NaN/지수없음→False)를 공용 헬퍼로 추출:
  `data.bearish_by_market(indices: dict[Market, Series|None], periods: dict[Market, int], ts) -> dict[Market, bool]`
  — 리플레이·라이브가 동일 판정식 사용. (SMA는 호출측에서 매번 rolling하지 않도록
  헬퍼가 Series 단위로 사전계산 가능한 형태로 설계해도 무방 — 구현 재량, 판정 의미만 고정)
- `replay.run_replay`: 시장별 기간(`market_trend_period_kr/us`)으로 SMA 계산(기존 로직의 dict화).

## 4. 라이브 배선 (orchestrator)

- `on_close`에서 `evaluate_close` 호출 전, **가드 대상 캐릭터가 있을 때만**
  양 시장 지수를 로드(`data.load_index`, 캐시 재사용)해 bearish dict를 계산·전달.
  지수 로드 실패/데이터 없음 → 해당 시장 False(리플레이와 동일한 안전 폴백, 로그만 남김).
- `bear_guard_characters`가 빈 집합이면 지수 로드 자체를 스킵(불필요 네트워크 회피 —
  기존 `__main__` 게이팅 관행과 동일).

## 5. CLI

- 기본: config의 `bear_guard_characters` 사용.
- `--bear-guard` = 전 캐릭터 강제 on / `--no-bear-guard` = 전체 강제 off (상호 배타).
- 지수 로드는 유효 집합이 비어있지 않을 때만.

## 6. 실험 (스윕 + 검증)

- `simcore/sweep.py`(커밋, `python -m simcore.sweep` — 패키지 모듈 CLI 관행): `run_replay` 인프로세스 반복.
  - 그리드: KR×US 기간 **{20, 40, 60, 120}² = 16회**(전 캐릭터 가드 on) + OFF 기준 1회.
    데이터 로드·캐시는 1회 재사용.
  - 출력: 캐릭터별 TWR·MDD·거래수 markdown 표 + 채택 규칙 자동 적용 결과.
- 기록: `docs/experiments/bear_guard_tuning_sweep_2026-01-09_2026-07-09.md`
  (선정 근거 포함, 나쁜 결과도 정직히 기록).
- 12개월 검증 2회(OFF vs 채택 조합) → §1 검증 기준으로 확정.

## 7. 하위 호환·파손 예상

- `bear_market_guard`·`market_trend_period`는 내부 파라미터(외부 사용자 없음) → 대체, deprecated 불필요.
- 파손 예상: sp6/gv2 엔진·리플레이 테스트의 `bear_market_guard=True` 사용처 → frozenset 방식 갱신,
  trading-rules.md §6-1 갱신.

## 8. 문서·테스트

- 신규 테스트: config 필드 존재/기본값, 캐릭터별 게이팅(집합 포함만 차단·미포함 통과),
  시장별 기간 독립 적용(KR≠US 기간 시 각자 SMA), 공용 헬퍼 단위(NaN·지수없음 폴백),
  CLI 플래그 매핑(on/off/기본).
- trading-rules.md §6-1: 캐릭터별 적용·시장별 기간으로 갱신(최종 기본값 반영).
- README 가드 절 갱신.

## 9. 릴리즈·완료 기준

1. pytest 전체 통과(갱신 포함).
2. 스윕 16+1회 실행·기록 + 12개월 검증 2회 → 기본값 확정.
3. trading-rules/README 갱신, config↔문서 일치.
4. `seed_from_replay --force` 재시딩(기본값 변경 반영, 대시보드 데이터 갱신).
5. dev 병합 → **v1.7.0** 릴리즈(MINOR) + 패치노트.
