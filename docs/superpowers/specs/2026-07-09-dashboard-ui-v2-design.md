# 대시보드 UI 개편 v2 + 데이터 리셋 — 설계 스펙

- 날짜: 2026-07-09
- 상태: 사용자 승인 완료 (브레인스토밍 세션)
- 상위: 주식 모의투자 시뮬레이터 — 서브프로젝트 5(대시보드 UX)
- 전제: 사용자는 **주식 완전 초짜**. "최대한 친절하고 친화적인 UI". 전문가가 봐도 "그럴싸"하되 초보가 이해 가능.
- 선행: 서브프로젝트 4(신호 v2, v1.3.0) 완료. 라이브 DB 스키마에 점수·트레일링·부분매도 컬럼 추가됨.

## 1. 배경 · 목표

v1.2.1 대시보드에 대한 사용자 화면 피드백을 반영한다:

**메인(index)**
1. 상단 "simcore 모의투자" 텍스트 제거.
2. 화면이 비어 보임 → 카카오뱅크·토스·한국투자 앱처럼 **일일 현황판**으로 꽉 채운다(시장 movers + 포트폴리오). 3개 캐릭터 카드는 유지하되 좌측 1열 배치 허용.
3. 캐릭터별 보유종목 등 실제 앱 수준 정보 노출.

**캐릭터 상세(detail)**
1. 종목번호 대신 **종목명(한글)** 표시.
2. "G1" 같은 암호식 신호 → **한 줄 요약 + 펼치면 이름·별점**의 초보 친화 표시.
3. 범용형 총자산 불일치(카드 4,100만 vs 상세 곡선 1억08) 해소.

**데이터**: 현재 DB는 v1 데모시드(구스키마)라 v2와 불일치 → **6개월 리플레이(2026-01-09~07-09) 결과를 DB에 적재**해 대시보드가 v2 실결과를 보여주게 한다.

## 2. 범위 밖

- 신호 엔진 로직 변경(= sp4에서 끝남). 이 서브프로젝트는 **표시·조회·시딩**만.
- 전략 튜닝(하락장 가드 등) = 서브프로젝트 6.
- 라이브 데몬 상시 구동/실거래.

## 3. 아키텍처 개요

3계층 그대로: (a) 데이터 시딩 스크립트, (b) FastAPI 백엔드 조회 확장, (c) React 프론트 개편.
순수 엔진(`simcore/`)·라이브 계층 로직은 건드리지 않는다(시딩은 리플레이 결과를 DB에 기록할 뿐).

## 4. 데이터 리셋 — 리플레이 결과 적재

**신규: `dashboard/scripts/seed_from_replay.py`** (기존 `seed_demo.py`는 데모 유지 또는 대체).

- `--force` 가드 유지(실데이터 보호). DB 스키마를 재생성(`Base.metadata.drop_all`+`create_all`)해 v2 컬럼 반영.
- 6개월 리플레이를 실행(또는 캐시된 산출물 로드)해 `ReplayResult`를 얻고, 3캐릭터 각각에 대해:
  - `trades` → `TradeRow`(green_score/red_score/fired 포함).
  - `equity` 일별 → `EquityPoint`(**포지션+현금 스냅샷과 동일 소스** → 카드 총자산 = 상세 곡선 마지막값, 불일치 해소).
  - 최종 `positions` → `PositionRow`(peak_price/locked_stop_pct 포함), `cash` → `CashBalance`, `flows` → `CapitalFlow`.
- **범용형 불일치 근본 해소**: card_summary의 total_asset과 equity_series 마지막값이 같은 스냅샷에서 나오도록 시딩(리플레이 관례상 이미 정합).
- 결정론: 고정 기간·유니버스로 재현 가능.

## 5. 종목명 — 번들 정적 매핑 + KIS 보강

