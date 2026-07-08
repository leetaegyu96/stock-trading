# simcore 라이브 모드 (KIS 실시세 + 스케줄러 + DB 영속) — 설계 스펙

- 날짜: 2026-07-08
- 상태: 사용자 승인 완료 (브레인스토밍 세션)
- 상위 문서: `docs/superpowers/specs/2026-07-07-simcore-engine-design.md` (서브프로젝트 2)
- 매매 규칙 단일 기준: `docs/trading-rules.md`

## 1. 목표

완료된 순수 매매 엔진(리플레이 검증, 63 테스트 통과)을 **실시간으로 구동**한다.
KIS 오픈API에서 실시세를 받아 스케줄러가 엔진을 돌리고, 상태·이력을 PostgreSQL에
영속화하여 **몇 달씩 도는 프로세스가 재시작돼도 이어서** 매매한다. 화면(대시보드)은
다음 서브프로젝트이며, 이번 단계는 화면 없는 백그라운드 데몬이다.

## 2. 확정된 핵심 결정

| 축 | 결정 | 비고 |
|---|---|---|
| KIS 역할 | **실시세 데이터 피드 전용** | 엔진이 자체 시뮬레이션(다음 시가 체결·가상 3캐릭터). KIS 계좌에 주문하지 않음 |
| KR 유니버스 | **KIS 시가총액 상위 top-N** | 지수 구성종목 API의 KRX 인증 장벽 회피. 기존 `--kr-top` 설계와 일치하는 "대형주 top-N" |
| US 유니버스 | 기존 `universe.sp500()`(Wikipedia) 유지 | KIS 해외 랭킹 연동은 후속 |
| DB | **PostgreSQL** | 상태의 단일 원천(single source of truth) |
| 실행 모델 | **환경 비종속 + 재시작 복구 기본** | PC 수동 실행이든 서버 데몬이든 동일 동작 |
| 장중 가격 | **REST 5분 폴링(보유종목만)** | 규칙이 5분 주기라 WebSocket 불필요. 보유 ≤15종목 |
| 시장 범위 | **KR + US 둘 다**(3캐릭터 모두 라이브) | US 서머타임 = `zoneinfo(America/New_York)` 자동. 조기폐장·환전 정밀화는 서브프로젝트 5 |
| KIS 도메인 | 데이터 피드는 **real 도메인**(읽기전용, 안전) | paper 도메인은 시세·랭킹 미지원 다수 |

## 3. 아키텍처 — 순수 엔진 + 얇은 라이브 계층 (A안)

기존 엔진/리플레이/신호/포트폴리오 코드는 **한 줄도 변경하지 않는다**(63 테스트 무손상).
엔진 바깥에 라이브 계층을 감싼다.

```
                    ┌──────────────── simcore/live/ (신규) ────────────────┐
   KIS 오픈API ◀───▶│ kis_client   토큰·시세·시총랭킹 REST (real 도메인)      │
                    │ calendar     KR/US 거래일·거래시간 (zoneinfo, 휴장일)   │
   APScheduler ────▶│ scheduler    개장/마감/5분 트리거 + 휴장일 가드         │
   PostgreSQL ◀───▶ │ repository   상태 저장·복원 (SQLAlchemy)               │
                    │ orchestrator 엔진 구동자 (run_replay의 라이브 쌍둥이)  │
                    │ __main__     python -m simcore.live 데몬 진입점        │
                    └───────────────────────┬──────────────────────────────┘
                                             │ 기존 메서드 그대로 호출
                    ┌────────────────────────▼──────────────────────────────┐
                    │ simcore/engine.py (순수·무변경)                         │
                    │  start·evaluate_close·fill_open·check_stops·apply_flow· │
                    │  snapshot·force_close                                   │
                    └─────────────────────────────────────────────────────────┘
```

### 컴포넌트 책임

| 모듈 | 책임 | 의존 |
|---|---|---|
| `kis_client` | KIS REST 래퍼: OAuth 토큰 캐시·갱신, 현재가/일봉/시총랭킹 조회, 백오프·키 마스킹 | httpx |
| `calendar` | "지금 KR/US 장중인가? 오늘 거래일인가? 다음 개장은?" 판정 | zoneinfo, KIS 휴장일 |
| `scheduler` | 시각 트리거만 담당 — 개장·마감·5분 시점에 orchestrator 콜백 | APScheduler, calendar |
| `orchestrator` | KIS 데이터 → 엔진 메서드 → repository 저장. `run_replay`와 동일 호출순서 | engine, kis_client, repository |
| `repository` | Postgres CRUD + `rehydrate(engine)` + 트랜잭션 영속 | SQLAlchemy, psycopg |
| `live/__main__` | 부팅: 설정 로드 → DB 연결 → 엔진 복원 → 스케줄러 시작 | 위 전부 |

