# simcore 대시보드 (FastAPI + React) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라이브 모드가 PostgreSQL에 쌓는 3캐릭터 데이터를 하이브리드 대시보드(리치 캐릭터 카드→상세)로 보여준다. FastAPI 백엔드(REST+WebSocket) + React/Vite 프론트, 로컬 단일 서빙. 성과연동 표정 캐릭터 아바타.

**Architecture:** 순수 엔진(`simcore/`)·라이브 계층(`simcore/live/`)은 무변경·재사용. 신규 `dashboard/backend`(FastAPI, Postgres 읽기 + flow_requests INSERT + WS 폴링 푸시)와 `dashboard/frontend`(Vite React TS). FastAPI가 React 정적 빌드도 서빙.

**Tech Stack:** FastAPI, uvicorn, SQLAlchemy/psycopg(기존), simcore.metrics/repository/kis_client 재사용; Vite + React + TypeScript, 경량 차트, 커스텀 SVG 아바타.

## Global Constraints

- Python `>=3.11`. **순수 엔진(`simcore/engine.py` 등)·라이브 계층(`simcore/live/*`)은 수정 금지.** 재사용만. 기존 96 테스트 그대로 통과.
- 대시보드는 Postgres **읽기 전용 + `flow_requests` INSERT만**. 매매/상태 변경은 라이브 데몬 소관.
- KIS 현재가는 `simcore.live.kis_client` + `DbTokenStore`(공유 `kis_token` 캐시) 사용 — 별도 토큰 발급 금지(1분1회 제한 회피).
- 상승=빨강, 하락=파랑(한국 관례). 라이트/다크 지원.
- 신규 코드: 백엔드 `dashboard/backend/`, 프론트 `dashboard/frontend/`. 백엔드 테스트 `tests/dashboard/`.
- DB 테스트는 `TEST_DATABASE_URL` 있을 때만 실행(없으면 skip). 커밋은 CLAUDE.md dev 워크플로.
- 설계 단일 기준: `docs/superpowers/specs/2026-07-08-simcore-dashboard-design.md`.

## 파일 구조

```
dashboard/
├── backend/
│   ├── __init__.py
│   ├── app.py            # FastAPI: REST + WS + 정적 서빙
│   ├── db.py             # 세션 팩토리(설정에서 DATABASE_URL)
│   ├── queries.py        # Postgres 조회
│   ├── summary.py        # 카드/상세 집계 + 메트릭
│   ├── live_prices.py    # KIS 현재가(+daily_bars 폴백)
│   ├── flows.py          # 입출금 예약
│   ├── schemas.py        # pydantic 응답 모델
│   └── broadcaster.py    # WS 연결관리 + 폴링 루프
└── frontend/
    ├── package.json, vite.config.ts, tsconfig.json, index.html
    └── src/
        ├── api.ts, ws.ts, types.ts
        ├── App.tsx, main.tsx
        ├── theme.css
        ├── pages/{Main,Detail}.tsx
        └── components/{Avatar,CharacterCard,Sparkline,EquityChart,
                        PositionsTable,TradesTable,MetricsPanel,FlowModal}.tsx
tests/dashboard/
├── __init__.py, conftest.py (테스트 DB + 시드 헬퍼)
├── test_queries.py, test_summary.py, test_api.py, test_flows.py,
│   test_live_prices.py, test_ws.py
```

---

### Task 1: 백엔드 의존성 + FastAPI 스켈레톤 + 헬스체크

**Files:** Modify `pyproject.toml`; Create `dashboard/__init__.py`, `dashboard/backend/__init__.py`, `dashboard/backend/db.py`, `dashboard/backend/app.py`, `tests/dashboard/__init__.py`, `tests/dashboard/conftest.py`, `tests/dashboard/test_api.py`.

**Interfaces:**
- Produces: `app` (FastAPI). `GET /api/health -> {"status":"ok"}`. `dashboard.backend.db.session_factory()` (uses `LiveSettings.database_url`).

- [ ] **Step 1: 의존성 추가** — `pyproject.toml` dependencies에 `fastapi>=0.110`, `uvicorn[standard]>=0.29`; dev에 `httpx>=0.27`(TestClient용, 이미 있음). (참고: Task 실행 환경엔 이미 설치돼 있을 수 있음 — 없으면 `pip install`.)

