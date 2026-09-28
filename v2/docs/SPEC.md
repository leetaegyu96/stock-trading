# stock-trading **v2** 스펙 — 회원제 수동매수 + 매도벽 모의투자

> 버전 0.1 · 2026-09-28 작성. 이 문서가 **구현의 계약서**다. 서브에이전트는 여기 정의된
> 스키마·API·규칙을 그대로 구현하며, 어긋나면 코드가 아니라 이 문서를 먼저 고친다.

---

## 0. v1 과 무엇이 다른가

| | **v1** (`/stock-v1/`) | **v2** (`/stock-v2/`) |
|---|---|---|
| 매수 | 청신호 18점 + 3관문 → **기계가 자동** | **사람이 종목·수량 선택** |
| 매도 | 적신호 점수 / 손절 / 트레일링 → 기계가 자동 | ① 사람이 수량 지정 ② **매도벽**(−n% / +m%) 도달 시 자동 |
| 계정 | 없음. 고정 캐릭터 3개 | **회원가입·로그인**, 회원당 캐릭터 2개 |
| 캐릭터 | 국내형 / 해외형 / 범용형 | **국내 / 해외** 2개, 각 1억원 |
| 지향 | 전략 백테스트·검증 | **주식 초보의 모의투자 경험** |

v1 은 "왜 기계가 이걸 샀나"를 설명하는 도구였고, v2 는 "내가 사고, 내가 정한 선에서
자동으로 팔린다"를 경험하는 도구다. **v1 의 신호 점수 체계(G/R 코드, buy_gate, 트레일링
티어)는 v2 에 존재하지 않는다.**

재사용하는 것: KIS 클라이언트, 종목명 매핑, 디자인 토큰(`theme.css`), `Sparkline`,
비용 모델(수수료·세금·환전). 재사용하지 않는 것: `simcore.signals`, `simcore.engine`,
`simcore.replay` 전부.

---

## 1. 배치 구조

```
~/stock-trading/                 (같은 리포)
├── simcore/                     v1 엔진 — v2 는 kis_client·names·costs 만 import
├── dashboard/                   v1 대시보드 (:8020, /stock-v1/)
└── v2/
    ├── docs/SPEC.md             이 문서
    ├── docs/PLAN.md             구현 계획
    ├── backend/                 FastAPI (:8030)
    │   ├── app.py               앱·라우터 조립 + 정적 서빙
    │   ├── db.py                SQLAlchemy 엔진/세션
    │   ├── models.py            ORM
    │   ├── schemas.py           Pydantic I/O
    │   ├── auth.py              회원가입·로그인·세션
    │   ├── market.py            KIS 시세 + 종목 리스트 캐시
    │   ├── trading.py           매수·수동매도 (회계 불변식)
    │   ├── sellwall.py          매도벽 평가·자동매도
    │   ├── scheduler.py         장중 1분 감시 잡
    │   └── settings.py          env
    ├── frontend/                React + Vite
    └── tests/                   pytest (백엔드) · vitest (프론트)
```

- **DB**: 기존 `stock-pg` 컨테이너(127.0.0.1:5433)에 **별도 데이터베이스 `simcore_v2`**.
  v1 의 `simcore` DB 와 테이블을 섞지 않는다. 테스트는 `simcore_v2_test`.
- **서비스**: `systemd --user` `stock-v2.service` → uvicorn `v2.backend.app:app` :8030.
- **공개 URL**: `https://ltk.golab.acego.net/stock-v2/` (nginx 서브패스, 프리픽스 strip).
  프론트는 반드시 `VITE_BASE_PATH=/stock-v2/` 로 빌드.

---

## 2. 도메인 모델

### 2.1 금액·수량 규칙 (전 계층 공통)

- **금액은 정수 최소단위로 저장한다.** KRW = 원(정수), USD = **센트(정수)**.
  부동소수 누적 오차로 잔고가 어긋나는 것을 원천 차단한다. API 경계에서만 사람이 읽는
  단위로 변환한다.
- **수량은 정수.** 소수점 주식 없음.
- 캐릭터는 **하나의 통화만** 쓴다 — 국내=KRW, 해외=USD. v1 의 범용형처럼 환전이 오가는
  캐릭터는 두지 않는다(v1 에서 왕복 환전으로 자본의 5%p 가 샜다).
