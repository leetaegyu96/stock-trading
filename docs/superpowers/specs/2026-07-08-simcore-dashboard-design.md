# simcore 대시보드 (React + FastAPI + WebSocket) — 설계 스펙

- 날짜: 2026-07-08
- 상태: 사용자 승인 완료 (브레인스토밍 세션)
- 상위 문서: `docs/superpowers/specs/2026-07-07-simcore-engine-design.md` (서브프로젝트 3)
- 선행: 서브프로젝트 1(엔진), 2(라이브 모드) — v1.1.0 릴리즈됨

## 1. 목표

라이브 모드가 PostgreSQL에 쌓는 3캐릭터의 상태·이력·자산곡선을 **눈으로 보는 대시보드**를
만든다. 하이브리드 UX: 메인은 캐릭터 카드로 요약, 카드 클릭 시 진지한 상세(차트·표)로 진입.
실시간 갱신(WebSocket)과 입출금 버튼을 제공한다.

## 2. 확정된 핵심 결정

| 축 | 결정 | 비고 |
|---|---|---|
| 성격 | **하이브리드** — 리치 캐릭터 카드(메인) → 진지한 상세 | 게임형 아님, 실용+약간의 재미 |
| 스택 | **FastAPI(백엔드) + React/Vite(프론트)**, 로컬 단일 서빙 | FastAPI가 React 정적 빌드도 서빙 |
| 실시간 | **WebSocket 푸시**, FastAPI가 Postgres 주기 폴링(~3–5s) + 장중 KIS 현재가 | 라이브 데몬과 디커플 — DB만 읽어도 동작 |
| 쓰기 | 입출금 **버튼** → `flow_requests` 예약(개장 시 데몬이 소비) | 출금 부족 시 청산종목 지정 |
| 순수/라이브 계층 | **무변경** — 대시보드는 읽기 + flow_requests INSERT만 | 엔진/repository 재사용 |

## 3. 아키텍처

신규 `dashboard/` 디렉토리. 순수 엔진(`simcore/`)과 라이브 계층(`simcore/live/`)은 변경하지 않고
임포트해서 재사용한다.

```
dashboard/
├── backend/                    # FastAPI (Python, simcore 재사용)
│   ├── __init__.py
│   ├── app.py                  # FastAPI 앱: REST + WebSocket + React 정적 서빙
│   ├── queries.py              # Postgres 조회 (SQLAlchemy, db.py ORM 재사용)
│   ├── summary.py              # 카드/상세용 집계 + TWR·MDD (simcore.metrics 재사용)
│   ├── live_prices.py          # kis_client(DbTokenStore)로 보유종목 현재가 조회
│   ├── flows.py                # 입출금 예약 (repository.enqueue_flow 재사용)
│   └── broadcaster.py          # 폴링 루프 + WebSocket 연결 관리/푸시
└── frontend/                   # Vite + React + TypeScript
    ├── index.html, vite.config.ts, package.json
    └── src/
        ├── api.ts              # REST/WS 클라이언트
        ├── pages/Main.tsx      # 리치 카드 3개
        ├── pages/Detail.tsx    # 자산곡선·보유종목·거래내역+지표
        └── components/         # Card, EquityChart, Sparkline, PositionsTable,
                                #   TradesTable, MetricsPanel, FlowModal
```

빌드/서빙: `vite build` → `dashboard/frontend/dist` 를 FastAPI가 `StaticFiles`로 서빙.
개발 중에는 Vite dev server + FastAPI를 함께 띄워도 되지만, 배포 형태는 **FastAPI 단일 프로세스**
(localhost:8000에서 API·WS·정적 파일 모두 서빙).

**데이터 원천**: 라이브 데몬이 쓰는 것과 동일한 PostgreSQL(`DATABASE_URL`). 대시보드는
읽기 전용 + `flow_requests` INSERT. 데몬과 별개 프로세스로, 데몬이 꺼져 있어도 마지막 상태를 보여준다.

**토큰 공유**: 장중 현재가 조회는 `kis_client` + `DbTokenStore`를 써서 **데몬과 같은 `kis_token`
캐시를 공유** → 대시보드가 별도 토큰을 발급하지 않아 KIS "1분당 1회 발급" 제한과 무관.

## 4. REST API

