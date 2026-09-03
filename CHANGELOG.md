# Changelog

이 프로젝트의 모든 주요 변경사항을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/), 버전은 [SemVer](https://semver.org/)를 따른다.

상세 패치노트는 `docs/patch-notes/vX.Y.Z.md` 참조.

## v1.18.0 — 2026-09-02

범용형 왕복 환전 제거 — 사후분석 처방 중 현재 운영 구성에서 유효한 마지막 항목.

### Fixed
- US 매도마다 달러 전액을 원화로 되돌리고 다음 매수에서 되돌리던 **왕복 0.2%** 제거. 라이브 6주 약 160만원, 3.2년 총 회전액 기준 초기자본 5.0%p 규모 (PR #68)
  - `Portfolio.buying_power`(양 통화 합산 여력) · `convert_to_krw` · `ensure_cash`(부족분만 환전)
  - `Engine._sell` 자동 전액 환전 제거, `_buy` 는 보유 통화 우선 후 부족분만 환전
  - `withdraw` 는 원화 부족 시 부족분을 달러에서 메움(왕복 제거로 달러를 보유하게 되므로 필요한 회귀 방지)
- `tests/live/test_settings.py` 가 실제 `.env`(KIS_ENV=paper)를 읽어 깨지던 격리 문제(`_env_file=None`)

### 검증
- 범용형 3.2년 현행규칙 −5.4%→**+2.7%**, 현재 운영구성 +89.0%→**+90.2%**, 2026년 8개월 +17.1%→**+18.1%**
- 대조군 국내형·해외형은 단일 통화라 소수점까지 불변 — 변경 범위 정확
- 회수액이 5.0%p 추정보다 작은 것은 시장 간 순이동분은 어차피 환전해야 하고 왕복 중복분만 사라지기 때문
- 테스트 20건 추가, 전체 **468 passed, 실패 0**(스위트가 완전히 초록이 된 첫 버전)

## v1.17.0 — 2026-09-02

리플레이에 장중 경로 주입 — 장중 자동매매를 검증할 수 있게 된 첫 버전. 첫 검증 결과는 "계속 꺼둘 것".

### Added
- `simcore/intraday_path.py` — 일봉 OHLC → 장중 슬라이스 근사. `low_first`(O→L→H→C, 기본)/`high_first` 경로를 등속 샘플링, 슬라이스는 k/(n+1) 지점(구간 내부)만. high/low 는 샘플 지점이 아닌 **지나간 구간**의 극값(두 스캔 사이의 저가를 놓치면 손절이 어긋난다)
- `replay.IntradayReplayOptions`(slices/order/session_start/scan_minutes) — `rules.intraday_enabled=True` 일 때만 적용
- CLI `--intraday-slices` / `--intraday-order`
- 테스트 29건, 전체 452 passed. `docs/trading-rules.md` §17-2

### 검증 결과
- 현행 구성에서 장중 ON vs OFF (경로 양방향 폭): **2026년 8개월 국내형 −17.98%~−17.61%p 악화**(두 경로가 좁게 일치 → 강건), 해외형 −1.80%~−0.08%, 범용형 −2.86%~+2.32%(판단 불가)
- 라이브와 같은 6주만 보면 부호가 뒤집힌다(+0.88~+4.69%) — 짧은 구간 하나로 판단하면 반대 결론이 나온다는 실례
- → `INTRADAY_ENABLED=0` 유지

### 한계
- 일봉에 경로 정보가 없어 경로는 '가정'. 메커니즘·방향성·상대비교는 검증되지만 **정확한 손익은 재현되지 않는다**(라이브 구간에서 매도 폭증 signature 는 재현되나 금액은 다름). 한쪽 order 값만 인용 금지
- 비용이 슬라이스 수에 선형. 4~8 권장
- `intraday_enabled=False` 면 기존 결과와 완전 동일(테스트로 고정)

## v1.16.1 — 2026-09-02

장중 잠정봉의 거래량 왜곡 차단 (v1.16.0 사후분석에서 지목한 버그).

### Fixed
- `on_intraday` 잠정봉의 당일 **누적** 거래량이 전일/20일평균의 **완성** 거래량과 직접 비교되던 문제. R24(거래량 없는 상승, 적 4점)가 22.7%→49.5%로 상시 점등돼 전량매도를 유발했다. `signals.VOLUME_SCALE_DEPENDENT`={G5,G23,R5,R24} 를 `fired_at_provisional()` 로 미발화 처리. 마감 경로·리플레이는 불변 (PR #62)
- 대상은 실측으로 선정(3,278 종목일): 판정 뒤집힘 R24 26.8% / R5 3.3% / G5 3.0% / G23 0.7%, 나머지 33개 0.0%. OBV·VWAP은 불변이라 제외하지 않음
- 한계: 오차가 사라지지 않고 부호가 뒤집힌다(전량매도 발동률 +11.4%p 과매도 → −13.3%p 과소매도). 후자는 마감 확정봉 판정이 바로잡고 매수 게이트는 8.18%로 동일. 완전 해결엔 시간대별 거래량 프로파일 + 장중 리플레이 하니스 필요

### Added
- 테스트 16건 + 테스트 DB(`simcore_test`) 구성으로 기존 스킵 105건 실행 → 423 passed
- `docs/trading-rules.md` §17-1

### 운영 영향
- `INTRADAY_ENABLED=0` 이라 현재 매매 동작 변화 없음. 장중매매 재활성화 선결 과제 해소

## v1.16.0 — 2026-09-02

라이브 6주 손실 사후분석과 처방. 적신호 점수 매도를 끄고 손절/트레일만 남기는 모드를 토글로 추가하고, 운영 계좌를 1억원으로 재시작.

### Added
- `TradeRules.signal_sell_enabled`(기본 True) — 점수 매도(9점 부분/11점 전량) on/off. False 여도 강제매도(R7·R10·R18·R5+R23)와 매수 경로는 유지 ("손절/트레일만" 모드). trading-rules §7-1 (PR #59)
- `SIGNAL_SELL_ENABLED` / `MAX_POSITIONS` 환경변수 — 코드 수정 없이 .env 로 전환 (PR #59)
- 손실 사후분석 리포트 `docs/reviews/2026-09-02-live-loss-autopsy.html` (PR #58)
- 테스트 23건(강제매도 생존·트레일링 래칫·양 경로 억제·매수 무영향·env 배선)

### Changed
- 운영 설정: `INTRADAY_ENABLED` 1→0, `SIGNAL_SELL_ENABLED=false`, `MAX_POSITIONS=10`
- 운영 계좌 초기화 — 상태·이력 테이블을 비우고 세 캐릭터에 각 1억원 재시딩(일봉 캐시·유니버스·KIS 토큰 보존)

### 검증
- 신규 플래그가 기존 검증 방식(`sell_*_min=999`)과 3.2년 리플레이에서 완전 일치
- 3구간 워크포워드 9칸 중 수익률 7칸·MDD 8칸 우세. 임계값 튜닝(13/16/26)은 과적합으로 미채택
- 한계: 동일가중 B&H(KR +412%/US +97%, 생존편향 포함)는 못 넘음 — 기존 규칙 대비 개선이지 알파의 증명이 아님

## v1.15.1 — 2026-07-21

스캔 상태 스트립 표시 개선: "N분 전" 상대시간 + KST/ET 타임존 라벨.

### Added
- 스캔 스트립에 "N분 전"(방금 전/N분 전/N시간 전) 상대시간 표시(30초마다 갱신) + 시장 벽시계 옆 KST/ET 라벨.

### Changed
- `/api/scan-status`에 `tz`(KST/ET)·`ts_epoch_ms`(절대 시각) 추가 — 시장 벽시계로 저장된 스캔 시각을 시장 tz로 복원해 브라우저 tz와 무관하게 정확한 "N분 전"을 계산. US는 DST 반영.

### 검증
- pytest 386 passed(+1), 프론트 vitest 137 passed + build 통과, 회귀 0. 상세: `docs/patch-notes/v1.15.1.md`.

## v1.15.0 — 2026-07-21

장중 스캔 관측성: 스캔이 돌고 있는지·종목별로 왜 샀/안 샀/팔았는지 대시보드에서 실시간으로 보인다.

### Added
- 스캔 하트비트(`intraday_scan` 테이블 + `/api/scan-status`) — 매 장중 스캔마다(0건 매매·전 종목 실패 포함) 시도/평가/실패 종목·게이트 통과·매수/매도 건수·스캔 주기를 시장별 최신 1행으로 기록. 전 종목 조회 실패에도 조용히 빠지지 않고 하트비트를 남김(#48 계열 방지).
- 스캔 상태 스트립(`ScanStatusStrip`) — 마지막 스캔 시각·평가 종목·게이트 통과·매수/매도·다음 주기 표시. 기록 없으면 "대기 중" 명시.

### Changed
- 의사결정판(오늘의 후보: 청/적신호·매수게이트·차단사유)이 마감 때만이 아니라 **매 장중 스캔마다** 갱신 → "왜 안 샀는지"가 실시간으로 보임. `evaluate_intraday`가 후보 평가를 기록(체결강도미달·장중매수캡·재매수쿨다운·킬스위치 등 사유 추가, 체결 결과 불변).
- "실시간" 라벨 정정 — 연결 표시를 "연결됨"으로, 상단 시각에 "카드 갱신" 라벨을 붙여 시장 데이터/스캔 시각이 아님을 명확히 함.

### 검증
- pytest 385 passed(+10), 프론트 vitest 136 passed + build 통과, 회귀 0. 상세: `docs/patch-notes/v1.15.0.md`.

## v1.14.1 — 2026-07-21

핫픽스: KIS 토큰 만료(EGW00123, HTTP 500/200) 자동 재발급 — 장중 조용한 시세 조회 전면 실패 복구.

### Fixed
- 저장된 KIS 토큰 만료 시 `current_price` 등 조회가 조용히 전부 실패해 장중 자동매매가 빈 스캔만 반복하던 버그 수정(#48). KIS가 만료를 401이 아니라 500(또는 200)+본문(`rt_cd=1`,`msg_cd=EGW00123`)으로 응답하는데, `_get()`이 401만 재발급 처리하고 500은 백오프 재시도만 해 같은 만료 토큰을 계속 재사용한 것이 원인. 본문을 파싱해 만료를 판정(`_is_expired_token`)하고 401과 동일하게 무효화·재발급·재시도. 저장 `expires_at`이 미래인 조기 무효화 케이스도 강제 무효화로 복구.

### 안정성
- 요청당 토큰 재발급 1회 제한(`reissued`) → 무한재시도·발급폭주(EGW00133) 방지. 기존 401 경로도 동일 정책으로 일관화.

### 검증
- pytest 375 passed(+4, TDD 회귀 테스트로 버그 재현→수정 실증). 상세: `docs/patch-notes/v1.14.1.md`.

## v1.14.0 — 2026-07-21

운영 토글: INTRADAY_ENABLED 환경변수로 코드 수정 없이 장중 자동매매 on/off.

### Added
- LiveSettings에 INTRADAY_ENABLED(기본 false)·INTRADAY_SCAN_MINUTES(기본 10). build_app이 설정→Config 구성(_config_from_settings), 엔진·오케·스케줄러 단일 Config 공유. 기본 OFF라 미설정 시 기존 동작 불변.

### Fixed
- build_app이 엔진/오케에 서로 다른 Config() 넘기던 잠재 버그 → 단일 공유 Config로 통일.

### 검증
- pytest 371 passed(+5), 회귀 0. 운영 반영: .env에 INTRADAY_ENABLED=1 후 데몬 재기동. 상세: `docs/patch-notes/v1.14.0.md`.

## v1.13.1 — 2026-07-21

패치: 시드/리플레이 보유 red_score 승계(#7 핵심).

### Fixed
- 리플레이/시드가 스냅 누락 보유종목 red_score를 0으로 리셋(→무위험 오인)하던 것을 직전값 승계로 수정(#7). 보유 signal_status 행 생성을 simcore/signal_status.py 공용 헬퍼로 통합(공식 드리프트 제거).

### 검증
- pytest 366 passed(승계 회귀테스트), 동치성·시드 통과. 상세: `docs/patch-notes/v1.13.1.md`.

## v1.13.0 — 2026-07-21

리서치 후속 3종: 지표 배점 배선(#27)·워크포워드 최적화 WFO/PBO(#30)·신호 신뢰도(#31).

### Added
- 괴리율·지지저항을 신호 코드 G8/G9/R20으로 배선(#27, 실측 문서화). walkforward에 WFO(폴드별 buy_score_min 최적화)+PBO(CSCV 경량, CLI --wfo)(#30). 후보 화면 신호 신뢰도[0,1] 표시(read 전용)(#31).

### 검증
- pytest 361 + 프론트 vitest 134 통과. #27 동치성 통과·실측, #30·#31 회귀 0. 후속(이슈): #38 완전CPCV/DSR, #32 팩터 앙상블, #7 Phase B 이월. 상세: `docs/patch-notes/v1.13.0.md`.

## v1.12.0 — 2026-07-21

전략 검증(워크포워드 롤링 OOS) 하니스 + 장중 가드 영속(#26). 감사 3단계 첫 구현. 알고 트레이딩 벤처 리서치 반영.

### Added
- `simcore/walkforward.py`: 롤링 아웃오브샘플 검증(폴드별 TWR·MDD·Sharpe·승률 + 폴드 간 평균/표준편차·수익폴드 비율), 기존 run_replay+risk_metrics 재사용, CLI, trading-rules §18. 벤처 리서치 문서(deep-research).

### Fixed / Safety
- 장중 킬스위치·휩쏘 캡이 인메모리라 재시작 시 리셋되던 결함 → `intraday_guards` 테이블 영속·부팅 복원(#26).

### 검증
- pytest 335 passed(+15), 회귀 0. 후속(이슈): #27·#30·#31·#32, 인트라데이 운영 활성화·cttr 실서버 검증. 상세: `docs/patch-notes/v1.12.0.md`.

## v1.11.0 — 2026-07-21

장중 자동매매 루프(인트라데이). 24h 라이브 페이퍼 서버가 장 시간 중 10분마다 스캔해 현재가 즉시 매수·매도. 엔진 결정 규칙 재사용(관찰≠행동), `intraday_enabled` 기본 OFF라 기존 동작·리플레이 등가성 불변.

### Added
- `Orchestrator.on_intraday`(10분·장시간 가드)+`Engine.evaluate_intraday`(현재가 즉시 체결, 기존 _buy/_sell 경유=비용 정직), 잠정 일봉(확정 d-1+인메모리 오늘봉). 신규 지표(괴리율·지지저항, 배점 배선 follow-up), 체결강도 게이팅(KR cttr·US 스킵), 휩쏘 캡(종목당 3회)·재매수 쿨다운 30분·킬스위치 당일 −5%. 장중 체결 INTRADAY_BUY/SELL 라벨, trading-rules §17.

### Fixed / Safety
- 장중 잠정봉이 당일 확정 일봉을 오염시키던 경로 수정(d-1까지만 조회), 핸들러 RLock 직렬화(네트워크 조회는 락 밖), per-symbol 크래시 가드·엔진 KeyError 방어.

### 검증
- pytest 320 + 프론트 vitest 133 통과, 회귀 0. 최종 리뷰(opus)+안전수정. 후속(이슈): 재시작 시 킬스위치/캡 인메모리 리셋, 지표 배점 배선, cttr 실서버 검증. 상세: `docs/patch-notes/v1.11.0.md`.

## v1.10.0 — 2026-07-20

의사결정판 가격 가시성 + 라이브 데몬 상시 운영 + 서브패스 배포. v1.9.0 이후 dev 누적 개선 묶음. 첫 화면 후보/시장/보유에 종목별 가격 노출, 라이브 데몬을 대시보드와 동시 기동·종료하도록 정비(감사 3단계 paper/shadow 운영 기반), 프론트 서브패스 배포 지원. 엔진 결정 로직 무변경.

### Added
- 의사결정판 가격 표시: 오늘의 후보 마감가(#10)·오늘의 시장 무버스 가격(#11)·베스트/워스트 종목 가격(#12).
- 라이브 데몬 상시 운영: `dashboard.sh`가 백엔드+데몬 동시 기동·종료, 시드가 RunState 마지막 마감일 기록으로 catch-up 연속성(#13).
- 프론트 서브패스 배포 지원: `VITE_BASE_PATH`(#15)+React Router `basename`(#16).

### Fixed
- KIS 해외 API 클래스주 티커 매핑(`BRK-B`→`BRK/B`) — 일봉·시세 조회 실패로 stale 폴백에 빠지던 문제 수정, 테스트 3건 추가(#17).
- 평균손실 표기를 손실 부호로 정정(+₩ 오인 방지, #10).

### Docs
- `docs/next-steps.md` 신설·정리(#14), BRK-B fix 완료 반영·후보 목록 갱신(#18).

### 검증
- `pytest tests/live/test_kis_client.py` 9 passed. 전체 스위트는 로컬 `.env`(`KIS_ENV=paper`) 자동 로드로 `test_settings` 1건만 실패 — 클린 환경/CI 통과하는 로컬 아티팩트. 포함 PR #10~#18. 상세: `docs/patch-notes/v1.10.0.md`.

## v1.9.0 — 2026-07-20

감사 Phase B — 의사결정 화면(P1). 첫 화면을 "오늘의 의사결정판"으로 재구성: 오늘의 후보/차단 사유(7종), 보유 리스크(손절선·거리%·잠재손실), 거래 생애 복기(페이지네이션·필터·생애 토글), 지표 맥락(손익비·정직한 단순수익률 라벨). 엔진은 관찰 전용 기록만 추가(결정 로직 무변경), 화면은 저장된 마감 상태(SignalStatusRow)만 읽음.

### Added
- CandidateEval 후보 평가 기록(관찰 전용)+SignalStatusRow 영속(시드·라이브), /candidates·/lifecycles·positions 리스크 9필드·dashboard today_actions/risk API, /trades {items,total} 페이지네이션·필터, 프론트 의사결정판(DecisionBoard·CandidatesTable·RiskStrip·TodayActions)+거래 복기 UI, trading-rules §16.

### Fixed
- 생애 진행중 포지션 limit 절단 누락, 리스크 파생필드 저장 마감가 기준 전환, 스냅 누락 보유종목 red_score 승계(라이브), TWR 허위 툴팁 정정, 실시간 갱신 시 거래내역 stale 회귀, ▲/▼ 접근성·제로 케이스.

### 검증
- pytest 286 + 프론트 vitest 116 통과, 재시딩 스모크 실측(후보 120건 분포·보유 12건 리스크 유한값·생애 open=실보유 일치). 최종 리뷰(opus) Ready to merge, Critical/Important 0. 후속: 이슈 #7. 상세: `docs/patch-notes/v1.9.0.md`.

## v1.8.0 — 2026-07-10

감사 Phase A — 신뢰 회복(P0). 엔진 결정을 데이터로 영속해 설명↔실제 행동 100% 일치(P0-1), 기술적 신호 라벨·미수집 축 고지(P0-2), 벤치마크 우선·위험조정 지표(P0-3), PAPER 모드·데이터 기준시각 배지.

### Added
- DecisionType+trigger_rule 결정 이벤트 모델(엔진 확정→전 계층 영속→결정 기반 표시), risk_metrics 12지표, 벤치마크 delta(BenchmarkRow)·미수집 경고, "기술적 매수/매도 신호" 라벨+미반영 고지, /api/status·PAPER 배지. trading-rules §13-15.

### Fixed
- 라이브 재시작 대기매도 크래시(대기주문 결정필드 영속, Critical), 부분매도 반올림 전량청산 라벨 승격, Calmar MDD=0 폴백 제거, 미지 decision_type 500 방어.

### 검증
- pytest 250 + 프론트 75 통과, 재시딩 스모크(FORCED 82건 결정표시, 벤치마크 3캐릭터 채움). 최종 리뷰(opus) P0 완료조건 3건 MET. 상세: `docs/patch-notes/v1.8.0.md`.

## v1.7.0 — 2026-07-10

하락장 가드 튜닝 — 캐릭터별 스위치 + 시장별 MA 기간으로 파라미터화. 12개월 검증에서 후보들이 MDD 기준 미달(6개월 과적합) → **기본값 전체 OFF 확정**(v1.6.0 동작 동일). 인프라·스윕 도구는 opt-in용으로 유지.

### Changed
- `bear_market_guard`(bool) → `bear_guard_characters`(frozenset), `market_trend_period` → `market_trend_period_kr/us`(시장별). CLI `--bear-guard`/`--no-bear-guard` 상호배타. trading-rules §6-1·README 갱신.

### Added
- `data.make_bearish_fn` 판정 공용 헬퍼(리플레이·라이브 공유), 라이브 `Orchestrator(index_provider)` 가드 배선, `simcore/sweep.py` 그리드 스윕+검증 CLI.

### 검증
- 스윕 16+1회 + 12개월 검증. 국내형은 어느 기간에서도 손해(−8.5%p 문제 근본 해소=가드 미적용). 해외형·범용형 12개월 MDD 악화로 off 강등. pytest 215. 상세: `docs/patch-notes/v1.7.0.md`.

## v1.6.0 — 2026-07-09

하락장 가드 v2 — 범용형 과발동 해소. 판정을 "캐릭터의 모든 시장이 하락장일 때만 차단"으로 변경(단일시장 캐릭터 동작 동일, 범용형은 양시장 동시 하락 시만). 기본 OFF 불변.

### Changed
- `evaluate_close(bearish_by_market dict)` 캐릭터별 all() 판정, 리플레이 양시장 dict 전달, trading-rules v2 규칙.

### 검증 (3자 A/B)
- 범용형 TWR −12.92%(v1 −17.10/OFF −12.10)·MDD −24.05%(3안 중 최고). 국내형/해외형 v1과 동일(회귀 없음). pytest 201.

## v1.5.0 — 2026-07-09

서브프로젝트 6: 시장지수 추세 필터(하락장 가드) — opt-in 전략 튜닝. 기본 OFF, 기존 동작 무변경.

### Added
- 하락장 가드(`bear_market_guard`, 기본 False): 지수(코스피200/S&P500) 20일선 아래면 해당 시장 신규매수 차단(보유·매도·손절 유지). `--bear-guard`로 활성.
- `data.load_index`(KR 1028 + yfinance ^KS200 폴백/US ^GSPC), `DataBundle` 지수 필드, `run_replay` 시장별 하락장 판정, `market_trend_period=20`.

### Fixed
- `load_index` KRX 자격증명 부재 시 크래시 → ^KS200 폴백. 지수 로드를 `--bear-guard` 시로 한정.

### 검증 (6개월 A/B)
- 해외형 개선(TWR +16→+27·MDD -11→-6.5), 국내형 중립, 범용형 악화(-12→-17) — 정직히 기록, 기본 OFF opt-in. pytest 198, 최종 리뷰(opus) 통과.

## v1.4.0 — 2026-07-09

서브프로젝트 5: 대시보드 UI 개편 + 데이터 리셋 (초보 친화 일일 현황판). 순수 엔진 무변경.

### Added
- 종목명 표시(`simcore/names.py`, 코드→한글/회사명, 폴백), 초보 친화 신호 표시(`simcore/signal_display.py`, 한글명·별점·등급·한 줄 요약).
- 일일 현황판 메인(시장 movers·캐릭터 요약·최근 체결), `/api/dashboard`.
- `seed_from_replay.py`(6개월 리플레이 → DB 리셋, `--force` 시 스키마 재생성), `ReplayResult` 최종 상태 노출, `FALLBACK_FX_RATE` 공유 상수.

### Changed
- "simcore/모의투자" 브랜드 텍스트 제거. 거래/보유 응답에 name·score·signal_summary/detail. 상세는 종목명 + 한 줄 요약·펼침(이름·별점).

### Fixed
- 범용형 총자산 불일치 해소(카드 총자산 = 자산곡선 마지막값 정확 일치, 재시딩 검증). USD 보유 캐릭터 "오늘 %" 환율 베이스 왜곡 교정(곡선 비율 스케일링). 시드 fx를 대시보드 고정 환율로 통일.

### 검증
- pytest 190 + 프론트 vitest 46 통과. 데이터 리셋 실행 + 스모크. 최종 전체리뷰(opus) READY TO MERGE.

## v1.3.0 — 2026-07-09

서브프로젝트 4: 신호 시스템 v2 (점수제·다중 게이팅·트레일링 스탑). 순수 엔진 계층 재설계. 목표는 손실 최소화.

### Added
- 신규 지표: ATR·ADX/DI·OBV·VWAP·Parabolic SAR·일목균형표.
- 점수제 신호(계산형 청 17·적 17 구현, 차트패턴/피보/뉴스/수급은 스텁), 카테고리 상한(추세10/돌파·하락패턴10/거래량8/모멘텀8/변동성6).
- 매수 다중 게이팅(총점 ≥ 18 AND 돌파+거래량+추세 각 1개), 매도 등급(9~10 부분 50%·11+ 전량)+강제매도(−7%·지지선·R5+R23), 트레일링 스탑(고정 익절 대체).
- CLI `--buy-score`, 워밍업 패딩 180, `TradeReason.TRAILING_STOP`.

### Changed
- 스냅샷/거래/포지션에 점수·게이트·트레일링 상태 필드. 라이브 영속에 점수·트레일링·부분매도 플래그 저장·복원(기존 DB 리셋 필요). trading-rules.md v2 재작성.

### Fixed (리뷰가 발견)
- 부분매도 전량청산 시 쿨다운 누락, 포지션 트레일링 상태 DB 미영속(라이브 재시작 손절바닥 소실), 재시작 대기주문 위치인자 오프셋, 신호 분포 리포트 라벨.

### 검증
- pytest 172 통과. 6개월 리플레이(2026-01-09~07-09): 국내형 +38.9%/해외형 +16.1%/범용형 −12.1%, 매수 270건 전부 총점≥18. 서브에이전트 구동 + 최종 전체리뷰(opus) 통과.

## v1.2.1 — 2026-07-09

대시보드 UI 전문가급 개편 (프론트엔드 전용, 백엔드·엔진 무변경).

### Changed
- 디자인 토큰 재정비: dataviz 검증 통과 상승=빨강/하락=파랑 팔레트(라이트·다크), 등폭 숫자·타이포·공용 컨트롤, 앱 셸/상단바(실시간 연결 표시).
- 리치 캐릭터 카드: 총자산 히어로 + 오늘 등락 칩 + 영역 스파크라인.
- 자산곡선 차트 전면 개편: Y축 눈금(억/만)·수평 그리드·기간 시작 기준선·X축 날짜·크로스헤어+툴팁·기간 토글(1M/3M/6M/전체), ResizeObserver 실측 폭.
- 보유종목/거래내역 테이블: 우측정렬 등폭 숫자, 시장 통화 인지(₩/$), KR/US 태그, 신호 배지, 사유 한글 라벨(손절/익절).
- 성과지표 스트립, 아바타 표정 다듬기.

### Added
- `format.ts` 포맷터(compact/signed/price/reason) + 테스트(vitest 42).
- `dashboard/scripts/seed_demo.py` — 화면 점검용 데모 데이터 시드(--force 가드).

### 검증
- 프론트 빌드 + vitest 42 통과, Python 137 통과(백엔드 무변경). uvicorn 스모크·전 화면 렌더 확인.

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