**핵심 불변식**: orchestrator는 리플레이와 **같은 엔진 메서드를 같은 순서로** 호출한다.
차이는 데이터 출처(과거 루프 vs KIS 실시간)와 저장(메모리 vs Postgres)뿐. 따라서
라이브 버그는 리플레이 픽스처로 재현 가능하다.

## 4. 데이터 흐름 & 스케줄러 타임라인

### 리플레이 → 라이브 매핑

| 리플레이(`run_replay`) | 라이브 트리거 | 엔진 호출 |
|---|---|---|
| 입출금 처리 | 개장 직전 | `apply_flow` (flow_requests 큐 소비) |
| 당일 시가 체결 | **개장 시각** | `fill_open` (pending 종목 현재가=시가) |
| 당일 OHLC 근사 손익절 | **장중 5분마다** | `check_stops` (보유종목 현재가 폴링) |
| 일봉 확정 신호판정 | **마감 후** | `evaluate_close` → 다음 개장용 pending |
| 평가액 | 마감 후 | `snapshot` → equity_curve 저장 |

### KR 하루 (Asia/Seoul)

```
08:50 개장준비  휴장일이면 스킵. 대기 입출금 → apply_flow
09:00 개장      pending 현재가 조회 → fill_open → DB 저장
09:05~15:25     5분마다: 보유 KR종목 현재가 → check_stops → 트리거 시 매도·저장
15:40 마감후    유니버스 확정 일봉(증분) → 지표·신호 → evaluate_close → pending 저장
                → snapshot → equity 저장 → (일1회) KIS 시총랭킹으로 유니버스 갱신
```

### US 하루 (America/New_York, DST 자동)

거래일 기준은 ET. 흐름 동일(09:30 개장 fill_open / 5분 check_stops / 16:00 마감 evaluate_close+snapshot).
벽시계상 KR 마감(15:30 KST)이 US 마감(≈06:00 KST 익일)보다 먼저라 **범용형의 "국내 먼저"
처리 순서가 자연히 보존**된다.

### 두 설계 포인트

1. **지표 워밍업 윈도우**: 신호 계산에 60+거래일 일봉 필요. 마감 후 KIS 일봉을 **증분 조회**
   (어제까지 DB캐시, 오늘분만 신규)로 종목별 롤링 윈도우 유지 → 기존 `sigmod.evaluate_frame`
   /`fired_at` 그대로 사용.
2. **5분봉 부재 처리**: 라이브 `check_stops`는 현재가만 있으므로 `o=h=l=c=현재가`인 유사
   `DailyBar`를 생성해 넘긴다. `b.low<=손절가`/`b.high>=익절가` 로직이 "현재가 기준 즉시
   체결"로 그대로 재사용된다(엔진 무변경).

## 5. PostgreSQL 스키마 & 상태 복원

### A. 엔진 상태 (복원용 — 항상 현재값)

| 테이블 | 컬럼 | 용도 |
|---|---|---|
| `characters` | name PK, base_currency | 3캐릭터 시드(참조) |
| `cash_balances` | character, currency, amount | 통화별 현금 (portfolio.cash) |
| `positions` | character, symbol, market, quantity, avg_price, opened_date | 보유 포지션 |
| `pending_orders` | id, character, side, symbol, market, green_count, red_count, change_pct, volume, fired[], reason, created_date | 다음 개장 대기 주문 |
| `cooldowns` | character, symbol, market, remaining_days | 재매수 금지 |
| `run_state` | market, last_open_date, last_close_date, last_fx_rate, schema_version | 멱등성 가드 |
| `kis_token` | access_token, expires_at | KIS 토큰 캐시 |

### B. 이력 & 캐시 (append-only / 조회용)

