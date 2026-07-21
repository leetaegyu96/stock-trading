# 워크포워드(롤링 아웃오브샘플) 검증 하니스 — 설계 스펙

> 2026-07-21. 리서치 채택안(`docs/research/2026-07-21-algo-trading-ventures.md` #1). 감사 로드맵
> 3단계(전략 검증, 실전 전 필수)의 첫 구현.

## 목적

전략 성과가 "한 번의 운 좋은 구간"이 아니라 여러 시간 구간에서 **일관**되는지 정직하게 보여준다.
전체 구간을 롤링 폴드로 나눠 각 test 구간을 **아웃오브샘플(OOS)로 독립 평가**하고, 폴드별 지표와
폴드 간 일관성(평균·표준편차·수익 폴드 비율)을 리포트한다.

## 정직한 범위 한정 (non-goals)

- 우리 엔진 파라미터는 `Config` 고정이며 **폴드별 재적합을 하지 않는다**. 따라서 이번 것은 엄밀히
  **롤링 OOS 평가**다. 폴드별 파라미터 최적화(진짜 WFO)·CPCV·과적합확률(PBO)·Deflated Sharpe는
  후속(이슈)으로 남긴다.
- 신호는 인과적(과거만 참조)이라 `evaluate_frame`을 전체 번들에 계산해도 lookahead가 없다. 각 폴드는
  번들 전체 히스토리를 워밍업으로 쓰되 시뮬레이션은 test 구간에서 **콜드스타트**(초기자금)로 시작한다.

## 아키텍처

기존 `simcore/replay.py::run_replay`와 `simcore/metrics.py::risk_metrics`를 **재사용**한다. 신규
의존성 없음.

### `simcore/walkforward.py` (신규)

- `Fold` (frozen dataclass): `index:int, test_start:date, test_end:date`.
- `generate_folds(start, end, test_days, step_days, warmup_days, trading_days=None) -> list[Fold]`
  - `start`~`end`를 `step_days` 간격으로 타일링해 각 폴드의 test 구간(`test_days` 길이)을 만든다.
  - 첫 test_start는 `start + warmup_days` 이상이어야 한다(지표 워밍업 확보; 일목 등 ~78 거래일 필요 →
    warmup_days 기본 120 캘린더일).
  - 마지막 폴드의 test_end는 `end`를 넘지 않게 자른다. test 구간이 최소 길이 미만이면 폴드 제외.
- `WalkForwardResult` (dataclass): `folds: list[dict]`, `aggregate: dict`.
  - 폴드 dict: `{index, test_start, test_end, per_char: {name: {twr, mdd, sharpe, win_rate, n_trades}}}`.
  - aggregate: `{per_char: {name: {mean_twr, std_twr, pct_profitable_folds, mean_sharpe, worst_mdd, n_folds}}}`.
- `run_walkforward(config, bundle, folds) -> WalkForwardResult`
  - 각 폴드: `res = run_replay(config, bundle, fold.test_start, fold.test_end)`.
  - 캐릭터별: `eq = res.equity[name]`; `rm = metrics.risk_metrics(eq, trades=res.trades[res.trades.character==name], flows=res.flows_by_char[name])`.
    - `twr = res.summary[name]["twr"]`, `mdd = res.summary[name]["mdd"]`, `sharpe = rm["sharpe"]`,
      `n_trades = res.summary[name]["n_trades"]`, `win_rate = rm["win_rate"]`(risk_metrics에 있으면; 없으면 trades에서 realized_pnl>0 비율 계산).
  - aggregate: 폴드 리스트에서 캐릭터별 twr 평균/표준편차, 수익(twr>0) 폴드 비율, sharpe 평균, 최악 mdd.
  - 폴드가 거래일 없음 등으로 `run_replay`가 `ValueError`면 그 폴드는 스킵(로그)하고 계속.

### CLI: `python -m simcore.walkforward`

- 인자: `--start --end --test-days(기본 63) --step-days(기본 63) --warmup-days(기본 120) --kr-top --us-top --cache --out`.
- 번들을 `[start, end]` 전체로 1회 로드(`__main__.py`의 로딩 패턴 재사용: load_kr_daily/load_us_daily/load_fx/load_index).
- `generate_folds` → `run_walkforward` → 콘솔에 폴드별·집계 표 출력 + `--out` 지정 시 마크다운 리포트 저장.

## 테스트 (`tests/test_walkforward.py`)

- `generate_folds`: 폴드 개수·경계(첫 test_start ≥ start+warmup, 마지막 test_end ≤ end)·step 간격·최소길이 미만 제외.
- 집계 수학: 합성 폴드 리스트로 mean_twr/std_twr/pct_profitable_folds 정확성.
- 통합: 소형 합성 번들(상승·하락 픽스처)로 2폴드 `run_walkforward` → 폴드별 per_char 지표 존재·aggregate n_folds==2·twr 유한값. (기존 test_replay 픽스처/헬퍼 재사용)
- 빈 구간 폴드 스킵(ValueError 방어).

## 문서

- `docs/trading-rules.md`에 워크포워드 검증 절 추가(롤링 OOS 정의·범위 한정·CLI 사용법).
- `docs/next-steps.md` 감사 3단계 항목에 walk-forward 착수/완료 반영.

## 회귀

- 순수 신규 모듈·CLI. 기존 코드 무변경 → 전체 pytest 무손상.
