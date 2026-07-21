# 장중 스캔 관측성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 장중 자동매매 스캔이 "돌고 있고, 종목별로 왜 샀/안 샀/팔았는지"를 대시보드에서 실시간으로 볼 수 있게 한다.

**Architecture:** 엔진이 장중에도 후보 평가(status/block_reason)를 `last_candidates`에 기록하고, 오케스트레이터가 매 스캔마다 (1) 의사결정판(`signal_status`)을 갱신하고 (2) 스캔 하트비트(`intraday_scan` 테이블)를 남긴다. 대시보드는 신규 `/api/scan-status`로 하트비트를 표시하고, 오해를 부르는 "실시간" 라벨을 정정한다.

**Tech Stack:** Python 3.14, SQLAlchemy(선언형 모델 + `create_all`), FastAPI, pytest+respx, React+TypeScript+Vitest.

## Global Constraints

- 커밋 신원: `leetaegyu96 <leetaegyu96@users.noreply.github.com>` (회사 이메일 금지). 커밋 메시지는 한국어 + 타입 접두어. 커밋 말미 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- TDD 필수: 실패 테스트 → 실패 확인 → 최소 구현 → 통과 → 커밋.
- **엔진 불변식**: 이 작업은 장중 매매의 *체결 결과(종목·수량·시점)*를 절대 바꾸지 않는다. 기록만 추가.
- 기존 `on_close`/리플레이/시딩 경로 동작 불변. 신규 테이블은 `create_all` 자동 생성(마이그레이션 없음).
- 사용자 표기: "청/적신호" 문구 규칙 등 기존 `format.ts` 컨벤션 유지. "실시간"이라는 단어로 연결상태를 표현하지 않는다.

---

### Task 1: 엔진 — evaluate_intraday가 후보 평가를 기록

**Files:**
- Modify: `simcore/engine.py` (`evaluate_intraday` 매수 루프, 335~374행 근처; 필요 시 사유 헬퍼 추가)
- Test: `tests/test_engine_intraday.py`

**Interfaces:**
- Consumes: `CandidateEval(symbol, market, green_score, red_score, buy_gate, status, block_reason)` (기존 dataclass), `self.last_candidates: dict[str, list[CandidateEval]]`.
- Produces: 장중 스캔 후 `engine.last_candidates[character]`에 이 시장 후보들이 채워짐(status ∈ {"매수","차단"}; block_reason ∈ {보유중, 쿨다운, 점수부족, 게이트미충족, 슬롯부족, 체결강도미달, 장중매수캡, 재매수쿨다운, 킬스위치, 현금부족, ""}).

- [ ] **Step 1: 실패 테스트 — 체결 결과 불변(golden)**. 기존 매수/매도가 나는 시나리오를 구성해 `evaluate_intraday` 실행 후 포지션·거래가 변경 전과 동일함을 단언(이미 있으면 재사용). 그리고 `engine.last_candidates`가 채워짐을 단언 → 현재는 비어 있어 실패.

- [ ] **Step 2: 실패 테스트 — 각 차단 사유 기록**. 종목별로 보유중/쿨다운/점수부족/게이트미충족/슬롯부족/체결강도미달/장중매수캡/재매수쿨다운/킬스위치/현금부족/매수 상황을 만들고 해당 `CandidateEval.block_reason`/`status`를 단언.

- [ ] **Step 3: 실패 확인**. `pytest tests/test_engine_intraday.py -k candidates -v` → FAIL.

- [ ] **Step 4: 구현**. `evaluate_intraday`에 `cands_eval: list[CandidateEval]` 누적. 매도 처리 후 매수 판정 지점마다 기록:
  - held/cooldown/점수부족/게이트미충족은 매수 후보군 구성 전에 각 스킵 사유로 기록.
  - 후보 루프에서 슬롯부족(break 시 남은 후보 전부)/체결강도미달/`_intraday_can_buy` 실패 사유(아래)/현금부족(`_buy`=False)/매수(`_buy`=True) 기록.
  - `_intraday_can_buy` 실패 사유 세분화: 헬퍼 `_intraday_buy_block(st, symbol, now, eq) -> str|None` 신설(현재 로직과 동일 순서·조건, 반환만 사유 문자열/None). `evaluate_intraday`는 이 헬퍼로 판정+사유를 동시에 얻는다(동작 불변).
  - 시장 단위 교체: `kept = [c for c in self.last_candidates.get(st.spec.name, []) if c.market != market]; self.last_candidates[st.spec.name] = kept + cands_eval`.

- [ ] **Step 5: 통과 확인**. `pytest tests/test_engine_intraday.py -v` → PASS. 전체 엔진 테스트도 통과.

- [ ] **Step 6: 커밋**. `feat: 장중 스캔이 종목별 후보 평가(사유)를 기록`.