**신규: `simcore/names.py`** (또는 `dashboard/backend/names.py`) — `SYMBOL_NAMES: dict[str, str]`.
- KR: 유니버스 폴백 top-30 + 리플레이 등장 종목 코드→한글명(예: `"005930": "삼성전자"`).
- US: 티커→회사명(S&P500 주요, 예: `"AAPL": "Apple"`). 미국은 티커 자체도 친숙하므로 "AAPL · Apple" 병기.
- 조회 함수 `display_name(symbol, market) -> str`: 매핑에 있으면 이름, 없으면 코드 그대로(안전 폴백).
- **KIS 보강(라이브 한정)**: `live_prices`가 현재가 조회 시 KIS 응답의 종목명(`hts_kor_isnm`)을 캐시해 매핑을 보완(선택적, 실패해도 정적 매핑으로 동작).
- 백엔드 조회 응답(positions/trades/movers)에 `name` 필드 추가.

## 6. 백엔드 조회 확장 (`dashboard/backend/`)

기존 REST 유지 + 확장. 순수 조회(읽기 전용), 계약은 프론트 `types.ts`와 1:1.

### 6.1 일일 현황판 데이터 — 신규 `GET /api/dashboard`
- **시장 movers**: 유니버스(추적 종목)의 최근 거래일 등락률 상위/하위 5(시장별 KR·US). `daily_bars` 최근 2봉으로 계산. 데이터 범위 한정(추적 유니버스, "전체 시장" 아님)을 응답 메타에 표기.
- **포트폴리오 요약**: 3캐릭터 각 오늘 손익(전일 대비 총자산 변화), 보유종목 수, 현금 비중.
- **보유 베스트/워스트**: 각 캐릭터 보유종목 중 오늘 등락 최고/최저.
- **최근 체결**: 전 캐릭터 통합 최신 N건(캐릭터·종목명·사유·손익).

### 6.2 신호 표시 데이터 — 거래 응답 확장
- **신규 `simcore/signal_display.py`** (엔진 옆, config.scores 소비):
  - `SIGNAL_NAMES: dict[str, str]` — 코드→초보용 한글명(예: `"G1": "골든크로스"`, `"G7": "신고가 돌파"`, `"R1": "데드크로스"`).
  - `stars(code) -> int` — 점수(1~5)를 별점으로.
  - `summarize(fired_codes, green_score, side) -> str` — "강한 상승추세 + 신고가 돌파 + 거래량 급증 → 강력 매수 신호 (85점/A등급)" 식 한 줄 요약. 등급은 점수 구간(A/B/C) 매핑.
  - `detail(fired_codes) -> list[{code, name, category, stars}]` — 펼침용.
- trades 엔드포인트 응답에 `signal_summary`(한 줄)·`signal_detail`(배열)·`green_score`/`red_score` 추가. 프론트는 그대로 렌더.

### 6.3 범용형 불일치
- 4.의 시딩으로 데이터 정합이 확보되면 자동 해소. 백엔드 `card_summary`/`equity_series` 로직은 이미 동일 스냅샷 기반이므로 수정 불필요(시딩 정합성 문제였음).

## 7. 프론트 개편 (`dashboard/frontend/`)

기존 디자인 토큰·팔레트(dataviz 검증, 상승빨강/하락파랑, 라이트/다크)·컴포넌트 재사용.

### 7.1 상단바
- "simcore 모의투자" 브랜드 텍스트 제거. 전체자산·실시간 연결 점만 유지(또는 중립적 아이콘).

### 7.2 메인 = 일일 현황판 (초보 친화, 꽉 채움)
- 레이아웃: **좌측 캐릭터 열(1열 3행 카드)** + 우측 현황판 영역. (또는 상단 카드 유지 — 반응형으로 좁으면 세로.)
- 현황판 섹션:
  1. **오늘의 시장** — KR·US 상승 top5 / 하락 top5(종목명 + 등락률 칩). 데이터 범위 안내 문구(작게).
  2. **내 캐릭터 요약** — 3캐릭터 오늘 손익·보유수·현금비중(카드가 이 역할 겸할 수 있음).
  3. **보유종목 미리보기** — 캐릭터별 보유 상위 몇 종목(종목명·평가손익 색).
  4. **최근 체결** — 통합 최신 체결 리스트(종목명·사유 한글·손익).