| 메서드 | 경로 | 반환 |
|---|---|---|
| GET | `/api/characters` | 3캐릭터 카드 요약: name, base_currency, market(s), total_asset_krw, twr, pnl_krw, today_pnl_pct, equity_spark(최근 30점), n_positions, cash_krw, benchmark_delta |
| GET | `/api/characters/{name}` | 상세 헤더 + 성과지표(twr, mdd, n_trades, win_rate, pnl_krw) |
| GET | `/api/characters/{name}/equity?range=` | 자산곡선 시계열 + 벤치마크 시계열 |
| GET | `/api/characters/{name}/positions` | 보유 종목(현재가·평가액·손익% 포함, live_prices 병합) |
| GET | `/api/characters/{name}/trades?limit=` | 거래내역(사유·켜진 청/적신호·손익) |
| GET | `/api/characters/{name}/flows` | 입출금 이력 |
| POST | `/api/characters/{name}/deposit` `{amount_krw}` | flow_requests 예약(입금) |
| POST | `/api/characters/{name}/withdraw` `{amount_krw, liquidate[]}` | flow_requests 예약(출금) |

- 응답은 pydantic 모델로 직렬화. 금액은 원 단위 정수/실수, 비율은 소수.
- 벤치마크: KOSPI200/S&P500 (기존 `__main__` 벤치마크 로직 참고, 캐시).

## 5. WebSocket `/ws`

- 클라이언트 접속 시 현재 스냅샷(카드 요약 전체) 1회 전송.
- FastAPI 백그라운드 태스크가 **~3–5초 주기**로 Postgres를 폴링:
  - `run_state`/`equity_curve`/`positions`/`trades` 변경 감지 → 카드 요약 재계산.
  - 장중(거래시간)엔 `live_prices`로 보유종목 현재가 갱신.
  - 직전 스냅샷과 diff가 있으면 접속 클라이언트에 push (`{type:"cards", data:[...]}` / `{type:"trade", ...}`).
- 연결 관리: 접속/해제 목록 유지, 예외 시 개별 연결만 정리(전체 죽지 않음).
- 폴링 주기·장중 판정은 설정값. `simcore.live.calendar` 재사용.

## 6. 화면

### 메인 (`/`)
- 3개 **리치 카드** 가로 배열. 카드 내용:
  - 캐릭터명, 유니버스(KOSPI200/S&P500/혼합), 통화
  - 총자산(₩), TWR(%), 누적손익(₩), 오늘 등락(▲/▼ %)
  - 30일 자산곡선 스파크라인
  - 보유 종목 수 · 현금
  - 벤치마크 대비(+%p)
- 카드 클릭 → 상세로 라우팅. 상단에 전체 합계/마지막 갱신 시각.

### 상세 (`/character/{name}`)
- **자산곡선 차트**: 자산/TWR 추이 라인 + 유니버스 벤치마크 오버레이. 기간 토글(1M/3M/전체).
- **보유 종목 테이블**: 종목·수량·평단·현재가·평가액·손익%·보유일. 실시간 갱신.
- **거래 내역 테이블**: 일자·종목·매수/매도·수량·가격·사유(청/적신호 배지·손절/익절)·실현손익.
- **성과 지표 패널**: TWR·MDD·누적손익·거래수·승률.
- 헤더에 **입금/출금 버튼**(모달): 금액 입력, 출금 시 청산종목 선택. 제출 → flow_requests 예약,
  "다음 개장에 반영" 안내.
- (신호 현황 섹션은 G8/9·R8/9 스텁이 실제 구현되는 서브프로젝트 4로 미룸.)

### 캐릭터 아바타 (미모티콘 느낌) ★
- 3캐릭터 각각 **고유 아바타(친근한 얼굴형 캐릭터)** 를 갖고, 메인 카드와 상세 헤더에 표시.
- **성과 연동 표정**: 아바타 표정이 상태를 반영해 "살아있는" 느낌을 준다.
  - 오늘 등락(또는 TWR) 기준: `+` 크게 → 활짝 웃음, 소폭 → 미소, 0 근처 → 무표정, `−` → 시무룩/찡그림.
  - 손절 발생 등 이벤트 시 순간 반응(옵션).
- **캐릭터 정체성**: 국내형/해외형/범용형을 소품·색으로 구분(예: 국내형=태극/원화 느낌, 해외형=지구본/달러,
  범용형=혼합). 과하지 않게.