---

### Task 2: 영속 — IntradayScanRow + repository

**Files:**
- Modify: `simcore/live/db.py` (신규 모델 `IntradayScanRow`)
- Modify: `simcore/live/repository.py` (`record_scan`, `scan_status`)
- Test: `tests/live/test_orchestrator.py` 또는 신규 `tests/live/test_scan_status_repo.py`

**Interfaces:**
- Produces:
  - `IntradayScanRow(market pk, ts:datetime, universe_size:int, evaluated:int, failed:int, gate_pass:int, buys:int, sells:int, scan_minutes:int)`.
  - `Repository.record_scan(market, ts, universe_size, evaluated, failed, gate_pass, buys, sells, scan_minutes, session=None)` — `mark_close`와 동일한 `s.merge` upsert(시장별 최신 1행).
  - `Repository.scan_status() -> list[dict]` — 전체 행을 dict 리스트로.

- [ ] **Step 1: 실패 테스트**. 새 세션/DB에서 `repo.record_scan("KR", ts, 60, 58, 2, 3, 1, 0, 10)` 후 `repo.scan_status()`가 해당 값을 반환. 같은 시장에 다시 `record_scan`하면 행이 **교체**(1행 유지)됨을 단언.

- [ ] **Step 2: 실패 확인**. `pytest tests/live/test_scan_status_repo.py -v` → FAIL(모델/메서드 없음).

- [ ] **Step 3: 구현**. `db.py`에 모델 추가(위 컬럼; `ts: Mapped[datetime] = mapped_column(DateTime)`). `repository.py`에 `record_scan`(`mark_close` 패턴), `scan_status`(`signal_status` 조회 패턴 참고, `s.expunge`/dict 변환).

- [ ] **Step 4: 통과 확인**. `pytest tests/live/test_scan_status_repo.py -v` → PASS.

- [ ] **Step 5: 커밋**. `feat: 장중 스캔 하트비트 저장(intraday_scan)`.

---

### Task 3: 오케스트레이터 — on_intraday가 판+하트비트를 쓴다

**Files:**
- Modify: `simcore/live/orchestrator.py` (`on_intraday`)
- Test: `tests/live/test_orchestrator.py`

**Interfaces:**
- Consumes: Task1(`last_candidates` 채워짐), Task2(`record_scan`), 기존 `_signal_status_rows`, `replace_signal_status`.
- Produces: `on_intraday` 실행 후 (a) `signal_status`가 이 시장의 후보/보유로 갱신, (b) `intraday_scan`에 하트비트 1행.

- [ ] **Step 1: 실패 테스트 — 판 갱신**. 가짜 kis/repo로 `on_intraday` 실행 후 `repo.signal_status(character)`에 kind=후보 행이 이번 스캔 스냅 기준으로 존재.

- [ ] **Step 2: 실패 테스트 — 하트비트(정상)**. `on_intraday` 후 `repo.scan_status()`에 universe_size/evaluated/failed/gate_pass/buys/sells가 기대값.

- [ ] **Step 3: 실패 테스트 — 전건 실패에도 하트비트**. 모든 `current_price`가 예외를 던지도록 stub → `on_intraday`가 조용히 return하지 않고 `scan_status()`에 evaluated=0, failed=universe_size 하트비트를 남김.

- [ ] **Step 4: 실패 확인**. `pytest tests/live/test_orchestrator.py -k "scan or heartbeat or signal_status" -v` → FAIL.

- [ ] **Step 5: 구현**. `on_intraday`:
  - 조회 루프에서 `attempted=len(universe)`, `failed` 카운트(current_price 예외 시 +1), `evaluated=len(snaps)`.
  - `evaluate_intraday` 전 캐릭터별 `len(trades)` 스냅, 후 delta로 buys(side=BUY)/sells(side=SELL) 집계.
  - `gate_pass = sum(1 for s in snaps.values() if s.buy_gate)`.
  - `if not snaps:` 조기 return **전에** 하트비트 기록(작은 트랜잭션 or 아래 락 트랜잭션 진입). 스냅 있으면 기존 락 트랜잭션 안에서 `replace_signal_status(self._signal_status_rows(d,m,snaps), session=s, market=market)` + `record_scan(..., session=s)`.
  - buys/sells 집계는 `evaluate_intraday` 직후(락 안, persist 전) 계산.

- [ ] **Step 6: 통과 확인**. `pytest tests/live/test_orchestrator.py -v` → PASS.

- [ ] **Step 7: 커밋**. `feat: 장중 스캔마다 의사결정판 갱신 + 하트비트 기록(전건 실패 포함)`.

---

### Task 4: 백엔드 API — /api/scan-status

