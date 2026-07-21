# 이슈 #31 — 설명가능 신호 강화(신뢰도) 설계

> 2026-07-21. 리서치 finding #1. 규칙기반 신호에 정직하게 적용 가능한 부분만.

## 정직성 판단 (범위 결정)

- 우리 신호는 **규칙기반**(green/red 코드 배점)이라 ML 특성기여도(SHAP/LIME)는 부적용.
- 전략은 **고정 익절 타깃이 없다**(트레일링 스톱 기반). 따라서 "타깃수익 r*"을 지어내지 않는다 —
  프로젝트의 정직 라벨링 원칙에 어긋남.
- **손절 임계값은 이미 노출**됨: 진입 손절(stop_loss_pct −7%), 보유 종목 stop_px·stop_distance_pct
  (감사 Phase B positions). 새로 만들 필요 없음.
- 따라서 #31의 실제 추가 가치 = **신뢰도(confidence): 신호 강도를 [0,1]로 정규화해 표시**.

## 구현 (read 경로만 — 엔진·스키마·매매행동 무변경)

- `signals.py`(또는 소유틸)에 순수 헬퍼 `signal_confidence(score: int, scores: SignalScores, side="green") -> float`:
  - `MAX = sum(caps[cat] for cat in {카테고리 of side 코드들})` (green: 추세10+돌파10+거래량8+모멘텀8+변동성6=42; red: 추세10+하락패턴10+거래량8+모멘텀8+변동성6=42 — config caps에서 동적 계산, 하드코딩 금지).
  - `confidence = round(min(1.0, max(0.0, score / MAX)), 2)`.
  - 단위 테스트: score=0→0.0, score=MAX→1.0, score=buy_score_min(18)→~0.43.
- **대시보드 read 시점 계산**(저장 green_score/red_score에서): `dashboard/backend`의 `CandidateOut`에
  `confidence: float` 추가(candidates()가 저장된 green_score로 계산). positions의 보유 종목엔
  `red_confidence`(current_red_score 기반) 선택 추가. **신규 DB 컬럼 없음** — 순수 파생.
- **프론트**: CandidatesTable에 신뢰도 열(퍼센트 또는 막대). 색상 단독 금지(수치 병기).

## 비목표

- 엔진/매매 판정 변경 없음(confidence는 표시 전용, 매수/매도 결정에 영향 안 줌).
- 고정 익절 타깃 없음(트레일링 스톱 설명은 문서로).
- signal_status DB 스키마 변경 없음.

## 테스트

- `signal_confidence` 단위(경계값·동적 MAX).
- 백엔드: CandidateOut.confidence가 저장 green_score와 일치(기존 candidates 테스트 확장).
- 프론트 vitest: 후보 행 신뢰도 렌더.

## 문서

- trading-rules.md 신호 절에 신뢰도 정의(정규화·타깃 미제공 사유). #31 반영.
