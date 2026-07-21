# 이슈 #27 — 신규 지표(괴리율·지지저항) 배점 배선 설계

> 2026-07-21. `disparity`/`support_resistance`(v1.11.0에서 라이브러리로만 추가)를 신호 체계에 편입.

## 목적

두 지표를 evaluate_frame의 신호 코드로 배선하고 SignalScores 배점에 편입해, 실제 매수/매도 판정에
반영한다. 매매 행동이 바뀌므로 워크포워드(#29)로 before/after를 측정한다.

## 배선 (예약 스텁 코드 사용)

기존 스텁 중 G8·G9·R20을 실제 신호로 전환(나머지 G19·G21·G24·R22는 스텁 유지):
- **G9 = 저항 돌파**: `(close.shift(1) <= res.shift(1)) & (close > res)`, res=support_resistance의 저항. 카테고리 **돌파**, 5점. (지지 이탈 R18은 이미 존재하므로 저항 돌파가 신규 가치)
- **G8 = 괴리율 과매도 반등**: `(disp.shift(1) <= oversold) & (disp > oversold)` — 이동평균 대비 크게 눌렸다가 회복. 카테고리 **모멘텀**, 3점.
- **R20 = 괴리율 과열 확장**: `disp >= overbought` — 이동평균 대비 과도하게 상승(주의). 카테고리 **변동성**, 4점.
- disp = `ind.disparity(close, p.disparity_period)`, (sup,res) = `ind.support_resistance(high, low, close, p.sr_lookback)`.

**buy_gate 미포함** — 게이트 필수 조건으로 만들지 않는다(과도한 진입 제약 방지). 점수 기여만.

## config (SignalParams 신규 필드)

- `disparity_period: int = 20`, `disparity_oversold: float = -0.10`, `disparity_overbought: float = 0.15`, `sr_lookback: int = 20`.

## 회귀 원칙 (중요)

- 신호 출력이 바뀌면 결과-고정 테스트(리플레이 거래수·seed_demo 등)가 흔들릴 수 있다. **동치성 테스트(live≡replay)는 양쪽이 같은 엔진이라 계속 통과**해야 한다.
- 결과-고정 테스트가 깨지면 **blind 재작성 금지** — 어떤 테스트가 어떻게(기대 vs 실제) 바뀌었는지 보고하고, 새 동작이 타당한지 컨트롤러가 판단 후 기대값 갱신.
- 스텁 단언 테스트(test_stub_columns_always_false, test_new_columns_present_and_stubs_false)는 G8/G9/R20 제거하도록 갱신 + G8/G9/R20 발화 양성 테스트 추가.

## 검증

- 단위: 각 코드가 구성된 데이터에서 정확히 발화, score/snapshot_scores에 반영.
- 영향 측정(컨트롤러): 캐시 데이터로 배선 전/후 리플레이 비교(거래수·TWR·MDD delta) + 워크포워드. 명백히 악화면 점수 하향 또는 문서화.

## 문서

- trading-rules.md 신호 코드 표에 G8·G9·R20 추가. #27 반영.
