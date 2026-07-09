# Changelog

이 프로젝트의 모든 주요 변경사항을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/), 버전은 [SemVer](https://semver.org/)를 따른다.

상세 패치노트는 `docs/patch-notes/vX.Y.Z.md` 참조.

## v1.6.0 — 2026-07-09

하락장 가드 v2 — 범용형 과발동 해소. 판정을 "캐릭터의 모든 시장이 하락장일 때만 차단"으로 변경(단일시장 캐릭터 동작 동일, 범용형은 양시장 동시 하락 시만). 기본 OFF 불변.

### Changed
- `evaluate_close(bearish_by_market dict)` 캐릭터별 all() 판정, 리플레이 양시장 dict 전달, trading-rules v2 규칙.

### 검증 (3자 A/B)
- 범용형 TWR −12.92%(v1 −17.10/OFF −12.10)·MDD −24.05%(3안 중 최고). 국내형/해외형 v1과 동일(회귀 없음). pytest 201.

## v1.5.0 — 2026-07-09

서브프로젝트 6: 시장지수 추세 필터(하락장 가드) — opt-in 전략 튜닝. 기본 OFF, 기존 동작 무변경.

### Added
- 하락장 가드(`bear_market_guard`, 기본 False): 지수(코스피200/S&P500) 20일선 아래면 해당 시장 신규매수 차단(보유·매도·손절 유지). `--bear-guard`로 활성.
- `data.load_index`(KR 1028 + yfinance ^KS200 폴백/US ^GSPC), `DataBundle` 지수 필드, `run_replay` 시장별 하락장 판정, `market_trend_period=20`.

### Fixed
- `load_index` KRX 자격증명 부재 시 크래시 → ^KS200 폴백. 지수 로드를 `--bear-guard` 시로 한정.

### 검증 (6개월 A/B)
- 해외형 개선(TWR +16→+27·MDD -11→-6.5), 국내형 중립, 범용형 악화(-12→-17) — 정직히 기록, 기본 OFF opt-in. pytest 198, 최종 리뷰(opus) 통과.

## v1.4.0 — 2026-07-09

서브프로젝트 5: 대시보드 UI 개편 + 데이터 리셋 (초보 친화 일일 현황판). 순수 엔진 무변경.

### Added
- 종목명 표시(`simcore/names.py`, 코드→한글/회사명, 폴백), 초보 친화 신호 표시(`simcore/signal_display.py`, 한글명·별점·등급·한 줄 요약).
- 일일 현황판 메인(시장 movers·캐릭터 요약·최근 체결), `/api/dashboard`.
- `seed_from_replay.py`(6개월 리플레이 → DB 리셋, `--force` 시 스키마 재생성), `ReplayResult` 최종 상태 노출, `FALLBACK_FX_RATE` 공유 상수.

### Changed
- "simcore/모의투자" 브랜드 텍스트 제거. 거래/보유 응답에 name·score·signal_summary/detail. 상세는 종목명 + 한 줄 요약·펼침(이름·별점).

### Fixed
- 범용형 총자산 불일치 해소(카드 총자산 = 자산곡선 마지막값 정확 일치, 재시딩 검증). USD 보유 캐릭터 "오늘 %" 환율 베이스 왜곡 교정(곡선 비율 스케일링). 시드 fx를 대시보드 고정 환율로 통일.

### 검증
- pytest 190 + 프론트 vitest 46 통과. 데이터 리셋 실행 + 스모크. 최종 전체리뷰(opus) READY TO MERGE.

## v1.3.0 — 2026-07-09

서브프로젝트 4: 신호 시스템 v2 (점수제·다중 게이팅·트레일링 스탑). 순수 엔진 계층 재설계. 목표는 손실 최소화.

### Added
- 신규 지표: ATR·ADX/DI·OBV·VWAP·Parabolic SAR·일목균형표.
- 점수제 신호(계산형 청 17·적 17 구현, 차트패턴/피보/뉴스/수급은 스텁), 카테고리 상한(추세10/돌파·하락패턴10/거래량8/모멘텀8/변동성6).
- 매수 다중 게이팅(총점 ≥ 18 AND 돌파+거래량+추세 각 1개), 매도 등급(9~10 부분 50%·11+ 전량)+강제매도(−7%·지지선·R5+R23), 트레일링 스탑(고정 익절 대체).
- CLI `--buy-score`, 워밍업 패딩 180, `TradeReason.TRAILING_STOP`.

### Changed
- 스냅샷/거래/포지션에 점수·게이트·트레일링 상태 필드. 라이브 영속에 점수·트레일링·부분매도 플래그 저장·복원(기존 DB 리셋 필요). trading-rules.md v2 재작성.

### Fixed (리뷰가 발견)
- 부분매도 전량청산 시 쿨다운 누락, 포지션 트레일링 상태 DB 미영속(라이브 재시작 손절바닥 소실), 재시작 대기주문 위치인자 오프셋, 신호 분포 리포트 라벨.

### 검증
- pytest 172 통과. 6개월 리플레이(2026-01-09~07-09): 국내형 +38.9%/해외형 +16.1%/범용형 −12.1%, 매수 270건 전부 총점≥18. 서브에이전트 구동 + 최종 전체리뷰(opus) 통과.

## v1.2.1 — 2026-07-09

대시보드 UI 전문가급 개편 (프론트엔드 전용, 백엔드·엔진 무변경).

### Changed
- 디자인 토큰 재정비: dataviz 검증 통과 상승=빨강/하락=파랑 팔레트(라이트·다크), 등폭 숫자·타이포·공용 컨트롤, 앱 셸/상단바(실시간 연결 표시).
- 리치 캐릭터 카드: 총자산 히어로 + 오늘 등락 칩 + 영역 스파크라인.
- 자산곡선 차트 전면 개편: Y축 눈금(억/만)·수평 그리드·기간 시작 기준선·X축 날짜·크로스헤어+툴팁·기간 토글(1M/3M/6M/전체), ResizeObserver 실측 폭.
- 보유종목/거래내역 테이블: 우측정렬 등폭 숫자, 시장 통화 인지(₩/$), KR/US 태그, 신호 배지, 사유 한글 라벨(손절/익절).
- 성과지표 스트립, 아바타 표정 다듬기.

### Added
- `format.ts` 포맷터(compact/signed/price/reason) + 테스트(vitest 42).
- `dashboard/scripts/seed_demo.py` — 화면 점검용 데모 데이터 시드(--force 가드).

### 검증
- 프론트 빌드 + vitest 42 통과, Python 137 통과(백엔드 무변경). uvicorn 스모크·전 화면 렌더 확인.

## v1.2.0 — 2026-07-08

서브프로젝트 3: 대시보드 (FastAPI + React + WebSocket). 순수 엔진·라이브 계층은 무변경·재사용.

### Added
- `dashboard/backend/` — FastAPI: 조회 REST(캐릭터 카드/상세/자산곡선/보유종목/거래내역/입출금), WebSocket 실시간 브로드캐스트(Postgres 폴링, 데몬과 디커플), 입출금 예약 엔드포인트, React 정적 빌드 서빙(SPA 폴백). `simcore.metrics`/repository/kis_client 재사용, KIS 현재가는 `DbTokenStore` 공유 캐시.
- `dashboard/frontend/` — Vite + React + TS: 하이브리드 UX(리치 캐릭터 카드 → 상세), **성과연동 표정 캐릭터 아바타**(커스텀 SVG, 국내형/해외형/범용형 정체성), 자산곡선 차트·보유종목/거래내역 테이블·성과지표·입출금 모달, WebSocket 실시간 갱신. 상승=빨강/하락=파랑, 라이트/다크.
- 신규 의존성: fastapi, uvicorn (백엔드); Vite/React/react-router-dom (프론트).

### Fixed (리뷰가 발견)
- DB 세션팩토리 싱글턴화 — 요청/폴링마다 새 엔진(QueuePool) 생성하던 연결 누수 방지.
- CardSummary 캐릭터 식별 필드(name/base_currency/markets) 누락 보강.
- 자산곡선 일단위 정규화 — equity(datetime) vs flow(date) 정합으로 TWR 왜곡 방지.

### 검증
- 137 테스트 통과(기존 96 + 라이브/대시보드). 최종 전체 브랜치 리뷰(백엔드↔프론트 계약·보안·제약) 통과.

## v1.1.0 — 2026-07-08

서브프로젝트 2: 라이브 모드 (KIS 실시세 + 스케줄러 + PostgreSQL 영속). 순수 엔진은 무변경.

### Added
- `simcore/live/` — 라이브 계층: `kis_client`(KIS REST·토큰캐시), `calendar`(KR/US 거래일·DST), `db`(SQLAlchemy ORM 13테이블), `repository`(상태 persist/rehydrate·이력·단일 트랜잭션), `orchestrator`(마감/개장/5분틱/입출금), `recovery`(갭 리플레이), `scheduler`(APScheduler), `__main__`(데몬+CLI).
- KIS 데이터 피드 전용(주문 없음), KR 유니버스=KIS 시총 상위, DB=PostgreSQL.
- 재시작 복구(rehydrate + 갭 리플레이), `run_state` 멱등, 라이브≡리플레이 동치성 테스트.
- CLI: `python -m simcore.live run | deposit | withdraw`.
- 신규 의존성: httpx, SQLAlchemy, psycopg, APScheduler, pydantic-settings.

### Fixed (구현 중 리뷰가 발견)
- 재시작 후 거래 유실(`append_new_trades` DB count → 세션 커서).
- cross-market stale 평가(범용형 반대시장 leg 원가 평가 → `_last_price` 캐시).
- 마감 사이클 비원자적 저장(크래시 시 쿨다운 이중차감 → 단일 트랜잭션).

### Changed
- `.env.example` 신규 변수(DATABASE_URL/TEST_DATABASE_URL, KIS_ENV=real), README 라이브 모드 사용법.

## v1.0.0 — 2026-07-08

첫 릴리즈. simcore 백테스트/리플레이 엔진 기준선 확정 + 프로젝트 작업 규칙 정립.

### Added
- `CLAUDE.md` — git 워크플로 규칙 (논리 단위 커밋 / 브랜치 개발 / SemVer 버전업 / PR 자율 처리 / 버전마다 패치노트).
- `.gitattributes` — 전 텍스트 파일 LF 강제 (WSL/Windows CRLF 노이즈 방지).
- `CHANGELOG.md` + `docs/patch-notes/` — 버전별 변경 이력 체계.

### Changed
- 개인 GitHub 신원으로 커밋 히스토리 정규화 (`leetaegyu96 <…noreply.github.com>`), 회사 이메일 제거.

### Baseline (v1.0.0 시점 구성 요소)
- `simcore/` — 백테스트/리플레이 엔진: config, data, indicators, signals, engine, portfolio, costs, metrics, report, universe, replay.
- `tests/` — 단위/통합 테스트.
- `docs/` — 트레이딩 규칙, 실험 기록, 설계 계획.