| 테이블 | 컬럼 | 용도 |
|---|---|---|
| `trades` | id, ts, date, character, symbol, market, side, quantity, price, fee, tax, reason, green_count, red_count, fired[], realized_pnl | 거래내역 (Trade 모델 1:1) |
| `capital_flows` | id, date, character, amount_krw, fx_rate | 입출금 원장 (TWR 소스) |
| `flow_requests` | id, character, amount_krw, liquidate[], status, requested_at, applied_at | 사용자 입출금 큐 (개장 시 소비). 이번 단계엔 UI가 없으므로 간단한 CLI(`python -m simcore.live deposit/withdraw ...`) 또는 직접 INSERT로 넣는다. 버튼 UI는 서브프로젝트 3 |
| `equity_curve` | ts, character, equity_krw | 자산곡선 (TWR·MDD·대시보드) |
| `daily_bars` | market, symbol, date, o,h,l,c,v | 지표 워밍업 증분 캐시 |
| `universe` | market, symbol, rank, as_of_date | 당일 유니버스 스냅샷 |

### 복원 (rehydrate)

데몬 부팅 시 `Repository.rehydrate(engine)`:
```
fresh Engine(config) 생성
→ 각 캐릭터: cash_balances → portfolio.cash
              positions      → portfolio.positions
              capital_flows  → portfolio.flows (TWR 정합성)
              pending_orders → pending_buys / pending_sells
              cooldowns      → cooldowns
→ 이력(trades)은 메모리에 로드하지 않음 (DB가 원천, 조회는 쿼리)
```
과거를 재생하지 않고 **현재 상태만 복원** → 순수 엔진 무변경, 부팅 즉시 재개.

### 멱등성 (재시작 안전)

각 트리거는 `run_state`를 먼저 확인해 이미 처리한 오늘의 open/close를 스킵한다.
매 엔진 변경 후 **[상태 delta + 이력 append + run_state 갱신]을 한 트랜잭션**으로 커밋 →
크래시 시 DB는 항상 "마지막 완료 단계"까지 일관.

### 최초 부팅

`run_state`가 비어있으면 → `engine.start(today, fx0)`로 3캐릭터 1억씩 초기 입금 후 시작.

## 6. KIS 클라이언트

### 인증 & 토큰 캐시
- `POST /oauth2/tokenP`(appkey/appsecret) → access_token(24h). **재발급 제한**이 있어
  `kis_token` 테이블에 캐시하고 만료 임박 시에만 갱신.
- 헤더: `authorization: Bearer`, `appkey`, `appsecret`, `tr_id`, `custtype=P`.
  키는 로그·에러에서 마스킹.

### 도메인
- real: `openapi.koreainvestment.com:9443` (데이터 피드로 사용)
- paper: `openapivts.koreainvestment.com:29443` (시세·랭킹 미지원 다수 → 미사용)
- `KIS_ENV=real` 로 데이터 조회. 주문을 하지 않으므로 real 읽기전용은 계좌에 무해.

### 엔드포인트

| 기능 | 엔드포인트 (tr_id) | 쓰임 |
|---|---|---|
| 국내 현재가 | `inquire-price` (FHKST01010100) | 개장 체결·5분 손익절 |
| 국내 일봉 | `inquire-daily-itemchartprice` (FHKST03010100) | 지표 워밍업(증분) |
| 국내 시총상위 | `ranking/market-cap` (FHPST01740000) | KR 유니버스 top-N |
| 해외 현재가 | `overseas-price/.../price` (HHDFS00000300) | US 체결·손익절 |
| 해외 일봉 | `overseas-price/.../dailyprice` (HHDFS76240000) | US 지표 워밍업 |

- 환율(USD/KRW): KIS에 깔끔한 FX 엔드포인트 없음 → 기존 `yfinance KRW=X`를 일 1회 조회.
  실시간 정밀 환율은 서브프로젝트 5.

### 레이트리밋
- **토큰버킷 리미터**(기본 ~10 req/s, 설정값)로 감싼다.
- 마감 후 일봉은 증분이라 하루 실제 호출 ≈ 유니버스 N개. 5분 폴링은 보유종목(≤15)만.

### 새 의존성
`httpx`, `SQLAlchemy`, `psycopg`, `APScheduler`. (finance-datareader 불필요.)

## 7. 에러 처리 & 재시작 복구

### KIS 호출 실패(일시적)
- 재시도 + 지수 백오프(3회). 401→토큰 1회 재발급 후 재시도. 429→대기 후 재시도.
- 그래도 실패 시 그 종목만 스킵, 데몬은 유지.

### 종목 단위 결측 (엔진 기존 처리 재사용)
| 상황 | 처리 |
|---|---|
| 개장 시 pending 현재가 없음(거래정지) | `fill_open`이 pending 이월(기존 로직) |
| 5분 폴링 보유종목 현재가 없음 | 이번 사이클 스킵, 다음 5분 재시도 |
| 마감 후 일부 일봉 실패 | 그 종목만 신호 제외(전부 꺼짐), 나머지 진행 |
| 상장폐지 감지 | `engine.force_close(마지막가)` |
| 환율 조회 실패 | `run_state.last_fx_rate` 재사용 |

