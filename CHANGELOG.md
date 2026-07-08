# Changelog

이 프로젝트의 모든 주요 변경사항을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/), 버전은 [SemVer](https://semver.org/)를 따른다.

상세 패치노트는 `docs/patch-notes/vX.Y.Z.md` 참조.

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
