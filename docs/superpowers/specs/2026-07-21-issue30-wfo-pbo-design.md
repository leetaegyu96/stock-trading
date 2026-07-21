# 이슈 #30 — 진짜 워크포워드 최적화(WFO) + 과적합확률(PBO) 설계

> 2026-07-21. v1.12.0 롤링 OOS 검증(`simcore/walkforward.py`)의 심화. 페이퍼 시뮬 규모에 맞춘 핵심 범위.

## 목적

롤링 OOS 평가를 **진짜 워크포워드 최적화**로 확장한다: 각 폴드의 **학습(train) 구간에서 파라미터를
그리드 최적화**하고 **테스트(test) 구간에서 그 파라미터를 OOS 평가**한다. 그리고 **과적합확률(PBO,
López de Prado CSCV)**을 계산해 "인샘플 최적이 아웃오브샘플에서 얼마나 자주 중앙값 이하로 추락하는가"를
정량화한다.

## 범위 한정 (non-goals — 후속)

- 완전 CPCV(≥100 조합 경로·purge/embargo 튜닝)와 Deflated/Probabilistic Sharpe(DSR/PSR)는 이번 범위
  밖(무거움). PBO는 CSCV의 경량판(폴드 이분 조합)으로 구현. 후속 이슈로 명시.
- 최적화 대상 파라미터는 **`buy_score_min` 단일 축**(그리드 예: [12,14,16,18,20])으로 시작. 다축은 후속.

## 아키텍처 (기존 확장, 신규 의존성 0)

`simcore/walkforward.py`에 추가. `run_replay`·`risk_metrics` 재사용.

- `Fold`에 `train_start`/`train_end` 추가(또는 신규 `OptFold`): test 구간 직전의 train 구간
  (train_days, 기본 252 캘린더일). generate_folds가 train+test 쌍 생성(롤링).
- `run_wfo(config, bundle, folds, grid, objective="twr", character="국내형") -> WfoResult`:
  - 각 폴드: grid의 각 값으로 config 복제(`dataclasses.replace(cfg.rules, buy_score_min=v)`) → train 구간 run_replay → objective(캐릭터 twr 또는 sharpe) 기록(IS 성과 행렬). IS 최적 파라미터 선택.
  - 선택된 파라미터로 test 구간 run_replay → OOS 성과. 폴드별 {train/test 구간, is_best_param, is_perf, oos_perf} 수집.
  - WFO 효율 = mean(oos_perf)/mean(is_best_perf) 등 IS→OOS 열화 리포트.
- `probability_of_backtest_overfitting(is_matrix, oos_matrix) -> float`:
  - CSCV 경량: 폴드들을 두 그룹(in/out)으로 나누는 조합마다, in-group에서 최적인 config가 out-group에서
    차지하는 상대순위 ω의 로짓 λ=logit(ω)를 모으고, **PBO = P(λ ≤ 0)** = OOS 중앙값 이하로 떨어지는 비율.
  - 입력: config(그리드값)×폴드 성과 행렬 2개(IS/OOS) 또는 단일 성과 행렬을 조합 분할. 조합 수가 크면
    상한(예: C(N, N/2) 최대 200 샘플)으로 캡하고 캡 시 log.
- `WfoResult` dataclass: `folds: list[dict]`, `wfo_efficiency: float`, `pbo: float`, `grid`, `objective`.
- CLI 확장(또는 신규 `--wfo` 플래그): 번들 로드→generate_folds(train+test)→run_wfo→폴드별 선택 파라미터·IS/OOS·PBO 표 출력, `--out` 마크다운.

## 정직성

- 결과가 "PBO 높음(과적합 위험)"이면 그대로 보고한다 — 좋은 숫자를 위해 그리드·목적함수를 조작하지 않는다.
- 우리 엔진은 대부분 파라미터가 고정이라 최적화 축이 좁다(단일). 이는 WFO의 탐색공간이 작다는 뜻이며
  리포트에 명시.

## 테스트 (`tests/test_walkforward.py` 확장 또는 신규)

- generate_folds(train+test): train_start<test_start, train_end≤test_start, 경계.
- `probability_of_backtest_overfitting`: 합성 행렬로 알려진 PBO(예: IS최적이 항상 OOS 최악=PBO 1.0, IS·OOS 완전일치=PBO 0.0) 검증.
- `run_wfo` 통합: 소형 합성 번들·2폴드·그리드 2값 → 폴드별 is_best_param 선택·oos_perf 유한·pbo∈[0,1].

## 문서

- trading-rules.md 워크포워드 절에 WFO·PBO 추가. next-steps 갱신. CPCV/DSR 후속 이슈 등록.

## 회귀

- 기존 `run_walkforward`·`generate_folds` 시그니처는 **유지**(하위호환) — WFO는 신규 함수로 추가. 전체 pytest 무손상.
