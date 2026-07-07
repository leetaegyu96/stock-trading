# simcore — 규칙 기반 롱온리 모의투자 시뮬레이터 (엔진 코어)

청신호/적신호 카운트 규칙(매수 7 / 매도 3)으로 3캐릭터(국내형/해외형/범용형)가
각 1억 원으로 모의매매하는 엔진. 과거 데이터 리플레이로 검증한다.

## 설치
    py -m venv .venv
    .venv\Scripts\python -m pip install -e .[dev]

## 리플레이 실행
    .venv\Scripts\python -m simcore --start 2025-01-01 --end 2025-12-31
    # 옵션: --buy-threshold 5  --kr-top 50 --us-top 50  --flows flows.csv  --out out

입출금 CSV 형식: `date,character,amount_krw,liquidate` (liquidate 는 세미콜론 구분 종목코드, 출금 시 청산 지정)

## 테스트
    .venv\Scripts\python -m pytest

## 문서
- 매매 규칙(튜닝 기준): docs/trading-rules.md
- 설계 스펙: docs/superpowers/specs/2026-07-07-simcore-engine-design.md
- 실험 기록: docs/experiments/

## 주의
실제 매매가 아닌 페이퍼 트레이딩이며 투자 조언이 아닙니다.