- [ ] **Step 2: 실패 테스트** — `tests/dashboard/test_api.py`:
```python
from fastapi.testclient import TestClient
from dashboard.backend.app import app

def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
```

- [ ] **Step 3: 실패 확인** — `python -m pytest tests/dashboard/test_api.py -v` → ModuleNotFoundError.

- [ ] **Step 4: 구현** — `dashboard/backend/db.py`:
```python
from simcore.live.settings import load_settings
from simcore.live import db as livedb

def session_factory():
    s = load_settings()
    return livedb.make_session_factory(livedb.make_engine(s.database_url))
```
`dashboard/backend/app.py`:
```python
from fastapi import FastAPI

app = FastAPI(title="simcore dashboard")

@app.get("/api/health")
def health():
    return {"status": "ok"}
```
`tests/dashboard/conftest.py` — 라이브 테스트 conftest와 동일 패턴(TEST_DATABASE_URL 가드 + 세션 픽스처, `simcore.live.db.create_all` 사용).

- [ ] **Step 5: 통과 확인** — `python -m pytest tests/dashboard/test_api.py -v` → PASS. 전체 `python -m pytest -q` 회귀 없음.

- [ ] **Step 6: 커밋** — `feat(dashboard): FastAPI 스켈레톤 + 헬스체크`.

---

### Task 2: queries.py — Postgres 조회

**Files:** Create `dashboard/backend/queries.py`, `tests/dashboard/test_queries.py`.

**Interfaces:**
- Consumes: `simcore.live.db` ORM, 세션 팩토리.
- Produces (모두 `session_factory` 인자):
  - `list_characters(sf) -> list[dict]` (name, base_currency)
  - `positions(sf, name) -> list[dict]` (symbol, market, quantity, avg_price, opened_date)
  - `trades(sf, name, limit=200) -> list[dict]`
  - `flows(sf, name) -> list[dict]`
  - `equity_series(sf, name) -> list[tuple[datetime, float]]`
  - `cash(sf, name) -> dict[str, float]`

- [ ] **Step 1: 실패 테스트** — `tests/dashboard/test_queries.py`: 시드(캐릭터/포지션/거래/자산/현금 몇 행 INSERT via ORM) 후 각 조회가 올바른 행을 반환하는지. 예:
```python
from tests.dashboard.conftest import needs_db
from dashboard.backend import queries as q
# ... 시드 후
@needs_db
def test_positions_roundtrip(session, sf):
    # seed a position for 국내형
    ...
    rows = q.positions(sf, "국내형")
    assert rows[0]["symbol"] == "005930" and rows[0]["quantity"] == 10
```
(conftest에 `sf` 픽스처 = 테스트 DB 세션팩토리 제공.)

