# 감사 Phase B — 의사결정 화면 (P1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 첫 화면을 "오늘의 의사결정판"으로 재구성 — 오늘의 후보/차단 사유, 보유 리스크(손절·잠재손실), 거래 생애 복기, 지표 맥락을 사용자가 바로 읽게 한다 (감사 §4 P1 5건, 로드맵 2단계).

**Architecture:** 엔진에 **관찰 전용** 후보 평가 기록을 추가(결정 로직 무변경 — 같은 입력이면 같은 거래)하고, 마감 시점 상태를 `SignalStatusRow`로 영속(리플레이 마지막 날 시드 + 라이브 on_close). 대시보드는 저장된 상태만 읽는다(요청 경로 무거운 계산·네트워크 금지, Phase A 관행). 거래 생애는 서버측 그룹핑.

**Tech Stack:** Python 3.11(pandas·SQLAlchemy·pytest), FastAPI, React+TS(Vite·vitest, SSR renderToStaticMarkup 테스트 — jsdom 없음).

**스펙:** `docs/superpowers/specs/2026-07-10-audit-phase-b-decision-ui-design.md`
**요구사항 원본:** `docs/reviews/2026-07-10-trading-product-audit.md` §4·§6 2단계
**브랜치:** `feature/audit-phase-b-decision-ui` (dev 6c7403e에서 분기)

## Global Constraints

- **관찰≠행동**: 후보 기록 훅은 매매 결과를 절대 바꾸지 않는다. 회귀 증거 = 기존 엔진·리플레이·동치성 테스트 전부 무수정 통과.
- block_reason 값(정확히): `"점수부족"`, `"게이트미충족"`, `"보유중"`, `"쿨다운"`, `"슬롯부족"`, `"현금부족"`, `"가격없음"`. 예약된 후보는 status `"예약"`, 차단은 `"차단"`.
- 요청 경로에서 evaluate_frame/지수 로드 등 무거운 계산·네트워크 금지 — 저장된 SignalStatusRow만 읽는다.
- 업종·실적일 컬럼 금지(데이터 없음 — 빈 컬럼을 만들지 않는다). "업종 집중" 대신 "종목 집중(최대 보유 비중)"으로 정직하게 라벨.
- 캐릭터 이름 정확히 국내형/해외형/범용형. 커밋 한국어+타입 접두어.
- 기준: dev에서 pytest 250 passed, 프론트 vitest 75. 프론트 검증: `cd dashboard/frontend && npm run build && npx vitest run`.
- 스키마 신설은 create_all/`--force` 재시딩 관행.

---

### Task 1: 엔진 후보 평가 기록 (관찰 전용)

**Files:** Modify `simcore/engine.py`, `simcore/models.py` / Test `tests/test_engine_orders.py`

**Interfaces — Produces:**
- `models.CandidateEval` frozen dataclass: `symbol: str, market: Market, green_score: int, red_score: int, buy_gate: bool, status: str("예약"|"차단"), block_reason: str("" when 예약)`.
- `engine.evaluate_close(...)` 기존 시그니처 유지 + **새 메서드** `Engine.last_candidates: dict[str, list[CandidateEval]]` (캐릭터명→해당 마감의 후보 평가; evaluate_close 호출 시 그 시장 분만 갱신·다른 시장 분 유지).
- `fill_open`이 체결 단계 차단(슬롯부족/현금부족/가격없음)을 같은 구조에 **status 갱신**으로 반영(예약이었다가 체결 안 된 사유).

- [ ] evaluate_close의 매수 후보 루프에서: 게이트/점수/보유/쿨다운 각 continue 지점에 CandidateEval("차단", 사유) 기록, 통과 시 ("예약",""). 기존 pending_buys 로직 무변경.
- [ ] fill_open에서: 슬롯 소진 break·가격 None·현금부족(qty<=0) 시 해당 후보의 last_candidates 항목을 status "차단"+사유로 갱신(체결되면 "예약" 유지 — 체결 여부는 trades로 확인 가능).
- [ ] 테스트(TDD): 사유별 파라미터화(점수부족/게이트/보유중/쿨다운/슬롯부족/현금부족), 예약 케이스, **동작 불변 회귀**(후보 기록 추가 전후 trades 동일함은 기존 전체 테스트 무수정 통과로 증명 — 이 태스크에서 기존 테스트를 고치지 말 것).
- [ ] Commit: `feat: 엔진 매수후보 평가 기록(관찰 전용, 차단사유 포함)`