- 문구는 초보 친화(예: "오늘 가장 많이 오른 종목", "내가 들고 있는 종목"). 전문용어 최소화, 필요한 곳엔 작은 도움말(툴팁).
- **화면에 요청/설명용 라벨("사용자 친화 UI" 등) 직접 노출 금지.**

### 7.3 상세 페이지
- 보유종목/거래내역 표: **종목명 우선 표시**(코드는 작게 보조 또는 툴팁). 시장 태그·통화 인지 유지.
- **신호 표시(TradesTable 개편)**: 각 거래 행에
  - 🟢/🔴 + **한 줄 요약**(`signal_summary`) + 점수/등급.
  - "펼쳐보기" → 개별 신호 `이름 + 별점(★)` 리스트(`signal_detail`).
  - 기존 "G1/R2" 코드 배지는 펼침 내부의 보조 정보로만(또는 제거).
- 자산곡선·성과지표는 유지(범용형 값 정합만 데이터로 해결).

## 8. 컴포넌트/파일 (경계)

- `dashboard/scripts/seed_from_replay.py` — 리셋+적재.
- `simcore/names.py` — 종목명 정적 매핑 + `display_name`.
- `simcore/signal_display.py` — 신호 한글명·별점·요약·상세(순수, config.scores 소비).
- `dashboard/backend/` — `/api/dashboard` 라우트, movers·portfolio 요약 쿼리, trades 응답에 signal_summary/detail·name 병합, positions/trades에 name.
- `dashboard/frontend/src/`:
  - `pages/Main.tsx` — 현황판 레이아웃.
  - 신규 컴포넌트: `MarketMovers`, `HoldingsPreview`, `RecentTrades`(공용), 캐릭터 열.
  - `components/TradesTable.tsx` — 한 줄 요약 + 펼침(이름·별점).
  - `components/PositionsTable.tsx` — 종목명.
  - `components/format.ts` — 이름/요약 포맷 헬퍼(또는 백엔드 제공값 사용).
  - `types.ts` — 신규 필드 미러.

## 9. 오류/엣지

- 종목명 매핑 미스 → 코드 폴백(깨지지 않음).
- movers 데이터 부족(거래일 1개뿐) → 빈 상태 안내.
- KIS 미연결(오프라인 데모) → 정적 매핑·시딩 데이터로 정상 동작(현재가 stale 배지 기존 유지).
- 빈 DB(시드 전) → 기존 빈 상태 UI.

## 10. 테스트 전략

- **백엔드**: `signal_display`(요약/별점/등급 경계), `names.display_name`(매핑/폴백), `/api/dashboard`(movers 계산·포트폴리오 요약) 단위/통합. trades 응답에 신규 필드 존재.
- **시드 스크립트**: 적재 후 card_summary.total_asset == equity_series 마지막값(범용형 불일치 회귀 방지) 검증.
- **프론트**: format/summary 렌더 vitest, 주요 컴포넌트 스모크, 빌드(tsc strict)+기존 vitest 유지.
- 스모크: uvicorn 기동 → 메인 현황판·상세(3캐릭터)·신호 펼침·라이트/다크 렌더 확인.

## 11. 완료 기준

1. `seed_from_replay.py --force` 실행 시 DB가 v2 6개월 결과로 채워지고, **범용형 카드 총자산 == 상세 곡선 마지막값**.
2. 메인에 "simcore 모의투자" 텍스트 없음. 시장 movers + 포트폴리오 현황판이 화면을 채움. 캐릭터별 보유 노출.
3. 상세에서 종목명 표시, 거래내역이 한 줄 요약 + 펼치면 이름·별점.
4. 프론트 빌드+vitest, 백엔드 pytest 통과. 스모크 렌더 확인.

## 12. 후속

- 서브프로젝트 6: 전략 튜닝(시장지수 추세 필터 = 하락장 가드) + A/B 리플레이.
- KIS 종목명 캐시 정교화, benchmark_delta 실계산(기존 후속).