- [ ] **Step 2: 실패 확인** — 모듈 없음.
- [ ] **Step 3: 구현** — `queries.py`에 위 함수들(SQLAlchemy select, dict 매핑). ORM: `db.PositionRow`, `db.TradeRow`, `db.CapitalFlowRow`, `db.EquityPoint`, `db.CashBalance`, `db.CharacterRow`.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests/dashboard/test_queries.py -v` PASS(실 Postgres).
- [ ] **Step 5: 커밋** — `feat(dashboard): Postgres 조회 queries`.

---

### Task 3: summary.py — 집계 + 메트릭

**Files:** Create `dashboard/backend/summary.py`, `dashboard/backend/schemas.py`, `tests/dashboard/test_summary.py`.

**Interfaces:**
- Consumes: `queries`, `simcore.metrics`(time_weighted_return/max_drawdown/simple_pnl_krw), `simcore.models.Currency`.
- Produces:
  - `card_summary(sf, name, fx_rate, last_prices) -> CardSummary` — total_asset_krw, twr, pnl_krw, today_pnl_pct, equity_spark(최근30), n_positions, cash_krw.
  - `detail_metrics(sf, name) -> Metrics` — twr, mdd, n_trades, win_rate, pnl_krw.
  - `schemas.py`: pydantic `CardSummary`, `Metrics`, `PositionOut`, `TradeOut`, `FlowOut`, `EquityPoint`.
- Note: TWR/MDD는 `equity_series`(pd.Series)와 flows(pd.Series)로 계산 — replay의 metrics 호출과 동일.

- [ ] **Step 1: 실패 테스트** — 고정 equity_curve + flows 시드로 `card_summary`/`detail_metrics`가 손계산값과 일치(특히 TWR·win_rate). 예: 거래 5건 중 3건 이익 → win_rate 0.6.
- [ ] **Step 2: 실패 확인** — 모듈 없음.
- [ ] **Step 3: 구현** — pandas Series로 변환 후 `simcore.metrics` 호출. today_pnl_pct = 최근 2 equity point 비교. win_rate = realized_pnl>0 매도 / 전체 매도.
- [ ] **Step 4: 통과 확인** — PASS.
- [ ] **Step 5: 커밋** — `feat(dashboard): 카드/상세 집계 + 메트릭(summary)`.

---

### Task 4: REST 엔드포인트 (조회)

**Files:** Modify `dashboard/backend/app.py`; Create/extend `tests/dashboard/test_api.py`.

**Interfaces:**
- Produces: `GET /api/characters`, `/api/characters/{name}`, `/equity`, `/positions`, `/trades`, `/flows` — schemas 반환. 세션팩토리는 FastAPI dependency로 주입(테스트에서 오버라이드 가능).
- Consumes: queries, summary.

- [ ] **Step 1: 실패 테스트** — TestClient로 시드된 테스트 DB(dependency override로 sf 주입) 대상 각 엔드포인트 200 + 스키마 필드 검증. `/api/characters` 3캐릭터 반환.
- [ ] **Step 2: 실패 확인** — 404(엔드포인트 없음).
- [ ] **Step 3: 구현** — 엔드포인트들. `app.dependency_overrides`로 sf 주입 가능하게 `get_sf()` dependency. fx_rate/last_prices는 이 태스크에선 최근 종가(daily_bars 최신) 또는 avg_price 폴백으로 계산(라이브 KIS는 Task 5에서 병합).
- [ ] **Step 4: 통과 확인** — PASS.
- [ ] **Step 5: 커밋** — `feat(dashboard): 조회 REST 엔드포인트`.

---

### Task 5: live_prices.py — KIS 현재가 병합

**Files:** Create `dashboard/backend/live_prices.py`, `tests/dashboard/test_live_prices.py`; Modify positions 엔드포인트.

**Interfaces:**
- Produces: `current_prices(kis, symbols_by_market, repo) -> dict[str,float]` — KIS 현재가, 실패 시 `repo.load_daily_bars` 마지막 종가 폴백. `stale` 여부 표시.
- Consumes: `simcore.live.kis_client`, `repository`. 테스트는 Fake kis.

- [ ] **Step 1: 실패 테스트** — Fake kis가 일부 심볼 성공/일부 예외 → 성공분은 현재가, 실패분은 daily_bars 폴백가 반환. (repo는 테스트 DB, daily_bars 시드.)
- [ ] **Step 2~4: 구현·통과** — positions 엔드포인트에 현재가·평가액·손익% 병합. 폴백 시 `stale=true`.
- [ ] **Step 5: 커밋** — `feat(dashboard): KIS 현재가 병합 + 폴백`.

---

### Task 6: 입출금 엔드포인트

**Files:** Create `dashboard/backend/flows.py`; Modify `app.py`; Create `tests/dashboard/test_flows.py`.

**Interfaces:**
- Produces: `POST /api/characters/{name}/deposit {amount_krw}` / `withdraw {amount_krw, liquidate:[]}` → `repository.enqueue_flow`(입금 +, 출금 −) 후 `{queued:true, request_id}`. 금액 ≤0/알수없는 캐릭터 → 400.

- [ ] **Step 1: 실패 테스트** — deposit POST 후 `flow_requests`에 +금액 pending 1건; withdraw는 −금액 + liquidate. 잘못된 금액 400. (TestClient + 테스트 DB.)
- [ ] **Step 2~4: 구현·통과** — `repository.enqueue_flow` 재사용. 캐릭터명 검증(DEFAULT_CHARACTERS).
- [ ] **Step 5: 커밋** — `feat(dashboard): 입출금 예약 엔드포인트`.

---

### Task 7: broadcaster.py + WebSocket

**Files:** Create `dashboard/backend/broadcaster.py`; Modify `app.py`; Create `tests/dashboard/test_ws.py`.

**Interfaces:**
- Produces: `class Broadcaster` — 연결 관리(add/remove), `snapshot(sf,...)` 생성, `poll_once()`(직전 대비 diff 시 push). `WS /ws` — 접속 시 초기 스냅샷 1회 전송 후 push 수신. 폴링 루프는 `app` startup에서 백그라운드 태스크(주기 설정값), 테스트에선 `poll_once` 직접 호출.
- Consumes: summary(card_summary), queries.

- [ ] **Step 1: 실패 테스트** — `with TestClient(app).websocket_connect("/ws") as ws:` 초기 메시지 `type=="cards"` + 3캐릭터. `broadcaster.poll_once()` 호출 후 데이터 변경 시 추가 push 수신(또는 diff 없음 시 무푸시). 연결 관리 단위 테스트(add/remove).
- [ ] **Step 2~4: 구현·통과** — `ConnectionManager`(list[WebSocket]), 예외 시 개별 제거. 초기 스냅샷은 `/api/characters`와 동일 데이터. 폴링은 이전 스냅샷 캐시와 비교.
- [ ] **Step 5: 커밋** — `feat(dashboard): WebSocket 실시간 브로드캐스트`.

---

### Task 8: React 정적 빌드 서빙 + SPA 폴백

**Files:** Modify `dashboard/backend/app.py`; `tests/dashboard/test_api.py`(정적 마운트 스모크).

**Interfaces:**
- Produces: `dashboard/frontend/dist` 존재 시 `/`·자산 서빙 + SPA 폴백(알 수 없는 비-API 경로 → index.html). dist 없으면 `/`가 안내 메시지(개발 편의).

- [ ] **Step 1: 실패 테스트** — dist 목(임시 index.html) 생성 후 `GET /` 200 + html; `GET /api/health` 여전히 JSON. (없을 때 안내 200.)
- [ ] **Step 2~4: 구현·통과** — `StaticFiles` 마운트 + catch-all 라우트(‘/api’ 제외). 
- [ ] **Step 5: 커밋** — `feat(dashboard): React 빌드 정적 서빙 + SPA 폴백`.

---

### Task 9: 프론트엔드 스캐폴딩 (Vite React TS) + API 클라이언트

**Files:** Create `dashboard/frontend/*` (package.json, vite.config.ts, tsconfig.json, index.html, src/main.tsx, src/App.tsx, src/api.ts, src/ws.ts, src/types.ts).

**Interfaces:**
- Produces: 빌드되는 Vite React TS 앱. `api.ts`(fetch 래퍼: getCharacters/getDetail/getEquity/getPositions/getTrades/postDeposit/postWithdraw), `ws.ts`(자동재연결 WebSocket 훅), `types.ts`(스키마 타입).
- vite.config: `build.outDir` 기본 `dist`, dev proxy `/api`·`/ws` → `localhost:8000`.

- [ ] **Step 1: Node 확인** — `node -v && npm -v` (v24 존재 가정; 없으면 BLOCKED 보고).
- [ ] **Step 2: 스캐폴딩** — 위 파일 생성. (React+TS 최소 구성. 차트/아바타는 이후 태스크.)
- [ ] **Step 3: 의존성 설치 + 빌드 검증** — `cd dashboard/frontend && npm install && npm run build` 성공(‘dist’ 생성). (테스트 대체: 빌드 성공이 게이트.)
- [ ] **Step 4: 커밋** — `feat(dashboard): 프론트 스캐폴딩 + API/WS 클라이언트`.

---

### Task 10: Avatar + CharacterCard 컴포넌트

**Files:** Create `dashboard/frontend/src/components/Avatar.tsx`, `CharacterCard.tsx`, `Sparkline.tsx`, `theme.css`; (선택) vitest 설정 + 스모크 테스트.

**Interfaces:**
- Produces:
  - `Avatar({character, mood})` — 커스텀 인라인 SVG 얼굴. `mood` = `happy|smile|neutral|down` (성과에서 매핑). 캐릭터별 색/소품(국내형/해외형/범용형).
  - `moodFromPnl(todayPct) -> mood` (순수 함수, 테스트 대상): `>1.5% happy, >0 smile, ==0 neutral, <0 down` 등.
  - `CharacterCard({summary})` — 스펙 §6 리치 카드(아바타·TWR·총자산·오늘·스파크라인·보유/현금·벤치). 상승 빨강/하락 파랑.
  - `Sparkline({points})` — 경량 SVG.

- [ ] **Step 1: 순수함수 테스트** — vitest로 `moodFromPnl` 경계값 검증(+2→happy, +0.5→smile, 0→neutral, −1→down).
- [ ] **Step 2: 실패 확인 → 구현** — Avatar(SVG variants), moodFromPnl, CharacterCard, Sparkline.
- [ ] **Step 3: 빌드/테스트 통과** — `npm run build` + `npm run test`(vitest) 성공.
- [ ] **Step 4: 커밋** — `feat(dashboard): 성과연동 표정 아바타 + 리치 카드`.

---

### Task 11: 메인 페이지 (카드 3개 + 로딩/빈상태)

**Files:** Create `dashboard/frontend/src/pages/Main.tsx`; Modify `App.tsx`(라우팅).

**Interfaces:**
- Produces: `/` 에서 `getCharacters()`로 3카드 렌더, WS로 실시간 갱신, 카드 클릭 → `/character/{name}`. 로딩/빈상태/에러 UI.

- [ ] **Step 1~3: 구현 + 빌드** — 카드 그리드, WS 훅 연결(cards 메시지로 상태 갱신), 상단 합계·마지막 갱신 시각. `npm run build` 성공.
- [ ] **Step 4: 커밋** — `feat(dashboard): 메인 페이지(카드+실시간)`.

---

### Task 12: 상세 페이지 (차트·표·지표)

**Files:** Create `EquityChart.tsx`, `PositionsTable.tsx`, `TradesTable.tsx`, `MetricsPanel.tsx`, `pages/Detail.tsx`.

**Interfaces:**
- Produces: `/character/{name}` — 자산곡선 차트(자산/TWR + 벤치 오버레이, 기간 토글), 보유종목 테이블(실시간가·손익%, 상승빨강/하락파랑), 거래내역(사유·청/적신호 배지·손익), 성과지표 패널. WS로 보유종목 갱신.

- [ ] **Step 1~3: 구현 + 빌드** — 경량 라인차트(SVG 또는 소형 라이브러리). 신호 배지(G/R 코드). `npm run build` 성공.
- [ ] **Step 4: 커밋** — `feat(dashboard): 상세 페이지(차트·표·지표)`.

---

### Task 13: 입출금 모달 (FlowModal)

**Files:** Create `FlowModal.tsx`; Modify `Detail.tsx`(헤더 버튼).

**Interfaces:**
- Produces: 입금/출금 모달. 금액 입력, 출금 시 보유종목 중 청산 선택. 제출 → `postDeposit/postWithdraw` → "다음 개장 반영" 토스트. 검증(양수).

- [ ] **Step 1~3: 구현 + 빌드** — 폼 검증, 성공/실패 처리. `npm run build` 성공.
- [ ] **Step 4: 커밋** — `feat(dashboard): 입출금 모달`.

---

### Task 14: 통합 실행 검증 + 문서

**Files:** Modify `README.md`; (선택) `dashboard/README.md`; 실행 스모크.

- [ ] **Step 1: 프론트 빌드** — `cd dashboard/frontend && npm run build` → `dist` 생성.
- [ ] **Step 2: 백엔드 기동 스모크** — `uvicorn dashboard.backend.app:app` 기동(백그라운드) 후 `curl localhost:8000/api/health` 200, `curl localhost:8000/` html(빌드된 SPA), `/api/characters` JSON 확인 후 종료. (실 데이터가 없으면 빈 배열/빈상태.)
- [ ] **Step 3: 전체 회귀** — `python -m pytest -q` (기존 96 + 신규 대시보드 백엔드 테스트 green).
- [ ] **Step 4: README** — "대시보드" 섹션 추가:
```
## 대시보드
    cd dashboard/frontend && npm install && npm run build
    uvicorn dashboard.backend.app:app        # http://localhost:8000
```
- [ ] **Step 5: 커밋** — `docs(dashboard): README 실행법` + 문서.

---

## 릴리즈

전 태스크 dev 병합 후, 완료 시 `dev`→`main` 승격 + `v1.2.0` 태그 + 패치노트(CHANGELOG + docs/patch-notes/v1.2.0.md). (CLAUDE.md §4·§7)

## 완료 기준 대조 (스펙 §10)

1. uvicorn 기동 → 메인/상세 표시 → Task 8·9·11·12·14.
2. REST 정확·백엔드 테스트 → Task 2~6.
3. WebSocket 실시간 갱신 → Task 7·11·12.
4. 입출금 예약 → Task 6·13.
5. 기존 96 + 신규 green → Task 14 Step 3.
6. README → Task 14.