### Task 2: SignalStatusRow 영속 + 보유 상태

**Files:** Modify `simcore/live/db.py`, `simcore/live/repository.py`, `simcore/replay.py` / Test `tests/live/test_repository.py`, `tests/test_replay_integration.py`

**Interfaces — Produces:**
- `db.SignalStatusRow`: id PK, `date: Date`, `character: str`, `symbol: str`, `kind: str("후보"|"보유")`, `green_score int`, `red_score int`, `buy_gate bool`, `status str`, `block_reason str`, `stop_px float|None`, `trail_px float|None`, `close float|None`.
- `repository.replace_signal_status(rows: list[dict], session=...)` — 전량 교체(최신 마감만 유지) + `signal_status(sf, character) -> list[dict]` 읽기.
- `ReplayResult.signal_status: list[dict]` — 리플레이 **마지막 거래일**의 후보(engine.last_candidates)+보유 상태(보유 종목별 red_score·stop_px=avg_price*(1+locked_stop_pct)·trail 관련·close).

- [ ] db 모델 + repository 교체/읽기(왕복 테스트).
- [ ] replay 말미: 마지막 ts의 snaps·positions에서 후보/보유 dict 목록 구성해 ReplayResult에 노출(테스트: 상승 픽스처에서 보유 상태 row 존재+stop_px 계산 정확).
- [ ] Commit: `feat: SignalStatusRow 영속(후보·보유 마감 상태)`

### Task 3: 시드·라이브 기록

**Files:** Modify `dashboard/scripts/seed_from_replay.py`, `simcore/live/orchestrator.py` / Test `tests/dashboard/test_seed_from_replay.py`, `tests/live/test_orchestrator.py`

- [ ] seed가 `result.signal_status`를 replace_signal_status로 적재(테스트: 시드 후 rows 존재).
- [ ] orchestrator.on_close 트랜잭션에 그 시장 후보+보유 상태 기록(engine.last_candidates + positions; 테스트: on_close 후 signal_status 조회 가능, 기존 on_close 동작 무변경).
- [ ] Commit: `feat: 시드·라이브 마감 상태 기록`

### Task 4: 거래 생애 그룹핑 + 페이지네이션·필터 (백엔드)

**Files:** Modify `dashboard/backend/queries.py`, `schemas.py`, `app.py` / Test `tests/dashboard/test_queries.py`, `test_api.py`

**Interfaces — Produces:**
- `queries.trades(sf, name, limit=20, offset=0, symbol=None, side=None, decision_type=None, date_from=None, date_to=None)` + 총 건수 반환(`{"items":[...], "total":int}` 형태로 변경 — app에서 스키마 `TradesPage(items: list[TradeOut], total: int)`).
- `queries.position_lifecycles(sf, name, limit=10)`: 종목별 BUY→(PARTIAL…)→보유0 SELL 묶음. 각 생애: symbol·entry_date·exit_date|None(진행중)·trades(list)·qty_peak·realized_pnl_sum·현재 보유 여부.
- API: `/api/characters/{name}/trades`에 쿼리 파라미터, `/api/characters/{name}/lifecycles` 신설.

- [ ] 그룹핑 규칙: 시간순 스캔, 보유수량 0→BUY로 새 생애 시작, 0 도달 SELL로 종료(테스트: 진입→부분→청산 시나리오·재매수 별도 생애·진행중 생애).
- [ ] 페이지네이션·필터 각 파라미터 테스트. 기존 응답 소비처(프론트 api.ts) 파손은 Task 6에서 갱신 — 백엔드 스키마 변화를 Interfaces에 명시했으니 프론트 태스크가 따라감.
- [ ] Commit: `feat: 거래 페이지네이션·필터+포지션 생애 그룹핑 API`