- 해외 캐릭터의 초기 자금: 1억 KRW 를 **계정 생성 시점 환율로 1회 환전**해 USD 로 보유.
  이후 환전 없음. 표시용 원화 환산은 조회 시점 환율로 계산하되 **저장하지 않는다**.

### 2.2 테이블

```
users
  id            BIGSERIAL PK
  email         CITEXT UNIQUE NOT NULL      -- 로그인 ID
  password_hash TEXT NOT NULL               -- argon2id
  nickname      TEXT NOT NULL
  created_at    TIMESTAMPTZ NOT NULL
  last_login_at TIMESTAMPTZ

accounts                                    -- = 캐릭터
  id            BIGSERIAL PK
  user_id       BIGINT FK users ON DELETE CASCADE
  kind          TEXT NOT NULL               -- 'KR' | 'US'
  currency      TEXT NOT NULL               -- 'KRW' | 'USD'
  cash_minor    BIGINT NOT NULL             -- 원 또는 센트
  seed_minor    BIGINT NOT NULL             -- 최초 투입액(수익률 분모)
  created_at    TIMESTAMPTZ NOT NULL
  UNIQUE (user_id, kind)                    -- 회원당 종류별 1개

positions
  id            BIGSERIAL PK
  account_id    BIGINT FK accounts ON DELETE CASCADE
  symbol        TEXT NOT NULL
  quantity      INT  NOT NULL CHECK (quantity > 0)
  avg_price_minor BIGINT NOT NULL           -- 매수 수수료 포함 평단
  opened_at     TIMESTAMPTZ NOT NULL
  UNIQUE (account_id, symbol)               -- 같은 종목은 한 포지션으로 합산

sell_rules                                  -- 매도벽
  id            BIGSERIAL PK
  position_id   BIGINT FK positions ON DELETE CASCADE UNIQUE
  stop_loss_pct  NUMERIC(6,3)               -- 예: -5.000 (NULL=미설정)
  take_profit_pct NUMERIC(6,3)              -- 예: +15.000 (NULL=미설정)
  quantity      INT NOT NULL                -- 발동 시 팔 수량
  active        BOOLEAN NOT NULL DEFAULT TRUE
  created_at    TIMESTAMPTZ NOT NULL
  updated_at    TIMESTAMPTZ NOT NULL

trades                                      -- 체결 원장 (append-only)
  id            BIGSERIAL PK
  account_id    BIGINT FK accounts
  symbol        TEXT NOT NULL
  side          TEXT NOT NULL               -- 'BUY' | 'SELL'
  quantity      INT  NOT NULL
  price_minor   BIGINT NOT NULL             -- 체결 단가
  fee_minor     BIGINT NOT NULL
  tax_minor     BIGINT NOT NULL
  gross_minor   BIGINT NOT NULL             -- quantity * price
  net_minor     BIGINT NOT NULL             -- 현금 증감(부호 포함)
  realized_pnl_minor BIGINT                 -- SELL 만. 비용 차감 후
  reason        TEXT NOT NULL               -- 'MANUAL' | 'AUTO_STOP_LOSS' | 'AUTO_TAKE_PROFIT'
  sell_rule_id  BIGINT                      -- 자동매도 시 근거 규칙
  executed_at   TIMESTAMPTZ NOT NULL

equity_snapshots                            -- 자산곡선
  id            BIGSERIAL PK
  account_id    BIGINT FK accounts
  ts            TIMESTAMPTZ NOT NULL
  equity_minor  BIGINT NOT NULL             -- 현금 + 평가액
  UNIQUE (account_id, ts)

event_log                                   -- "모든 건 기록을 남긴다"
  id            BIGSERIAL PK
  user_id       BIGINT
  account_id    BIGINT
  kind          TEXT NOT NULL               -- SIGNUP/LOGIN/BUY/SELL/RULE_SET/RULE_CANCEL/
                                            -- AUTO_SELL_FIRED/AUTO_SELL_SKIPPED/PRICE_STALE
  detail_json   JSONB NOT NULL
  ts            TIMESTAMPTZ NOT NULL
```

