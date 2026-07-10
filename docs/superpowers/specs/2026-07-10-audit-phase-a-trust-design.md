# 감사 Phase A — 신뢰 회복 (P0) 설계 스펙

- 날짜: 2026-07-10
- 상태: 사용자 승인(범위: Phase A 먼저 → v1.8.0 → 이후 Phase B)
- 요구사항 원본: `docs/reviews/2026-07-10-trading-product-audit.md` (§2 P0, §6 1단계). 본 스펙은 finding ID를 인용하며 리포트 문구를 복제하지 않는다. 리포트의 **완료 조건**이 곧 인수 기준.
- 상위: 감사 로드맵 1단계 "신뢰 회복". Phase B(P1 의사결정 화면)는 후속 서브프로젝트(v1.9.0).

## 목표

리포트 최종 판단의 3축 중 첫째 — **"설명과 실제 행동의 완전한 일치"** — 를 확보하고(P0-1), 신호의 실제 범위를 사용자에게 정직하게 알리며(P0-2), 절대수익률 대신 **위험조정·벤치마크 대비** 성과를 보여준다(P0-3). 운영 모드와 데이터 기준시각을 전 화면에 고정한다.

## 범위 밖 (명시)

- P1 의사결정 화면 전체 → Phase B(v1.9.0).
- 자동매매 안전장치·실주문·실전 게이트(리포트 "향후 실주문 P0 진입조건", 5단계) — 리포트가 "지금 실주문 기능 추가 금지" 명시.
- 심층 전략검증: point-in-time universe, corporate action, walk-forward/holdout, ablation, 비용 스트레스(3단계) — 데이터·연구 인프라 필요, 후속.
- 외부 정보축(공시·수급·뉴스·거시) 데이터 파이프라인(4단계).
- 신호 재설계(§3: ATR 손절·리스크 예산 사이징·업종상관 한도·KR우선처리 제거) — 별도 튜닝 서브프로젝트.
  단, P0-2가 요구하는 "외부 축 미수집 표시"와 KR우선처리의 **정직한 고지**는 포함(동작 변경은 아님).

## 1. P0-1 — 결정과 설명의 일치 (결정 이벤트 모델)

**문제(코드 확인):** `engine.evaluate_close`가 강제매도(R18 지지선 붕괴, R5+R23 급락복합)를 등급 매도와 동일하게 `TradeReason.SIGNAL_SELL`로 기록한다(engine.py:99-113). `signal_display.summarize`는 영속된 결정이 아니라 red_score만으로 문구를 재계산한다(signal_display.py:54) → R5+R23 score=8 강제 전량매도가 "주의 신호 (8점)"으로 표시된다.

**설계:**
- `models.py`에 `DecisionType(str, Enum)` 추가: `BUY`, `PARTIAL_SELL`, `FULL_SELL`, `FORCED_SELL`.
- `Trade`에 `decision_type: DecisionType`, `trigger_rule: str` 추가(키워드 생성 — 기존 realized_pnl/score 삽입 관행 유지). `PendingBuy`/`PendingSell`에 결정 시점 값 전달용 필드 추가.
- 엔진이 **결정 시점에** 유형·트리거를 확정:
  - 매수 → `BUY`, trigger_rule = 게이트 통과 근거(예: `"게이트+19점"`).
  - 등급 부분매도(9~10) → `PARTIAL_SELL`, trigger = 발화 적신호 코드.
  - 등급 전량매도(≥11) → `FULL_SELL`, trigger = 발화 적신호 코드.
  - 강제(R18 / R5+R23 / R7 종가갭 / 트레일링갭) → `FORCED_SELL`, trigger = 구체 원인(`"R18"`, `"R5+R23"`, `"R7"`, `"R10"`).
  - `check_stops` STOP_LOSS/TRAILING_STOP → `FORCED_SELL`, trigger `"R7"`/`"R10"`.
  - USER_WITHDRAWAL/DELISTED → 각각 유형 유지(표시는 사유 그대로).
- `signal_display`: `summarize`/`detail`이 **decision_type + trigger_rule을 우선 사용**해 실제 행동을 문구화. 매핑: FORCED_SELL+R5+R23 → "급락 복합조건 → 강제 전량매도", R18 → "지지선 붕괴 → 강제 전량매도", R7 → "잠금 손절선 도달 → 강제 전량매도", R10 → "최고가 대비 트레일링선 도달 → 강제 전량매도", PARTIAL_SELL → "부분 매도", FULL_SELL → "전량 매도(적신호 N점)", BUY → 기존 매수 문구. red_score 기반 재계산 경로 제거(점수는 부가 정보로만).
- 영속: `report.py`(리플레이 trades DataFrame), `replay.py`, 라이브 `db.py`(TradeRow에 컬럼)·`repository.persist`/`append_new_trades`, `dashboard queries`에 decision_type/trigger_rule 전파. db 스키마 신규 컬럼은 기존 관행(create_all 신규 시; `seed_from_replay --force` drop+recreate로 반영).
- 대시보드 `app.character_trades`: score 기반 summarize 호출을 decision_type/trigger 전달로 교체(app.py:174-178).
- **완료 조건(리포트):** 동일 거래의 사유·신호요약·실제 주문수량이 하나의 결정 유형으로 일관 설명. 회귀 테스트: `R5+R23 score=8 → FORCED_SELL` 표시 정합, R18/R7/R10 각 표시, 모든 강제 원인 파라미터화 전수.