### Task 5: 의사결정판 데이터 API (후보·보유리스크·포트폴리오 위험)

**Files:** Modify `dashboard/backend/queries.py`, `schemas.py`, `app.py`, `summary.py` / Test `tests/dashboard/`

**Interfaces — Produces:**
- `/api/characters/{name}/candidates`: SignalStatusRow(kind=후보) → `CandidateOut(symbol,name,green_score,red_score,buy_gate,status,block_reason,as_of)`.
- positions 응답 확장: `weight_pct`(평가액/총자산), `entry_trigger`(해당 종목 마지막 BUY의 trigger_rule), `current_red_score`(SignalStatusRow kind=보유), `stop_px, trail_px, stop_distance_pct`((close−stop)/close), `potential_loss`(수량×(close−stop)×환산), `pending_sell: bool`, `as_of`.
- `/api/dashboard` 확장: `today_actions`(캐릭터별 pending_orders 결정 포함+최신일 FORCED_SELL 경보), `risk`(캐릭터별 현금비중·총노출·최대 보유 비중(종목 집중)·일 손익).

- [ ] 전부 저장 데이터만 사용(pending_orders/trades/positions/signal_status/equity). 각 응답 테스트.
- [ ] Commit: `feat: 의사결정판 API(오늘의 후보·보유 리스크·포트폴리오 위험)`

### Task 6: 프론트 — 의사결정판 재구성 + 후보/리스크

**Files:** `dashboard/frontend/src/` types.ts·api.ts·pages(Main)·components(CandidatesTable 신설, PositionsTable 확장, 신규 TodayActions/RiskStrip) / vitest

- [ ] Main 순서 재배치: ModeBar → 오늘의 행동(대기주문+강제매도 경보, 없으면 "오늘 예정된 행동 없음") → 포트폴리오 위험 스트립 → 캐릭터 카드(성과vs벤치 이미 우선) → MarketMovers/최근체결 하단.
- [ ] CandidatesTable: 오늘의 후보(점수·게이트·상태·차단 사유). 상세 페이지 보유 섹션 위에도 해당 캐릭터 후보 표시.
- [ ] PositionsTable: 비중·진입사유·현재 적신호·손절가·트레일가·거리%·잠재손실·매도대기·기준시각. 업종/실적 컬럼 없음.
- [ ] 접근성: 등락 색+▲/▼ 부호 병행(format 헬퍼).
- [ ] vitest: 섹션 순서, 후보 차단사유 렌더, 리스크 컬럼, 행동없음 문구, ▲/▼.
- [ ] Commit: `feat: 프론트 의사결정판(오늘의 행동·후보·보유 리스크)`

### Task 7: 프론트 — 거래 생애·페이지네이션·지표 맥락

**Files:** TradesTable(페이지네이션+필터+생애 뷰 토글), MetricsPanel/EquityChart 라벨 / vitest

- [ ] TradesTable: 기본 20건+페이지 이동, 필터(기간·종목·매수/매도·결정유형), "포지션 생애" 토글 뷰(진입→부분→청산 묶음, 생애 손익 합계).
- [ ] EquityChart 구간 수익률에 "선택 기간 수익률" 라벨, TWR 툴팁, 승률 옆 평균이익·평균손실·손익비(기존 Metrics 필드).
- [ ] vitest: 페이지네이션 동작·생애 묶음 렌더·라벨.
- [ ] Commit: `feat: 프론트 거래 생애 복기·페이지네이션·지표 맥락`

### Task 8: 문서·재시딩·검증

- [ ] trading-rules.md(후보 기록·차단 사유·생애 정의 절)+README. `python -m dashboard.scripts.seed_from_replay --force` 재시딩, 스모크(후보 rows·보유 리스크 값·생애 그룹·의사결정판 렌더 — 실제 관측값 기록). 전체 pytest+프론트.
- [ ] Commit: `docs: 의사결정판 규칙 문서 + 재시딩`

## 완료 후 (플랜 밖)

원장 갱신 → 최종 전체브랜치 리뷰(opus) → dev 병합 → **v1.9.0** 태그+패치노트. Codex 재감사 대상.
