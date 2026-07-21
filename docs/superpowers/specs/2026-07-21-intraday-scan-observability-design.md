# 장중 스캔 관측성 (Intraday Scan Observability) — 설계

2026-07-21 · 관련 이슈: 후속(#48 토큰 버그와 같은 "조용한 실패" 계열)

## 배경 / 문제

운영자가 장중 자동매매(intraday)를 켜고 1시간을 돌려도 **매매가 안 일어나면
대시보드에서 "돌고 있는지"조차 확인할 수 없다.** 세 가지 관측성 구멍:

1. **"실시간 · HH:MM:SS" 표기가 오해를 부른다.** (`Main.tsx:94-101`, `broadcaster.py`)
   - "실시간" = 단지 **WebSocket 연결됨** 표시. 시세가 실시간이라는 뜻이 아니다.
   - "HH:MM:SS" = **브라우저 시계** 기준 *마지막 카드 스냅샷 수신 시각*(`lastUpdated = new Date()`).
     브로드캐스터는 카드 값이 바뀔 때만 push하므로(`poll_once`), 변화가 없으면 멈춰 있다.
   - 즉 시장 데이터 기준시각도, KIS 조회 시각도, **스캔 시각도 아니다.**

2. **스캔 하트비트가 없다.** `on_intraday`는 `intraday_scan_minutes`(기본 10분)마다
   돌며 종목별 신호·매수/매도를 판단하지만, **매매가 없으면 DB에 아무 흔적도 안 남는다**
   (stdout `print`만). "마지막으로 언제 스캔했고 몇 종목 봤는지"를 알 수 없다.
   - 특히 전 종목 조회가 실패하면 `if not snaps: return`(orchestrator.py:272)으로 조용히
     빠져나가 흔적이 0 — #48 토큰 버그가 바로 이 경로로 조용히 실패했다.

3. **의사결정판이 장중에 안 갱신된다.** 대시보드에는 이미 "오늘의 후보" 판
   (`CandidatesTable`: 청신호·적신호·매수게이트 통과/미충족·차단사유)이 있지만,
   `signal_status` 테이블은 **장 마감(`on_close`) 때만** `replace_signal_status`로 갱신된다.
   `evaluate_intraday`는 `last_candidates`를 채우지 않고, `on_intraday`는 `replace_signal_status`를
   호출하지 않는다. → 장중 내내 어제 마감값으로 얼어 있어 "왜 안 샀는지"가 안 보인다.

## 목표

- G1. **스캔 하트비트**: 매 스캔마다(0건 매매·전건 실패 포함) "언제/몇 종목/게이트 통과 몇/
  매수·매도 몇"을 DB에 남기고 대시보드에 표시.
- G2. **의사결정판 장중 갱신**: 장중 스캔마다 종목별 청/적·게이트·차단사유·상태를 갱신 →
  "샀다/안 샀다(사유)/팔았다"가 실시간으로 보임.
- G3. **"실시간" 라벨 정정**: 연결 표시와 데이터/스캔 기준시각을 정확한 문구로 분리.

## 비목표 (YAGNI)

- 스캔 이력의 시계열 로그/차트(현재는 시장별 "최신 1건"만 유지 — run_state와 동일 철학).
- 실주문/알림. (이 제품은 페이퍼 전용)
- 종목별 스킵 원인(네트워크 실패 사유)의 개별 표시 — 하트비트의 `failed` 카운트로 집계만.

## 설계

### 1. 엔진 — `evaluate_intraday`가 `last_candidates`를 채운다 (`simcore/engine.py`)

`evaluate_close`와 동일한 "관찰 전용 기록만 추가, 매매 로직 불변" 원칙. 매수 판정 루프의
각 스킵 지점에서 `CandidateEval(sym, market, green_score, red_score, buy_gate, status, block_reason)`을
기록한다. 시장 단위 교체(`kept = [c for c in last_candidates ... if c.market != market]`).

장중 차단 사유(기존 마감 사유 + 장중 전용 추가):

| 조건 (evaluate_intraday 순서) | status | block_reason |
|---|---|---|
| `sym in held` | 차단 | 보유중 |
| `sym in st.cooldowns` | 차단 | 쿨다운 |
| `green_score < buy_score_min` | 차단 | 점수부족 |
| `not buy_gate` | 차단 | 게이트미충족 |
| 후보군에서 `slots <= 0` | 차단 | 슬롯부족 |
| `strength < intraday_strength_buy_min` | 차단 | 체결강도미달 *(신규)* |
| `_intraday_can_buy`=False: 종목별 매수 캡 초과 | 차단 | 장중매수캡 *(신규)* |
| `_intraday_can_buy`=False: 재매수 쿨다운 | 차단 | 재매수쿨다운 *(신규)* |
| `_intraday_can_buy`=False: 당일손실 킬스위치 | 차단 | 킬스위치 *(신규)* |
| `_buy(...)`=False (수량 0) | 차단 | 현금부족 |
| `_buy(...)`=True | 매수 | "" |

- `_intraday_can_buy`는 현재 bool만 반환하므로, 사유 분해를 위해 내부 세 조건을 순서대로
  검사하는 형태로 리팩터(동작 불변, 반환값만 세분화 or 헬퍼가 사유 문자열 반환).
- **불변식**: 실제 매수/매도 결과(체결 종목·수량)는 이 변경 전후로 100% 동일해야 한다
  (기록만 추가). golden 테스트로 회귀 방지.

### 2. 오케스트레이터 — `on_intraday`가 판+하트비트를 쓴다 (`simcore/live/orchestrator.py`)

- 유니버스 조회 루프에서 **시도 수(universe)·성공 수(snaps)·실패 수**를 집계.
- `evaluate_intraday` 전후로 캐릭터별 `len(trades)`를 비교해 이번 스캔의 **매수/매도 건수** 산출
  (엔진 시그니처 변경 없이 orchestrator에서 계산).
- **하트비트는 `if not snaps: return`보다 먼저, 항상 기록**한다(전건 실패 시에도 흔적).
- 트랜잭션(락 구간) 안에서:
  - `replace_signal_status(self._signal_status_rows(d, m, snaps), session=s, market=market)`
    — `on_close`와 동일. `_signal_status_rows`는 이미 `last_candidates`+보유를 읽으므로 재사용.
  - `record_scan(market, ts=now, universe_size, evaluated, failed, gate_pass, buys, sells,
    scan_minutes, session=s)`.
- `gate_pass = sum(1 for s in snaps.values() if s.buy_gate)`.

### 3. 영속 — `IntradayScanRow` (`simcore/live/db.py`, `repository.py`)

`run_state`와 같은 "시장별 최신 1행" 철학. `s.merge`로 upsert.

```python
class IntradayScanRow(Base):
    __tablename__ = "intraday_scan"
    market: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime)      # 마지막 스캔 시각(시장 tz aware)
    universe_size: Mapped[int]   # 시도 종목 수
    evaluated: Mapped[int]       # 신호 계산 성공 종목 수
    failed: Mapped[int]          # 조회/계산 실패로 스킵한 수
    gate_pass: Mapped[int]       # 매수게이트 통과 종목 수
    buys: Mapped[int]            # 이번 스캔 매수 건수
    sells: Mapped[int]           # 이번 스캔 매도 건수
    scan_minutes: Mapped[int]    # 설정된 스캔 주기(UI "다음 ~N분")
```

`repository.record_scan(...)` (session 지원, `mark_close`와 동일 패턴) + `scan_status()` 조회.

### 4. 백엔드 API (`dashboard/backend`)

`/api/status`(MarketStatusOut) 패턴을 그대로 미러.

- `queries.scan_status(sf) -> list[dict]` — `intraday_scan` 전체 행.
- `schemas.ScanStatusOut` — 위 컬럼 + 파생 없음.
- `@app.get("/api/scan-status", response_model=list[ScanStatusOut])`.

### 5. 프론트엔드 (`dashboard/frontend/src`)

- **라벨 정정** (`Main.tsx`, `ModeBar.tsx`):
  - `실시간`/`실시간 연결` → `연결됨`(dot on)·`오프라인`/`연결 끊김`(off). "실시간" 단어 제거.
  - `Main.tsx`의 `· ${formatTime(lastUpdated)}`에 `카드 갱신` 라벨을 붙여 의미 명시
    (`카드 갱신 HH:MM:SS`), 또는 스캔 스트립으로 대체.
- **스캔 상태 스트립**(신규 컴포넌트 `ScanStatusStrip`): `getScanStatus()`로 조회, 카드
  스냅샷(asOf) 갱신 시 재조회. 표시 예:
  `장중 스캔 · KR 13:43 (60종목·게이트통과 3·매수 0/매도 0·실패 0) · 다음 ~10분`
  - 스캔 기록이 없으면 `장중 스캔 대기 중(가동 전/OFF)` 명시(조용히 생략 X).
- 기존 `CandidatesTable`은 그대로 두되, 이제 장중에도 자동 갱신됨(데이터 소스만 바뀜).

## 데이터 흐름

```
스케줄러(intraday every N min)
  → orch.on_intraday(now, d, market, universe)
      조회 루프(KIS, 락 밖) → snaps/strengths + (universe,evaluated,failed) 집계
      [락] evaluate_intraday(→ 매매 + last_candidates 기록)
           trades delta → buys/sells 집계
           [txn] persist_state / append_new_trades / persist_intraday_guards
                 replace_signal_status(후보+보유, market)      # G2
                 record_scan(하트비트)                          # G1
DB: intraday_scan(최신 1행/시장), signal_status(시장별 교체)
  → /api/scan-status, /api/characters/{n}/candidates
  → ScanStatusStrip, CandidatesTable
```

## 에러 처리

- 종목별 조회/계산 실패는 기존대로 개별 스킵(`failed` 카운트에 반영), 나머지 유니버스·persist 계속.
- 하트비트 기록은 매매/판 기록과 **같은 트랜잭션**으로 원자적. `snaps`가 비어도 하트비트는 남긴다.
- `scan_status` 조회 실패 시 프론트는 마지막 값 유지(ModeBar의 market-status와 동일 정책).

## 테스트 계획 (TDD)

- **엔진(가장 중요)**: `evaluate_intraday` 기록 추가 후에도 체결 결과 불변(golden). 각 차단 사유가
  올바른 `block_reason`으로 기록되는지(보유중/쿨다운/점수부족/게이트미충족/슬롯부족/체결강도미달/
  장중매수캡/재매수쿨다운/킬스위치/현금부족/매수).
- **오케스트레이터**: (a) 스캔 시 `signal_status` 후보/보유 행이 갱신된다. (b) 하트비트가
  기록된다(universe/evaluated/failed/gate_pass/buys/sells). (c) **전건 실패(snaps 비어도)** 하트비트가
  남는다. (d) 매수/매도 건수 집계 정확.
- **repository**: `record_scan` upsert(시장별 최신 1행), `scan_status` 조회.
- **백엔드**: `/api/scan-status` 응답 스키마·값.
- **프론트**: `ScanStatusStrip` 렌더(데이터 있음/없음), 라벨 정정 반영(ModeBar/Main 테스트 갱신).

## 롤아웃

- `INTRADAY_ENABLED=0`(기본)이면 스캔 미가동 → 하트비트 없음 → 스트립은 "대기 중" 표시(정상).
- DB: 신규 테이블 `intraday_scan`은 `create_all`로 자동 생성(마이그레이션 불필요, 기존 테이블 불변).
- 기존 `on_close` 경로·리플레이·시딩 동작 불변(이 설계는 장중 경로에만 기록을 추가).