- **구현 방식**: 로컬 생성 SVG 아바타로 자산 의존/네트워크 없이 처리.
  - 1순위: `@dicebear`(예: `fun-emoji`/`big-smile` 스타일)를 **npm 로컬 생성**(런타임 네트워크 X),
    캐릭터명을 seed로 결정론적 얼굴 + 표정 파라미터를 성과로 매핑.
  - 대안: 3캐릭터 전용 **커스텀 인라인 SVG**(표정 3~4단계 variant)를 직접 제작 — 3개뿐이라 충분히 가능.
  - 구현 단계에서 둘 중 택1(디자인 취향 확인).

### 디자인 톤
- 라이트/다크 모두 지원. 상승/하락 색은 **한국 관례(상승=빨강, 하락=파랑)** 기본, 접근성 고려한 중립 배경.
- 캐릭터별 은은한 색상 구분(국내형/해외형/범용형) — 아바타 정체성과 일치시킴.

## 7. 재사용 & 계산

- `simcore.metrics.time_weighted_return` / `max_drawdown` / `simple_pnl_krw` — equity_curve + capital_flows 로 TWR·MDD·손익.
- `simcore.live.db` ORM + 조회. `simcore.live.repository.enqueue_flow` (입출금 예약).
- `simcore.live.kis_client` + `DbTokenStore` (보유종목 현재가). `simcore.live.calendar` (장중 판정).

## 8. 에러 처리

- DB 연결 실패 → API 503 + 프론트에 "DB 연결 불가" 표시. WS는 재연결 백오프.
- KIS 현재가 실패(장 마감/일시 오류) → 마지막 종가(daily_bars 캐시)로 폴백, 표에 "지연" 표시.
- 빈 데이터(거래·이력 없음, 콜드스타트 직후) → 빈 상태 UI("아직 데이터 없음").
- 입출금 예약 실패(잘못된 금액 등) → 400 + 폼 검증 메시지.

## 9. 테스트 전략

- **백엔드**: FastAPI `TestClient` + 테스트 Postgres. REST 각 엔드포인트(요약·상세·equity·positions·trades·flows),
  입출금 POST가 flow_requests에 올바르게 예약되는지, 메트릭(TWR/MDD) 정확성(고정 fixture),
  WebSocket 초기 스냅샷/푸시(연결 테스트). `TEST_DATABASE_URL` 있을 때만 DB 테스트 실행.
- 순수 엔진/라이브 계층 기존 96 테스트 무손상 유지.
- **프론트엔드**: 개인용 범위 — 핵심 컴포넌트(Card, EquityChart 데이터 매핑) 스모크/유닛 위주.
  무거운 브라우저 E2E는 생략(필요 시 후속). 빌드가 성공하고 메인/상세가 목 데이터로 렌더되는지 확인.

## 10. 완료 기준

1. `uvicorn dashboard.backend.app:app` 기동 → localhost에서 메인(카드 3개)·상세 화면 표시.
2. REST API가 Postgres 데이터를 정확히 반환(메트릭 포함), 백엔드 테스트 통과.
3. WebSocket으로 카드/보유종목이 실시간(폴링) 갱신됨.
4. 입금/출금 버튼이 flow_requests에 예약되고, (데몬 가동 시) 다음 개장에 반영됨.
5. 기존 96 테스트 green 유지 + 신규 백엔드 테스트 통과.
6. README에 대시보드 실행법 추가.

## 11. 범위 밖 (후속)

- 감정·수급 신호(G8/9·R8/9) 및 신호 현황 화면 (서브프로젝트 4).
- 인증/멀티유저, 모바일 최적화, 클라우드 배포 (개인 로컬용이라 범위 밖).
- 서머타임/환전 정밀화, 알림 (서브프로젝트 5).

## 12. 신규 의존성

- 백엔드: `fastapi`, `uvicorn[standard]` (httpx·SQLAlchemy·psycopg는 기존).
- 프론트: Node(v24 존재) + Vite + React + TypeScript + 차트 라이브러리(경량, 예: 자체 SVG 스파크라인 +
  라인차트는 가벼운 라이브러리) + `@dicebear`(로컬 SVG 아바타 생성, 런타임 네트워크 없음) 또는 커스텀 SVG.
  CSP·번들은 로컬 서빙이라 제약 적음.
