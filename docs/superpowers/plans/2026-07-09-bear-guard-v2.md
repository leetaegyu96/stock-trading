# 하락장 가드 v2 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** 가드 판정을 "캐릭터의 모든 시장이 하락장일 때만 차단"으로 변경(범용형 과발동 해소)하고 A/B v2로 검증.

**Architecture:** engine `evaluate_close`의 `market_bearish: bool` → `bearish_by_market: dict | None` 대체(캐릭터별 all() 판정), replay가 양시장 dict 전달. 기본 None=무변경.

## Global Constraints
- 기본 OFF/None이면 동작 무변경. 단일시장 캐릭터는 v1과 판정 동일. 매도·손절·쿨다운 불변.
- 커밋 신원 `leetaegyu96 <leetaegyu96@users.noreply.github.com>`, 한국어 커밋. `dev`에서 분기.

---

### Task 1: 엔진 — bearish_by_market 판정

**Files:** Modify `simcore/engine.py`; Test `tests/test_engine_orders.py`

**Interfaces — Produces:** `evaluate_close(self, d, market, snaps, bearish_by_market: dict | None = None)`. 가드(매수 후보 생성 직전, st 루프 안):
```python
            if (self.config.rules.bear_market_guard and bearish_by_market
                    and all(bearish_by_market.get(m, False) for m in st.spec.markets)):
                continue
```

- [ ] **Step 1: 실패 테스트** — 기존 sp6 가드 테스트 4건을 v2 의미로 갱신 + 신규 2건:

```python
def test_bear_guard_v2_multimarket_one_bearish_allows_buys():
    # 범용형: KR만 하락 → US·KR 모두 신규매수 허용(all() 미충족)
    from datetime import date
    cfg = replace(Config(), rules=replace(Config().rules, bear_market_guard=True))
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: True, Market.US: False})
    assert any(b.symbol == "AAA" for b in eng.states["범용형"].pending_buys)   # 범용형 허용
    assert not eng.states["국내형"].pending_buys                                # 국내형(KR만)은 차단


def test_bear_guard_v2_multimarket_both_bearish_blocks():
    from datetime import date
    cfg = replace(Config(), rules=replace(Config().rules, bear_market_guard=True))
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: True, Market.US: True})
    assert not eng.states["범용형"].pending_buys
    assert not eng.states["국내형"].pending_buys
```
기존 4건 갱신: `market_bearish=True` → `bearish_by_market={Market.KR: True, Market.US: True}` 식(테스트 의도 보존; "still allows sells" 포함).

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_engine_orders.py -k bear_guard -q` → FAIL
- [ ] **Step 3: 구현** — 시그니처 교체 + 가드 조건 교체(위 코드). `market_bearish` 파라미터 제거.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_engine_orders.py -q` → PASS
- [ ] **Step 5: 커밋** — `git commit -m "feat: 하락장 가드 v2 (캐릭터 전 시장 하락 시만 차단)"`

---

### Task 2: 리플레이 dict 전달

**Files:** Modify `simcore/replay.py`; Test `tests/test_replay_integration.py`

**Interfaces:** run_replay가 각 evaluate_close 호출에 `bearish_by_market={Market.KR: _bearish(Market.KR, ts), Market.US: _bearish(Market.US, ts)}` 전달(기존 `market_bearish=` 교체).

- [ ] **Step 1: 테스트 갱신+신규** — 기존 `test_bear_guard_suppresses_buys_in_index_downtrend` 유지(단일시장이라 동일 결과). 신규: KR지수 하락·US지수 상승 + KR/US 종목 모두 존재하는 번들에서 guard on 시 **범용형 매수가 0이 아님**(한쪽만 하락이라 허용) 확인.

```python
def test_bear_guard_v2_universal_buys_when_only_one_market_bearish():
    import numpy as np, pandas as pd
    from datetime import date
    from dataclasses import replace
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 400, 220)
    mk = lambda: pd.DataFrame({"open": up, "high": up + 2, "low": up - 2, "close": up,
                               "volume": np.linspace(1e3, 5e3, 220)}, index=idx)
    bundle = DataBundle(kr={"AAA": mk()}, us={"BBB": mk()}, fx=pd.Series(1300.0, index=idx),
                        kr_index=pd.Series(np.linspace(400, 100, 220), index=idx),   # KR 하락
                        us_index=pd.Series(np.linspace(100, 400, 220), index=idx))   # US 상승
    cfg_on = replace(Config(), rules=replace(Config().rules, bear_market_guard=True))
    res = run_replay(cfg_on, bundle, date(2025, 9, 1), date(2026, 2, 1))
    buys = res.trades[(res.trades.side == "BUY") & (res.trades.character == "범용형")] if not res.trades.empty else res.trades
    assert len(buys) > 0        # 한쪽만 하락 → 범용형 매수 허용(v1이면 KR 매수 전면 차단이었음)
```

- [ ] **Step 2~4: TDD 실행** — FAIL 확인 → replay.py 호출부 교체 → PASS(전체 회귀 포함).
- [ ] **Step 5: 커밋** — `git commit -m "feat: 리플레이가 양시장 하락 dict 전달 (가드 v2)"`

---

### Task 3: A/B v2 + 문서

**Files:** Modify `docs/experiments/replay_bear_guard_ab_2026-01-09_2026-07-09.md`, `docs/trading-rules.md`

- [ ] **Step 1: 회귀** — `python -m pytest -q` 전부 통과.
- [ ] **Step 2: B(v2) 실행** — `python -m simcore --start 2026-01-09 --end 2026-07-09 --kr-top 50 --us-top 50 --bear-guard --out out/ab_on_v2` (OFF·v1 결과는 기존 기록 재사용).
- [ ] **Step 3: 3자 비교 기록** — 실험 md에 "v2" 절 추가: OFF/v1/v2 캐릭터별 TWR·MDD·거래수·승률 표 + 해석(범용형이 v1 대비/OFF 대비 개선?). 국내형·해외형이 v1과 동일한지(단일시장 회귀 확인)도 명시.
- [ ] **Step 4: trading-rules 갱신** — 가드 절을 v2 규칙("캐릭터가 거래하는 모든 시장이 하락일 때만")으로.
- [ ] **Step 5: 커밋** — `git commit -m "test: 하락장 가드 v2 A/B + 규칙 문서 갱신"`

## Self-Review
- 스펙 §1~2=Task1·2, §4=Task3, §5=각 태스크. 시그니처 교체(모든 호출부: replay 1곳·orchestrator는 미전달이라 무변경·테스트) 일관. 기본 None 무변경.