## 2. P0-2 — 신호 범위의 정직한 고지

**설계(주로 표시·라벨, 동작 무변경):**
- 프론트 라벨: "청/적신호" → **"기술적 매수/매도 신호"**(green/red 배지·범례·상세 헤더). 백엔드 응답 문구도 필요 시 동반.
- 종목 판단/카드에 고지: **"뉴스·공시·수급은 현재 판단에 반영되지 않음"** 상시 표시.
- 미구현 외부 축(예 G8 긍정심리·G9 외인기관)은 **0점이 아니라 "미수집/판단 불가"**로 표기. `signal_display`가 스텁/미수집 코드를 별도 상태로 구분(현재 스텁은 항상 꺼짐 → "미수집" 상태값 신설).
- **완료 조건(리포트):** 한 종목 화면에서 어떤 데이터 축이 강세/약세/미확인인지 구분(축 라벨 수준). 근거 시각·출처 역추적은 6축 분리(4단계)에 속하므로 Phase A는 "기술적 축만 계산됨 + 나머지 미수집" 구분까지.

## 3. P0-3 — 벤치마크·위험조정 성과

**설계:**
- `metrics.py`에 위험조정 지표 추가(기존 equity/flows/trades로 계산 가능한 것만): CAGR, 연변동성, Sharpe, Sortino, Calmar(CAGR/|MDD|), Profit Factor, 평균이익/평균손실·손익비, 기대값/거래, 최대 연속손실 횟수, 최대낙폭 회복기간(일). 무위험수익률=0 가정 명시.
- 벤치마크: 리플레이/시드가 이미 KOSPI200/S&P500 지수를 로드 가능(`data.load_index`). 캐릭터 시장 기준 **전략 vs 벤치마크 초과수익(benchmark_delta)** 계산·영속. 범용형은 시장별 비중 가중 벤치마크.
- 대시보드: 성과 화면 **1순위를 전략 vs 벤치마크**로. `benchmark_delta`가 null이면 조용히 숨기지 말고 **경고 배지**("벤치마크 미수집").
- 성과값 꼬리표: 표본 기간, 거래 수, 비용 가정, 데이터 버전(간단한 버전 문자열). "검증됨" 라벨은 **쓰지 않는다**(3개 국면 통과 전 금지 — Phase A는 애초 그 라벨 미도입).
- MDD 표현: "최대 낙폭 17.30%"처럼 위험량 문구 병기. 자산곡선 선택구간 수익률은 "선택 기간 수익률"로 명시(전체 TWR과 혼동 방지) — 지표 설명 툴팁은 Phase B와 겹치므로 Phase A는 최소 라벨만.
- **완료 조건(리포트):** 사용자가 "얼마의 위험을 감수해 벤치마크보다 얼마나 나았는지" 판단 가능.

## 4. 운영 모드·데이터 기준시각 고정

- 전 화면 상단에 **운영 모드 배지**(현재 `REPLAY`/`PAPER` — 라이브 시세 조회 전용이므로 실주문 없음, 기본 PAPER 표기) 고정.
- **데이터 기준시각(as-of)**: "실시간"=WebSocket 연결이 아니라 각 시장 가격의 as-of·지연을 표기(§4 접근성, §5 코드 피드백). Phase A는 스냅샷 시각 표시까지(가격수집·조회 분리는 후속).

## 5. 아키텍처·단위

- 엔진 결정 로직과 표시(signal_display)의 경계를 명확히: 엔진은 결정을 **데이터로 영속**, 표시는 그 데이터를 **문구로 변환만**(재계산 금지). 이것이 P0-1 모순의 구조적 해소.
- 파일 영향: `models.py`(DecisionType, Trade/Pending 필드), `engine.py`(결정 시 유형·트리거), `portfolio.py`(Trade 생성), `signal_display.py`(결정 기반 문구), `report.py`·`replay.py`(집계), `live/db.py`·`live/repository.py`(영속), `dashboard/backend`(queries·app·summary), 프론트 `types.ts`·배지/라벨·테이블 문구.

## 6. 테스트

- 엔진: 모든 강제 원인(R18, R5+R23, R7, R10)과 등급(부분/전량)·매수가 올바른 decision_type/trigger로 기록되는지 파라미터화 전수.
- signal_display: `R5+R23 score=8 → "강제 전량매도"` 등 표시 정합(재계산 아님) 회귀.
- metrics: 위험조정 지표 각 수식 손계산 대조(Sharpe/Sortino/Calmar/Profit Factor/기대값/연속손실/회복기간), 엣지(무거래·전량손실).
- 벤치마크: delta 계산·null 경고 경로.
- 통합/라이브: 리플레이·시드·라이브 영속에 신규 컬럼 왕복, 대시보드 응답 정합. 기존 스위트 무회귀.

## 7. 완료 기준·릴리즈

1. pytest 전체 통과(신규 포함), 프론트 빌드+vitest 통과.
2. 세 P0의 리포트 완료 조건 충족(행동↔설명 일치 0 모순, 신호범위 고지, 벤치마크·위험지표 노출).
3. `seed_from_replay --force` 재시딩(신규 컬럼·벤치마크·지표 반영), 대시보드 스모크.
4. trading-rules/README 갱신(결정 유형·표시 규칙·지표 정의).
5. dev 병합 → **v1.8.0** 릴리즈 + 패치노트. 리포트 재검증은 Codex 재감사가 수행(완료 조건 재확인).