**Files:**
- Modify: `dashboard/backend/queries.py` (`scan_status`)
- Modify: `dashboard/backend/schemas.py` (`ScanStatusOut`)
- Modify: `dashboard/backend/app.py` (`@app.get("/api/scan-status")`)
- Test: `tests/dashboard/test_api.py`

**Interfaces:**
- Consumes: `intraday_scan` 테이블(Task2).
- Produces: `GET /api/scan-status -> list[ScanStatusOut]` (market, ts, universe_size, evaluated, failed, gate_pass, buys, sells, scan_minutes).

- [ ] **Step 1: 실패 테스트**. 시드 DB에 intraday_scan 1행 삽입 후 `client.get("/api/scan-status")`가 200 + 해당 값.

- [ ] **Step 2: 실패 확인**. `pytest tests/dashboard/test_api.py -k scan_status -v` → FAIL(404/미정의).

- [ ] **Step 3: 구현**. `queries.scan_status(sf)`(Repository.scan_status 위임), `ScanStatusOut`(pydantic), `market_status` 엔드포인트 패턴대로 라우트 추가.

- [ ] **Step 4: 통과 확인**. `pytest tests/dashboard/test_api.py -v` → PASS.

- [ ] **Step 5: 커밋**. `feat: /api/scan-status (장중 스캔 하트비트 노출)`.

---

### Task 5: 프론트엔드 — 스캔 상태 스트립 + 실시간 라벨 정정

**Files:**
- Modify: `dashboard/frontend/src/types.ts` (`ScanStatus`)
- Modify: `dashboard/frontend/src/api.ts` (`getScanStatus`)
- Create: `dashboard/frontend/src/components/ScanStatusStrip.tsx` (+ `.test.tsx`)
- Modify: `dashboard/frontend/src/pages/Main.tsx` (스트립 배치 + "실시간" 라벨 정정)
- Modify: `dashboard/frontend/src/components/ModeBar.tsx` (+ `ModeBar.test.tsx`) — "실시간 연결"→"연결됨"
- Test: Vitest

**Interfaces:**
- Consumes: `GET /api/scan-status`(Task4).
- Produces: 화면에 "장중 스캔 · KR 13:43 (60종목·게이트통과 3·매수 0/매도 0·실패 0) · 다음 ~10분" / 기록 없으면 "장중 스캔 대기 중". 연결 라벨은 "연결됨/오프라인".

- [ ] **Step 1: 실패 테스트(ScanStatusStrip)**. 데이터 있는 경우 종목수·게이트통과·매수/매도가 렌더되고, 빈 배열이면 "대기 중" 문구가 렌더됨을 단언.

- [ ] **Step 2: 실패 테스트(라벨)**. `ModeBar.test.tsx`를 "연결됨" 기대로 갱신(현재 "실시간 연결" 기대라 실패). `Main`의 카드 갱신 시각 라벨이 "실시간"이 아님을 확인.

- [ ] **Step 3: 실패 확인**. `npm test`(vitest) → FAIL.

- [ ] **Step 4: 구현**. `ScanStatus` 타입, `getScanStatus()`(`getMarketStatus` 패턴), `ScanStatusStrip` 컴포넌트(asOf 변경 시 재조회, 실패 시 마지막 값 유지), `Main.tsx`에 스트립 배치 + 상단 배지 텍스트 "실시간"→"연결됨"/`· 카드 갱신 ${formatTime}`, `ModeBar.tsx` "실시간 연결"→"연결됨".

- [ ] **Step 5: 통과 확인**. `npm test` → PASS. `npm run build`(타입체크) 통과.

- [ ] **Step 6: 커밋**. `feat: 장중 스캔 상태 스트립 + '실시간' 라벨 정정`.

---

### Task 6: 통합 검증 + 릴리즈

- [ ] **Step 1**: `pytest -q` 전체 통과(회귀 0).
- [ ] **Step 2**: 프론트 `npm test` + `npm run build` 통과.
- [ ] **Step 3**: PR `feature/intraday-scan-observability` → dev, 머지, 브랜치 삭제.
- [ ] **Step 4**: 릴리즈 판단(MINOR: 기능 추가 → v1.15.0) — dev→main 승격, CHANGELOG + `docs/patch-notes/v1.15.0.md`, 태그.

## Self-Review

- **Spec coverage**: G1(하트비트)=Task2/3/4/5, G2(판 장중 갱신)=Task1/3/(4·5 표시), G3(라벨)=Task5. 전건 실패 하트비트=Task3 Step3. 모두 커버.
- **Placeholder scan**: 없음(각 스텝에 대상 파일·조건·명령 명시).
- **Type consistency**: `record_scan`/`scan_status`/`ScanStatusOut`/`ScanStatus`/`getScanStatus` 이름·필드 일치. block_reason 집합 Task1↔spec 일치.