**불변식** (모든 쓰기 후 검사, 위반 시 트랜잭션 롤백):
1. `cash_minor >= 0`
2. `positions.quantity > 0` — 0 이 되면 행 삭제(+ 연결된 sell_rule CASCADE)
3. 계정별 `cash + Σ(포지션 평가액)` = 직전 equity ± 이번 체결 net — 원장과 잔고가 일치
4. `trades` 는 **수정·삭제 불가**(append-only)

### 2.3 비용 모델 (v1 과 동일)

| 시장 | 매수 수수료 | 매도 수수료 | 매도 세금 |
|---|---|---|---|
| KR | 0.015% | 0.015% | 0.15% (증권거래세) |
| US | 0.09% | 0.09% | — |

- 계산 순서: `gross = qty × price` → `fee = round(gross × rate)` → `tax`(매도·KR만)
- 매수 시 필요 현금 = `gross + fee`, 매도 시 입금 = `gross − fee − tax`
- 반올림은 **최소단위로 내림이 아닌 반올림(round-half-up)**, 모든 계산은 정수 연산

---

## 3. 인증

- **비밀번호**: argon2id 해시(`argon2-cffi`). 평문·복호화 가능 형태로 저장 금지.
- **세션**: JWT 를 **httpOnly + SameSite=Lax + Secure 쿠키**로 발급(유효기간 7일).
  로컬스토리지에 토큰을 두지 않는다(XSS 노출 차단).
- **회원가입 시** 트랜잭션 1건으로 `users` 1행 + `accounts` 2행(KR/US) 생성.
  - 국내: `cash_minor = 100_000_000` (1억 원)
  - 해외: `cash_minor = round(100_000_000 / fx × 100)` 센트 — 환전 수수료 0.1% 차감
  - 실패 시 전부 롤백(계정만 있고 캐릭터 없는 상태 금지)
- **레이트 리밋**: 로그인 실패 시 IP+계정 기준 5회/5분 초과하면 429.
- 비밀번호 최소 10자. 이메일 형식 검증.
- **모든 거래 API 는 세션 필수**이며, 요청의 `account_id` 가 **그 세션 사용자 소유인지
  반드시 검증**한다(수평 권한 상승 차단). 이 검사는 테스트로 고정한다.

---

## 4. 시세·종목 데이터

### 4.1 소스
v1 의 `simcore.live.kis_client.KisClient` 재사용.
- `current_price(market, symbol) -> float`
- `daily_bars(market, symbol, start, end) -> DataFrame[open,high,low,close,volume]`

**KIS 토큰은 v1 과 별도 저장소**(`simcore_v2.kis_token`)를 쓴다 — 같은 앱키로 두 서비스가
토큰을 동시 갱신하면 서로를 무효화할 수 있다. 호출량을 줄이려 아래 캐시를 둔다.

### 4.2 종목 리스트 (매수 화면)
- **국내**: KIS 시가총액 상위 30 (`market_cap_ranking`)
- **해외**: S&P500 상위 30 (`simcore.universe.sp500`)
- 각 종목에 대해 제공:

| 필드 | 내용 |
|---|---|
| `symbol` / `name` | 코드 / 한글·영문명 (`simcore.names`) |
| `price` | 현재가 |
| `change_pct` | 전일 종가 대비 등락률 |
| `spark7` | **최근 7거래일 종가 배열** — 스파크라인용 |
| `week_change_pct` | 7일 전 대비 등락률 |
| `volume` | 당일 거래량 |
| `volume_vs_avg` | 20일 평균 거래량 대비 배수 (거래 활발도) |
| `high_52w` / `low_52w` | 52주 고저 — 현재 위치를 게이지로 표시 |
| `stale` | 실시간 조회 실패해 캐시값을 쓴 경우 true |

**캐시**: 종목 리스트는 **60초 TTL** 인메모리 캐시. 일봉(7일·52주)은 **당일 1회** 조회 후
날짜가 바뀔 때까지 재사용. 장 마감 후에는 갱신하지 않는다.

**초보 친화 보조 지표**(점수·추천이 아니라 **사실 제시**):
- "최근 7일 +3.2%" 같은 평문 요약
- 거래량이 평소의 몇 배인지 ("평소의 2.1배")
- 52주 범위 내 현재 위치 게이지
- ❗ **매수 추천·신호 점수는 표시하지 않는다.** v2 는 사용자가 판단하는 도구다.

