# simcore — 규칙 기반 롱온리 모의투자 시뮬레이터 (엔진 코어)

청신호/적신호 점수제(매수 18점+게이트 / 매도 등급·트레일링 스탑)으로 3캐릭터(국내형/해외형/범용형)가
각 1억 원으로 모의매매하는 엔진. 과거 데이터 리플레이로 검증한다.

## 설치
    py -m venv .venv
    .venv\Scripts\python -m pip install -e .[dev]

## 리플레이 실행
    .venv\Scripts\python -m simcore --start 2025-01-01 --end 2025-12-31
    # 옵션: --buy-score 16  --kr-top 50 --us-top 50  --flows flows.csv  --out out
    #      --bear-guard (하락장 가드 전 캐릭터 강제 on, 기본은 config bear_guard_characters=전체 off)
    #      --no-bear-guard (하락장 가드 전체 강제 off)

입출금 CSV 형식: `date,character,amount_krw,liquidate` (liquidate 는 세미콜론 구분 종목코드, 출금 시 청산 지정)

## 라이브 모드 (KIS 실시세)

KIS 실시세로 스케줄러가 엔진을 실시간 구동하고 상태·거래내역을 PostgreSQL에 영속한다.
KIS는 **데이터 피드 전용**(주문하지 않음)이며 3캐릭터는 엔진이 자체 시뮬레이션한다.

    # 1) PostgreSQL 준비 후 .env 채우기 (KIS 키·DATABASE_URL — .env.example 참고)
    # 2) 데몬 시작
    py -m simcore.live run
    # 3) 입출금 예약 (다음 개장에 반영)
    py -m simcore.live deposit 국내형 5000000
    py -m simcore.live withdraw 해외형 3000000 --liquidate AAPL

- KIS `access_token` 은 앱키/시크릿으로 자동 발급·캐시된다(직접 입력 불필요).
- 재시작 시 DB에서 상태를 복원하고, 꺼져 있던 거래일은 확정 일봉으로 재생(갭 리플레이)해 따라잡는다.
- 라이브와 리플레이는 동일한 엔진 코드 경로를 타며, 동치성 테스트로 보증한다.

설계: `docs/superpowers/specs/2026-07-08-simcore-live-kis-design.md`

## 대시보드

한 번에 켜고 끄기 (프론트 빌드 + 백엔드를 uvicorn 하나로 서빙):

    ./dashboard/dashboard.sh start     # 빌드 + 기동 → http://localhost:8000
    ./dashboard/dashboard.sh stop      # 종료
    ./dashboard/dashboard.sh status    # 실행 여부 / logs 로 로그 보기
    # 포트 변경: PORT=9000 ./dashboard/dashboard.sh start

수동으로 하려면:

    cd dashboard/frontend && npm install && npm run build
    uvicorn dashboard.backend.app:app        # http://localhost:8000

라이브 데몬(`simcore.live run`)과 동일한 PostgreSQL(`DATABASE_URL`)을 읽어, 3캐릭터 카드·상세(차트·표·지표)·입출금 예약을 REST + WebSocket으로 제공한다.
프론트 빌드(`dist/`)가 있으면 백엔드가 SPA를 그대로 서빙하며, KIS 실시세를 종가에 병합해 카드/차트에 반영한다.

거래내역은 엔진이 결정 시점에 확정한 결정 유형(매수/부분매도/전량매도/강제매도, `docs/trading-rules.md` §13)을
그대로 문구로 보여주고, 위험조정 지표·벤치마크 초과수익(§14)과 상단 **PAPER 모드 배지**(모의투자·실주문 없음 고지)를
항상 함께 노출한다. 벤치마크가 미수집이면 조용히 숨기지 않고 경고로 표시한다.

대시보드 DB를 6개월 리플레이 결과로 초기화(리셋)하려면(⚠️ `DATABASE_URL`의 기존 거래·자산·포지션을 전부 지움):

    python dashboard/scripts/seed_from_replay.py --force
    # 옵션: --start/--end (기본 최근 6개월) --kr-top 50 --us-top 50 --cache data/cache

## 테스트
    .venv\Scripts\python -m pytest

## 문서
- 매매 규칙(튜닝 기준): docs/trading-rules.md
- 설계 스펙: docs/superpowers/specs/2026-07-07-simcore-engine-design.md
- 실험 기록: docs/experiments/

## 주의
실제 매매가 아닌 페이퍼 트레이딩이며 투자 조언이 아닙니다.
