# v2 구현 계획

SPEC.md 를 3갈래로 쪼개 병렬 개발한다. **경계는 파일 단위**라 서로 충돌하지 않는다.

## 이미 완료 (기반 — 공유 계약)

| 파일 | 내용 |
|---|---|
| `v2/backend/settings.py` | env 설정. v1 과 DB·포트·KIS 토큰 분리 |
| `v2/backend/money.py` | 정수 최소단위 금액 + 수수료/세금/환전 |
| `v2/backend/models.py` | ORM 9테이블 (SPEC §2.2) |
| `v2/backend/db.py` | 엔진·세션·트랜잭션 |
| DB | `simcore_v2` / `simcore_v2_test` 생성, 스키마 반영 |
| nginx | `/stock-v1/`·`/stock-v2/` 서브패스, 구 URL 301 |

## 병렬 작업

### A — 인증 (`auth.py`, `routers/auth.py`, `tests/test_auth.py`)
argon2id 해시, JWT httpOnly 쿠키, 가입 시 캐릭터 2개 원자적 생성, 레이트 리밋,
소유권 검증 의존성(`require_account`) — **B 가 이 의존성을 쓴다**.

### B — 시세·매매 (`market.py`, `trading.py`, `sellwall.py`, `scheduler.py`, `routers/*.py`)
KIS 시세 캐시, 종목 리스트, 매수/수동매도(회계 불변식·계정 행 잠금),
매도벽 판정·자동매도, 장중 1분 감시 잡.

### C — 프론트 (`v2/frontend/**`)
React+Vite. v1 디자인 토큰 재사용. 7화면 + vitest.
API 는 SPEC §7 계약대로 호출하며, 백엔드 없이도 개발되도록 계약 기반 목을 둔다.

## 통합 (내가 직접)
`app.py` 조립 → E2E 시나리오 테스트 → systemd `stock-v2.service` → 빌드·배포 → 검증.

## goal
가입 → 캐릭터 2개(각 1억) → 매수 → 매도벽 설정 → 자동매도 발동 → 기록 확인이
**공개 URL 에서 실제로** 동작하고, 백엔드·프론트 테스트가 전부 통과.