---

## 5. 매수

### 5.1 규칙
1. 로그인 사용자의 캐릭터(KR 또는 US) 선택 → 그 시장의 종목만 매수 가능
2. 종목 + 수량 입력 → 예상 금액(수수료 포함) 미리보기 → 확정
3. 체결가 = **주문 시점 현재가**(모의투자이므로 즉시 체결, 슬리피지 0)
4. `필요현금 = gross + fee` 가 `cash_minor` 초과면 거부(`INSUFFICIENT_CASH`)
5. 같은 종목 재매수 시 **기존 포지션에 합산**하고 평단을 가중평균으로 갱신
   - `new_avg = (old_qty × old_avg + gross + fee) / (old_qty + qty)`
   - 평단에 매수 수수료를 포함해, 손익 계산이 실제 투입액 기준이 되게 한다
6. **장 시간 외에도 매수 가능**(모의투자). 다만 마지막 체결가 기준임을 UI 에 명시하고
   `stale` 플래그를 체결 기록에 남긴다.

### 5.2 동시성
같은 계정에 대한 주문은 **계정 행 `SELECT ... FOR UPDATE`** 로 직렬화한다. 두 탭에서
동시에 주문해 잔고가 음수가 되는 일을 막는다. 이 시나리오는 테스트로 고정한다.

---

## 6. 매도

### 6.1 수동 매도
- 보유 목록에서 종목 선택 → 수량 지정(최대 = 보유 수량) → 확정
- 체결가 = 주문 시점 현재가. 입금 = `gross − fee − tax`
- 실현손익 = `(체결가 − 평단) × 수량 − fee − tax`
- 전량 매도 시 포지션 행 삭제 + 연결된 매도벽도 함께 삭제(CASCADE)
- 부분 매도 시 **평단은 유지**하고 수량만 차감

### 6.2 매도벽 (자동매도) — v2 의 핵심
사용자가 포지션별로 **손절선(−n%)** 과 **익절선(+m%)** 을 설정한다. 둘 다 선택이며,
하나만 설정해도 된다.

**기준선**: **평단(`avg_price_minor`) 대비 퍼센트.** 매수가가 아니라 평단인 이유는
추가 매수 시 기준이 자연스럽게 따라가야 하기 때문이다.

```
손절 발동가 = avg_price × (1 + stop_loss_pct/100)     예: 평단 10,000 · −5%  → 9,500
익절 발동가 = avg_price × (1 + take_profit_pct/100)   예: 평단 10,000 · +15% → 11,500
```

**판정**: 감시 시점 현재가 `p` 에 대해
- `stop_loss_pct` 설정 & `p <= 손절 발동가` → **손절 발동**
- `take_profit_pct` 설정 & `p >= 익절 발동가` → **익절 발동**
- 둘 다 동시 충족(급변동으로 한 틱에 양쪽을 넘긴 경우) → **손절 우선**(보수적)

**체결가**: **발동 시점의 현재가 `p`** 로 체결한다. 발동선 가격이 아니다.
- 이유: 모의투자에서 "설정한 가격에 정확히 체결"은 현실과 다르다. 실제로는 갭이나
  급락으로 설정선보다 불리하게 체결되는데, 그 경험을 왜곡 없이 보여주는 편이 낫다.
- UI 는 발동선과 실제 체결가를 **나란히 표시**해 차이를 학습 포인트로 만든다.

**수량**: `sell_rules.quantity` (기본 = 설정 시점 보유 전량). 보유 수량이 그보다 적어졌으면
남은 전량을 판다.

**발동 후**: 규칙은 `active=false` 로 내리고, `trades` 에 `reason='AUTO_STOP_LOSS'` 또는
`'AUTO_TAKE_PROFIT'` + `sell_rule_id` 를 기록한다. `event_log` 에 발동선·체결가·괴리를 남긴다.

**유효성**:
- `stop_loss_pct` 는 음수, `take_profit_pct` 는 양수여야 한다
- `-99 <= stop_loss_pct < 0 < take_profit_pct <= 900` 범위
- 둘 다 NULL 이면 규칙을 만들지 않는다(있던 규칙은 삭제)