### 재시작/공백 복구 = "갭 리플레이"
데몬이 꺼져 있던 동안 놓친 거래일을 KIS **확정 일봉**으로 조회해 `run_replay` 로직으로
재생하여 현재 시각까지 따라잡은 뒤 라이브로 전환한다. 공백 기간의 5분 정밀도는 OHLC
근사로 대체됨(리플레이와 동일, 로그에 명시). 라이브 ≡ "실시간으로 이어지는 리플레이".

### 치명적 오류 = 안전 정지
- DB 연결 지속 실패 → 상태 저장 불가이므로 무리하게 진행하지 않고 안전 정지(로그+비정상 종료).
- 필수 설정(KIS 키/DB URL) 없음 → 즉시 명확한 에러로 종료.

### 관측성
- 구조적 로그(트리거·체결·스킵·에러), 민감정보 마스킹. trades/equity_curve/에러로그가
  운영 감사 기록. 알림(텔레그램 등)은 범위 밖.

## 8. 테스트 전략

순수 엔진의 기존 63 테스트는 무손상 유지(회귀 가드). 라이브 계층은 KIS 목으로 네트워크 없이 검증.

| 대상 | 방식 | 핵심 검증 |
|---|---|---|
| `kis_client` | httpx 목 | 토큰 발급·캐시·갱신, 응답 파싱, 백오프·401·429, 키 마스킹 |
| `calendar` | 순수·결정론 | KR/US 거래일·개장 판정, DST 전환(3·11월 경계), 휴장일 |
| `repository` | 임시 Postgres | persist→rehydrate 상태 완전 동일, 멱등성(트리거 2회≠중복) |
| `orchestrator` | KIS 목 + 임시 DB | 하루 사이클 후 엔진 상태·DB 행 일치 |
| **동치성** | 동일 픽스처 | run_replay와 라이브 orchestrator(목) 결과 **완전 동일** ★ |
| 갭 리플레이 복구 | 시나리오 | N일 다운 후 재부팅 = 연속 실행과 동일 상태 |

★ 동치성 테스트가 안전벨트("라이브 = 실시간으로 이어지는 리플레이" 증명).

**테스트 DB**: Postgres 전용 기능 사용 → `TEST_DATABASE_URL` 설정 시에만 DB 테스트 실행
(없으면 skip). 로컬은 docker Postgres 권장. 구현은 test-driven-development 스킬로 진행.

## 9. 완료 기준

1. `python -m simcore.live` 부팅 → DB 연결 → rehydrate(또는 콜드스타트 3캐릭터 1억) →
   스케줄러 가동. KIS 목 기반 통합테스트 E2E 통과.
2. 동치성 테스트 통과(라이브 ≡ 리플레이).
3. 장중 재시작 무중복 재개 + 갭 리플레이 복구 동작.
4. 전체 테스트 green (기존 63 + 신규 라이브).
5. 라이브 스모크 런: 실제 KIS(real 도메인)로 1거래일 가동, 결과 Postgres 적재,
   `docs/experiments/`에 기록.
6. 문서 갱신: `.env.example`(신규 변수), `README`(라이브 모드 사용법).
   `docs/trading-rules.md`는 규칙 불변이라 무영향.

## 10. 범위 밖 (후속 서브프로젝트)

- FastAPI·React·WebSocket 대시보드 (서브프로젝트 3)
- 감정분석·뉴스·수급 신호(G8·G9·R8·R9) 실제 구현 (서브프로젝트 4)
- 서머타임/환전 정밀화, 조기폐장, 알림 (서브프로젝트 5)

## 11. 신규 환경변수 (.env)

```
KIS_APP_KEY=...            # 발급 완료
KIS_APP_SECRET=...         # 발급 완료
KIS_ACCOUNT_NO=...         # 계좌번호(보관)
KIS_ENV=real               # 데이터 피드 도메인
DATABASE_URL=postgresql://...   # Postgres 접속
TEST_DATABASE_URL=postgresql://...  # (선택) DB 테스트용
```
access_token은 코드가 자동 발급·캐시하므로 사용자가 직접 넣지 않는다.
`.env`는 AI 도구가 읽지 않으며 `.gitignore`에 등록되어 있다.
