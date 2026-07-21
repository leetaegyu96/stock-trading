# 다음 할 일 (Next Steps)

> 기준일: **2026-07-20**. 새 작업을 시작하거나 우선순위를 바꿀 때 이 문서를 갱신한다.
> 근거 문서: 감사 리포트 `docs/reviews/2026-07-10-trading-product-audit.md`, 백로그 이슈 [#7](https://github.com/leetaegyu96/stock-trading/issues/7).

## 현재 상태 스냅샷

- **v1.10.0 릴리즈 완료** (2026-07-20) — 의사결정판 가격 가시성(후보/시장/보유 종목별 가격), 라이브 데몬 상시 운영(dashboard.sh 동시 기동·종료+시드 RunState catch-up), 서브패스 배포(VITE_BASE_PATH), KIS 해외 BRK-B 심볼 매핑 fix. dev→main 승격·태그·패치노트 완료. 포함 PR #10~#19. 상세 `docs/patch-notes/v1.10.0.md`.
- **v1.9.0 릴리즈 완료** — 감사 Phase B(의사결정 화면 P1) 8태스크. 첫 화면 의사결정판, 오늘의 후보/차단 사유, 보유 리스크, 거래 생애 복기. Codex 재감사 대기.
- **라이브 데몬 가동 중** — `./dashboard/dashboard.sh start`가 백엔드+데몬 동시 기동. 시드 RunState 덕에 7/10~7/17 갭 리플레이 완료, 데이터 7/17 기준 최신. 이후 매 마감 자동 처리(PAPER 모드, 실주문 없음).
- **장중 자동매매(인트라데이) 구현 완료 — 진행 중(운영 미활성화)**: `feature/intraday-trading-loop` 브랜치에서 9태스크(신규 지표·config·DecisionType·엔진 게이트/체결·KIS 체결강도·오케스트레이터 잠정봉·스케줄러·대시보드 라벨/문서) 전부 구현·테스트 통과(trading-rules §17). `intraday_enabled` 기본 `False`라 아직 미동작. 다음: 전체브랜치 리뷰(opus) → dev 병합 → 운영 서버 플래그 `True` 활성화 → 첫 장중 실동작(매수/매도·킬스위치) 로그 관측 → 이상 없으면 v1.11.0으로 릴리즈(v1.10.0은 이미 출시됨).

## 1. 즉시 (이번 주)

- [ ] **오늘 이후 첫 실시간 마감 정상 처리 확인** — KR 15:30 / US 새벽 마감이 스케줄러로 처리되는지 로그(`dashboard.sh logs live`, tmux `trade:1` live-log 창)와 `/api/status`·후보 as_of로 확인. 이상 없으면 →
- [x] **v1.10.0 릴리즈** (2026-07-20) — dev→main 승격(PR #20), 태그 v1.10.0, 패치노트 완료. PR #10~#19 묶음.
- [x] **BRK-B KIS 해외 일봉 실패 수정** (PR #17, dev 병합) — 원인: KIS 해외 API가 클래스주 티커를 `/` 구분자(`BRK/B`)로 요구하는데 유니버스엔 `BRK-B`(하이픈)로 저장돼 조회가 항상 실패. `kis_client._split_us()`에 `-`→`/` 정규화 추가로 수정, 테스트 3건 추가. **다음 실시간 마감에서 BRK-B 일봉·시세가 정상 수신되는지 로그로 재확인 필요** (아래 항목과 연동).
- [ ] **Codex 재감사 대응** — Phase B 재감사 결과가 오면 `docs/reviews/`의 신규 리포트를 `implementing-review-findings` 스킬로 반영.
- [ ] **장중 자동매매 운영 활성화** — `intraday_enabled=True`로 별도 설정/환경변수 켜기 → 장중 로그로 매수/매도·킬스위치 실동작 첫 관측 → KIS 체결강도(`cttr`) 필드가 실서버 응답과 일치하는지 검증(trading-rules §17, 문서상 값이라 미검증) → 이상 없으면 v1.11.0 릴리즈.

## 2. 단기 — Phase B 이월 백로그 (이슈 #7)

우선 권고(최종 리뷰어 명시) 순:

- [ ] **replay·orchestrator 보유 signal_status 생성 공용 헬퍼 통합** — 시드 경로에도 red_score 승계 적용(현재 라이브만, trading-rules §16-3에 한계 명시). 두 경로 드리프트 원천 차단. ※ #1 완료 후 재시딩 불필요해졌으므로 우선순위 소폭 하락했지만 여전히 유효.
- [ ] /api/dashboard 루프의 캐릭터별 positions 중복 조회 제거
- [ ] 시드 as_of가 시장별 마지막 거래일 편차를 반영하지 않음(전 row 글로벌 last_day 스탬프)
- [ ] 테스트 커버리지: fill_open "가격없음" 경로, positions close=None 보유행, decision_type·offset API 레이어, Detail 페이지(라이브 서명→재조회 회귀)
- [ ] 품질/UX: `_all_trades` 공개 API화, lifecycles limit 하한 시맨틱 주석, `_prior_held_red_score` 쿼리 배치화, signal_status kind SQL 필터, LifecycleCard entry_trigger 표시, 종목 필터 디바운스, TradesTable(419줄) 분할 감시, MetricsPanel 손실 음수화 `-Math.abs` 단순화

## 3. 감사 로드맵 3단계 — 전략 검증 (실전 전 필수 P0)

Phase B 다음의 큰 덩어리. 감사 §6 3단계 원문 기준:

- [ ] point-in-time universe와 corporate action 검증
- [x] walk-forward / holdout 하니스 구현 완료 (`simcore/walkforward.py`, `feature/walk-forward-validation`) — 기존 `run_replay`/`risk_metrics` 재사용한 롤링 OOS 평가.
- [x] **진짜 WFO(폴드별 파라미터 최적화) + 과적합확률(PBO, CSCV 경량판) 구현 완료** (이슈 #30, `generate_opt_folds`/`run_wfo`/`probability_of_backtest_overfitting`, CLI `--wfo`, `docs/trading-rules.md` §18.1). 실데이터로 폴드 리포트를 뽑아 국면별 일관성 검토는 남음. **여전히 후속**: purge/embargo·≥100 경로를 갖춘 완전 CPCV, Deflated/Probabilistic Sharpe Ratio(DSR/PSR).
- [ ] 비용·슬리피지·미체결 스트레스 테스트
- [ ] 신호별 ablation과 파라미터 안정성 지도
- [ ] **paper/shadow 최소 1개월 운영** — 주문 대사·데이터 장애 통계 수집. ※ 라이브 데몬이 이제 상시 가동되므로 이 항목은 오늘부터 사실상 진행 시작. 장애(일봉 실패 등) 통계를 쌓는 관측 코드가 뒷받침되면 좋음.

## 4. 이후 단계 (착수 전 사용자 합의 필요)

- **4단계 — 외부 정보축(P1)**: 공시·실적·수급·거시 파이프라인, 출처·시각·신뢰도·결측 증거 모델, 찬성/반대 근거 균형 표시, 뉴스는 검증 통과 시에만 점수 반영.
- **P2 — 초보자 학습 UX**: 용어 도움말, 신호의 반례 표시, 복기 노트, 캐릭터 전략 차별화(또는 "시장별 계좌"로 정직하게 개명).
- **5단계 — 제한적 실전(P0 게이트 통과 후에만)**: 소액·1종목 한도 → 알림 전용 → 승인 주문 → 소액 자동주문 승격. 킬스위치 리허설. **3단계 검증 통과 전에는 실주문 코드를 넣지 않는다**(감사 §2 진입 조건).

## 5. 운영 잔여 (소항목, 기회 될 때)

- KR/US 휴장일 정밀화 — `_holidays_provider`가 현재 빈 집합(주말만 비거래). 휴장일에 마감 처리 시도→일봉 실패 스킵으로 무해하지만 정밀화 필요.
- KRX_ID/KRX_PW 미설정 경고(시드 시 로그) — 자격 증명 설정 또는 경고 억제.
- 이중 /ws 연결(무해), RecentTrades 집계 위젯 결정 칩 미노출, seed_demo SELL=BUY 고정, profit_factor 전승 시 0 표시, 혼합 벤치마크 단순평균→자본 비중 가중, 유니버스 30/30 확대 검토.
- 재시딩 시 RunState가 `_TABLES_TO_CLEAR` 미포함 — 현행 `--force`(drop_all) 경로는 무해하나 시드 함수 직접 호출 시 stale 가능(리뷰어 노트).
- CandidateOut 등 의사결정판 API 필드 목록의 문서 절 부재(trading-rules §16은 의미만 서술).