### 6.3 감시 잡
- **장중 1분 간격**. KR 09:00~15:30 KST, US 09:30~16:00 ET, 주말 제외.
- 대상: `sell_rules.active = true` 인 포지션의 **종목 집합**(중복 제거) → 종목당 1회 조회.
  같은 종목을 여러 사용자가 들고 있어도 API 호출은 1회다.
- 시세 조회 실패 종목은 **건너뛴다**(마지막 종가로 자동매도하지 않는다 — 오래된 가격으로
  남의 돈을 파는 것은 하지 않는다). `event_log` 에 `PRICE_STALE` 기록.
- 처리 중 예외는 **그 규칙만** 스킵하고 나머지를 계속한다.
- **멱등**: 이미 `active=false` 인 규칙은 건너뛴다. 감시 잡과 수동 매도가 같은 포지션을
  동시에 건드리지 않도록 계정 행 잠금을 공유한다.

---

## 7. API

모두 `/api` 프리픽스. 인증 필요한 엔드포인트는 🔒.

### 인증
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/signup` | `{email, password, nickname}` → 회원 + 캐릭터 2개 생성, 세션 쿠키 |
| POST | `/api/auth/login` | `{email, password}` → 세션 쿠키 |
| POST | `/api/auth/logout` 🔒 | 쿠키 만료 |
| GET | `/api/auth/me` 🔒 | `{id, email, nickname}` |

### 계좌·보유
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/accounts` 🔒 | 캐릭터 2개 요약 — 현금·평가액·총자산·수익률·보유수 |
| GET | `/api/accounts/{id}` 🔒 | 상세 + 자산곡선 |
| GET | `/api/accounts/{id}/positions` 🔒 | 보유 목록(평단·현재가·평가손익·매도벽 상태 포함) |
| GET | `/api/accounts/{id}/trades` 🔒 | 거래 내역(페이지네이션) |
| GET | `/api/accounts/{id}/events` 🔒 | 활동 로그 |

### 시세
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/market/{kind}/stocks` 🔒 | `kind`=KR\|US. 종목 리스트(§4.2 필드) |
| GET | `/api/market/{kind}/stocks/{symbol}` 🔒 | 단일 종목 상세 + 30일 일봉 |

### 주문
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/accounts/{id}/buy` 🔒 | `{symbol, quantity}` → 체결 |
| POST | `/api/accounts/{id}/sell` 🔒 | `{symbol, quantity}` → 체결 |
| PUT | `/api/positions/{id}/sell-rule` 🔒 | `{stop_loss_pct?, take_profit_pct?, quantity?}` |
| DELETE | `/api/positions/{id}/sell-rule` 🔒 | 매도벽 해제 |

**오류 규약**: `{"error": {"code": "INSUFFICIENT_CASH", "message": "사람이 읽는 한국어 설명"}}`
- 코드: `UNAUTHORIZED` `FORBIDDEN` `NOT_FOUND` `INSUFFICIENT_CASH` `INSUFFICIENT_QUANTITY`
  `INVALID_QUANTITY` `INVALID_SELL_RULE` `PRICE_UNAVAILABLE` `MARKET_MISMATCH` `RATE_LIMITED`
- message 는 **초보가 이해할 한국어**로. 예: "현금이 부족합니다. 8,320,000원이 필요한데
  잔고는 5,100,000원입니다."

---

## 8. 화면 (UI/UX)

디자인은 v1 의 토큰(`theme.css`)을 그대로 쓴다 — 한국 증권 관례(**상승=빨강, 하락=파랑**),
Pretendard, 라이트/다크 대응.

### 8.1 화면 목록

| # | 화면 | 핵심 |
|---|---|---|
| 1 | 로그인 / 회원가입 | 한 화면에서 탭 전환. 가입 즉시 캐릭터 2개 생성 안내 |
| 2 | **홈** | 캐릭터 2장 카드(총자산·수익률·자산곡선 스파크라인) + 오늘의 변화 |
| 3 | **종목 탐색**(매수) | 카드/표 토글. 종목명·현재가·등락률·**7일 스파크라인**·거래량 배수·52주 위치 |
| 4 | 종목 상세 | 30일 차트 + 지표 + **매수 패널**(수량 스테퍼, 예상금액 실시간 계산) |
| 5 | **보유 종목** | 포지션 카드: 평단/현재가/평가손익 + **매도벽 시각화** + 매도 버튼 |
| 6 | 매도벽 설정 | 슬라이더로 −n%/+m% 조절, **발동가를 즉시 원화로 환산 표시** |
| 7 | 거래 내역 | 매수/매도/자동매도 필터, 자동매도는 발동 근거 함께 표시 |

### 8.2 초보 친화 원칙
- **숫자 옆에 항상 의미를 적는다.** "-320,000원" 이 아니라 "-320,000원 (-3.2%)"
- **전문용어를 쓰지 않는다.** '손절' → "이만큼 떨어지면 팔기", '익절' → "이만큼 오르면 팔기"
- **매도벽은 그림으로 보여준다.** 현재가가 두 선 사이 어디에 있는지 막대로 표시:
  ```
  손절 9,500 ┃━━━━━━━●━━━━━━━━━━━┃ 익절 11,500
            평단 10,000  현재 10,240 (+2.4%)
  ```
- **되돌릴 수 없는 행동은 확인 단계를 둔다** — 매수·매도 확정 전 요약 모달
- 빈 상태(보유 없음)에 다음 행동을 안내한다
- 모든 금액은 천 단위 구분 + `tabular-nums`

### 8.3 차트
- 7일 추이: `Sparkline`(v1 컴포넌트 복사)
- 30일 상세: 선 차트 + 거래량 막대. 축 라벨·툴팁 포함, 라이트/다크 토큰 사용
- 자산곡선: 원금선(수평 점선) 대비 현재 위치가 보이게

---

## 9. 테스트 (goal)

**goal = 아래가 전부 통과하고, 공개 URL 에서 가입→매수→매도벽→자동매도가 실제로 동작.**

### 9.1 백엔드 (pytest)
- **회계 불변식**: 매수/매도 후 `cash + 평가액` 이 원장과 일치. 현금 음수 불가
- **평단 가중평균**: 추가 매수 시 평단이 수수료 포함으로 정확히 갱신
- **부분 매도**: 평단 유지, 수량만 차감. 전량 매도 시 포지션·매도벽 삭제
- **비용**: KR 매도 시 거래세 0.15% 부과, US 는 미부과
- **매도벽 판정**: 손절/익절 경계값(정확히 같은 가격), 둘 다 충족 시 손절 우선
- **매도벽 체결가**: 발동선이 아니라 현재가로 체결됨
- **시세 실패**: 자동매도가 **발동하지 않고** `PRICE_STALE` 이 기록됨
- **권한**: 남의 `account_id`·`position_id` 로 요청 시 403
- **동시성**: 같은 계정 동시 매수 2건 → 잔고 음수 없음
- **인증**: 비밀번호 해시 저장, 약한 비밀번호 거부, 로그인 실패 레이트 리밋
- **가입 원자성**: 캐릭터 생성 실패 시 사용자도 롤백
- **멱등**: 이미 발동한 규칙 재평가 시 중복 매도 없음

### 9.2 프론트 (vitest)
- 금액·등락률 포맷, 상승/하락 색상 규칙
- 매도벽 게이지가 현재가 위치를 올바르게 계산
- 매수 예상금액(수수료 포함) 계산
- 잔고 초과 수량 입력 시 버튼 비활성 + 안내

### 9.3 통합 (E2E 시나리오)
가입 → 캐릭터 2개 확인(각 1억) → 국내 종목 매수 → 보유 목록 노출 →
매도벽 −5%/+15% 설정 → 가격을 익절선 위로 주입 → 감시 1틱 → **자동 매도 체결** →
거래 내역에 `AUTO_TAKE_PROFIT` 기록 → 현금·수익률 반영 확인.

---

## 10. 비범위 (이번에 하지 않는 것)

- 실제 주문(항상 모의). 실주문 코드 경로를 만들지 않는다
- 지정가·예약 주문(시장가 즉시 체결만)
- 공매도·신용·파생
- 소셜 기능(랭킹·공유)
- 비밀번호 재설정 메일 발송(자리만 만들고 미구현)
- v1 데이터 마이그레이션 — v2 는 빈 상태에서 시작한다
