# 하락장 가드 튜닝 (캐릭터별 스위치 + 시장별 MA 기간) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 하락장 가드를 캐릭터별 스위치(`bear_guard_characters`)와 시장별 MA 기간(`market_trend_period_kr/us`)으로 파라미터화하고, 스윕 실험으로 최적 조합을 찾아 config 기본값으로 채택한다 (국내형 −8.5%p 손해 해소가 핵심).

**Architecture:** config의 bool 스위치·단일 기간을 frozenset·시장별 기간으로 대체 → 판정식을 `data.make_bearish_fn` 공용 헬퍼로 추출해 리플레이·라이브가 공유 → 라이브 orchestrator에 `index_provider` 주입으로 가드 배선 → `simcore/sweep.py`로 그리드 스윕·검증 → 확정값을 기본값·문서·대시보드 시드에 반영.

**Tech Stack:** Python 3.11+, dataclasses(frozen), pandas, pytest, pykrx/yfinance(지수), SQLAlchemy(라이브 테스트).

**스펙:** `docs/superpowers/specs/2026-07-10-bear-guard-tuning-design.md`
**브랜치:** `feature/bear-guard-tuning` (dev f9cfdc8에서 분기, 스펙 커밋 bbe0a68 이후)

## Global Constraints

- 캐릭터 이름은 정확히 `"국내형"`, `"해외형"`, `"범용형"` (engine.DEFAULT_CHARACTERS).
- 판정식 의미 고정: **지수 close asof(ts) < 지수 SMA(period) asof(ts)** → 하락장. 지수 없음/워밍업 NaN/조회 실패 → **False**(가드 미발동, 안전 폴백).
- 가드 차단 조건: `st.spec.name in rules.bear_guard_characters AND bearish_by_market AND all(bearish_by_market.get(m, False) for m in st.spec.markets)`. **신규 매수만 차단** — 매도·손절·트레일링·쿨다운 감소는 영향 없음.
- `bear_market_guard`(bool)·`market_trend_period`(단일)는 **완전 대체**(deprecated 별칭 금지 — 내부 파라미터, 외부 사용자 없음).
- config는 "모든 튜닝 파라미터" 원칙 — 새 파라미터는 전부 `simcore/config.py`에, `docs/trading-rules.md`와 1:1 유지.
- 커밋 메시지: 한국어 + 타입 접두어(`feat:`/`fix:`/`test:`/`docs:`). 논리 단위 커밋.
- 전체 테스트: `pytest tests/ -q` — 시작 기준 **201 passed** (tests/live·tests/dashboard는 `TEST_DATABASE_URL`/`DATABASE_URL` 미설정 시 skip, 이는 정상).
- 채택 규칙(6개월 스윕): `TWR ≥ OFF−1.0%p AND |MDD| 감소` 후보 중 |MDD| 최소, 동률 시 TWR 최대. 없으면 off. 12개월 검증: `|MDD| 개선 방향 유지 AND TWR ≥ OFF−3.0%p` 실패 캐릭터는 off 강등.

---

### Task 1: config 필드 교체(캐릭터별 스위치 + 시장별 기간) 전파

`bear_market_guard: bool` → `bear_guard_characters: frozenset`, `market_trend_period` → `market_trend_period_kr/us`. 엔진 게이트·리플레이 SMA·CLI 플래그·기존 테스트를 새 필드로 일괄 갱신한다. **이 태스크 완료 시점에 전체 테스트 그린**이어야 한다(동작은 기존과 동등: 기본 off, 전 캐릭터 on 시 v1.6.0과 동일).

**Files:**
- Modify: `simcore/config.py:43` (SignalParams), `simcore/config.py:99` (TradeRules)
- Modify: `simcore/engine.py:114-117` (매수 가드 게이트)
- Modify: `simcore/replay.py:56-59` (시장별 SMA 기간)
- Modify: `simcore/__main__.py:32-33,44-45,51-52` (+상단 import)
- Test: `tests/test_config.py:23`, `tests/test_data.py:48-50`, `tests/test_engine_orders.py:152-211`, `tests/test_replay_integration.py:111,131`

**Interfaces:**
- Consumes: 기존 `engine.evaluate_close(d, market, snaps, bearish_by_market: dict | None = None)` 시그니처(불변).
- Produces: `SignalParams.market_trend_period_kr: int = 20`, `SignalParams.market_trend_period_us: int = 20`, `TradeRules.bear_guard_characters: frozenset = frozenset()`. 이후 모든 태스크는 이 3개 필드명을 사용한다.

- [ ] **Step 1: 테스트를 새 필드로 갱신 (실패 상태 만들기)**

`tests/test_config.py:23` 을 다음으로 교체:

```python
    assert c.rules.bear_guard_characters == frozenset()
```

`tests/test_data.py:48-50` (`test_market_trend_period_default`)을 다음으로 교체:

```python
def test_market_trend_period_defaults():
    assert SignalParams().market_trend_period_kr == 20
    assert SignalParams().market_trend_period_us == 20
```

`tests/test_engine_orders.py` — 가드 테스트 5곳의 config 생성을 교체. 파일 상단(`_buy_snap` 위)에 상수 추가:

```python
ALL_GUARD = frozenset({"국내형", "해외형", "범용형"})
```

이후 152~211행 안의 `replace(Config().rules, bear_market_guard=True)` **전부(5곳)** 를 `replace(Config().rules, bear_guard_characters=ALL_GUARD)` 로 교체 (테스트 이름·단언은 그대로 유지 — v1.6.0 동작 동등성 확인 겸용).

같은 파일 끝에 캐릭터별 스위치 신규 테스트 추가:

```python
def test_bear_guard_only_listed_characters_blocked():
    # 집합에 든 캐릭터만 차단 — 국내형·범용형은 집합 밖이라 양시장 하락에도 매수 허용
    from datetime import date
    cfg = replace(Config(), rules=replace(Config().rules,
                  bear_guard_characters=frozenset({"해외형"})))
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()},
                       bearish_by_market={Market.KR: True, Market.US: True})
    assert any(b.symbol == "AAA" for b in eng.states["국내형"].pending_buys)
    assert any(b.symbol == "AAA" for b in eng.states["범용형"].pending_buys)
```

`tests/test_replay_integration.py:111` 과 `:131` 의
`replace(Config().rules, bear_market_guard=True)` 를
`replace(Config().rules, bear_guard_characters=frozenset({"국내형", "해외형", "범용형"}))` 로 교체.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_config.py tests/test_data.py tests/test_engine_orders.py tests/test_replay_integration.py -q`
Expected: FAIL — `AttributeError: ... no attribute 'bear_guard_characters'` 또는 `TypeError: ... unexpected keyword argument`

- [ ] **Step 3: config.py 필드 교체**

`simcore/config.py:43` 의 `market_trend_period: int = 20` 을 다음으로 교체:

```python
    market_trend_period_kr: int = 20    # 하락장 가드: KR 지수(코스피200) SMA 기간
    market_trend_period_us: int = 20    # 하락장 가드: US 지수(S&P500) SMA 기간
```

`simcore/config.py:99` 의 `bear_market_guard: bool = False` 를 다음으로 교체:

```python
    bear_guard_characters: frozenset = frozenset()  # 하락장 가드 적용 캐릭터(빈 집합=전체 off)
```

- [ ] **Step 4: engine.py 게이트 교체**

`simcore/engine.py:114-117` 을 다음으로 교체:

```python
            # 매수 후보 (하락장 가드: 집합에 든 캐릭터만, 그 캐릭터의 전 시장 하락 시 차단)
            if (st.spec.name in r.bear_guard_characters and bearish_by_market
                    and all(bearish_by_market.get(m, False) for m in st.spec.markets)):
                continue
```

- [ ] **Step 5: replay.py 시장별 기간**

`simcore/replay.py:56-59` 를 다음으로 교체:

```python
    periods = {Market.KR: config.signals.market_trend_period_kr,
               Market.US: config.signals.market_trend_period_us}
    index_by_market = {Market.KR: bundle.kr_index, Market.US: bundle.us_index}
    sma_by_market = {m: (s.rolling(periods[m]).mean() if s is not None else None)
                     for m, s in index_by_market.items()}
```

- [ ] **Step 6: __main__.py CLI 교체**

상단 import에 추가 (`from simcore.replay import ...` 아래):

```python
from simcore.engine import DEFAULT_CHARACTERS
```

`simcore/__main__.py:32-33` 의 `--bear-guard` 정의를 상호배타 그룹으로 교체:

```python
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--bear-guard", action="store_true",
                     help="하락장 가드 전 캐릭터 강제 on (기본: config bear_guard_characters)")
    grp.add_argument("--no-bear-guard", action="store_true",
                     help="하락장 가드 전체 강제 off")
```

`simcore/__main__.py:44-45` 를 다음으로 교체:

```python
    if args.bear_guard:
        cfg = replace(cfg, rules=replace(cfg.rules,
                      bear_guard_characters=frozenset(c.name for c in DEFAULT_CHARACTERS)))
    elif args.no_bear_guard:
        cfg = replace(cfg, rules=replace(cfg.rules, bear_guard_characters=frozenset()))
```

`simcore/__main__.py:51-52` 지수 로드 게이팅을 유효 집합 기준으로 교체:

```python
    guard_on = bool(cfg.rules.bear_guard_characters)
    kr_index = datamod.load_index("KR", start, end, cache) if (guard_on and kr_syms) else None
    us_index = datamod.load_index("US", start, end, cache) if (guard_on and us_syms) else None
```

- [ ] **Step 7: 전체 테스트 통과 확인**

Run: `pytest tests/ -q`
Expected: 202 passed (기존 201 + 신규 1), 0 failed. 잔여 `bear_market_guard`/`market_trend_period`(단일) 참조 없는지 확인:
`grep -rn "bear_market_guard\|market_trend_period\b" simcore/ tests/ dashboard/ --include=*.py` → `market_trend_period_kr/us` 만 나와야 함.

- [ ] **Step 8: Commit**

```bash
git add simcore/config.py simcore/engine.py simcore/replay.py simcore/__main__.py tests/
git commit -m "feat: 하락장 가드 캐릭터별 스위치+시장별 MA 기간 파라미터화"
```

---

### Task 2: 하락장 판정 공용 헬퍼 `data.make_bearish_fn`

리플레이의 인라인 `_bearish` 를 `simcore/data.py` 공용 헬퍼로 추출한다(라이브가 Task 3에서 재사용). 판정 의미는 Global Constraints의 식과 동일해야 한다.

**Files:**
- Modify: `simcore/data.py` (파일 끝에 함수 추가)
- Modify: `simcore/replay.py:56-73,103` (`_bearish` 인라인 제거, 헬퍼 사용)
- Test: `tests/test_data.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: Task 1의 `market_trend_period_kr/us`.
- Produces: `data.make_bearish_fn(indices: dict, periods: dict) -> Callable[[pd.Timestamp], dict]` — 키는 호출측이 넣은 그대로(리플레이·라이브는 `Market` enum 키 사용), 값은 `bool`. Task 3이 이 함수를 사용한다.

- [ ] **Step 1: 실패하는 단위 테스트 작성** — `tests/test_data.py` 끝에 추가:

```python
def test_make_bearish_fn_basic_and_fallbacks():
    import numpy as np
    import pandas as pd
    from simcore.data import make_bearish_fn
    idx = pd.bdate_range("2026-01-01", periods=60)
    down = pd.Series(np.linspace(200, 100, 60), index=idx)   # 종가 < SMA20
    up = pd.Series(np.linspace(100, 200, 60), index=idx)     # 종가 > SMA20
    fn = make_bearish_fn({"KR": down, "US": up}, {"KR": 20, "US": 20})
    assert fn(idx[-1]) == {"KR": True, "US": False}
    # 지수 없음(None) → False
    assert make_bearish_fn({"KR": None}, {"KR": 20})(idx[-1]) == {"KR": False}
    # 워밍업(SMA NaN) → False
    assert make_bearish_fn({"KR": down}, {"KR": 20})(idx[3]) == {"KR": False}


def test_make_bearish_fn_period_independent_per_market():
    # 같은 지수라도 시장별 기간이 다르면 판정이 갈린다 (하락 후 단기 반등 시나리오)
    import numpy as np
    import pandas as pd
    from simcore.data import make_bearish_fn
    idx = pd.bdate_range("2026-01-01", periods=60)
    v = np.concatenate([np.linspace(200, 100, 50), np.linspace(103, 130, 10)])
    s = pd.Series(v, index=idx)
    fn = make_bearish_fn({"KR": s, "US": s}, {"KR": 5, "US": 60})
    assert fn(idx[-1]) == {"KR": False, "US": True}   # 단기(5)는 반등 반영, 장기(60)는 하락
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_data.py -q`
Expected: FAIL — `ImportError: cannot import name 'make_bearish_fn'`

- [ ] **Step 3: 헬퍼 구현** — `simcore/data.py` 파일 끝에 추가:

```python
def make_bearish_fn(indices: dict, periods: dict):
    """시장별 지수 종가·SMA 기간으로 '하락장 판정 함수'를 만든다 (리플레이·라이브 공용).

    indices: {시장키: pd.Series | None} — 지수 종가(일별). periods: {시장키: SMA 기간}.
    반환 fn(ts) -> {시장키: bool}. 지수 없음/워밍업 NaN/asof 실패 → False (가드 미발동).
    """
    smas = {m: (s.rolling(periods[m]).mean() if s is not None else None)
            for m, s in indices.items()}

    def _one(m, ts) -> bool:
        s, sma = indices.get(m), smas.get(m)
        if s is None or sma is None:
            return False
        try:
            close = float(s.asof(ts))
            avg = float(sma.asof(ts))
        except (KeyError, ValueError):
            return False
        if pd.isna(close) or pd.isna(avg):
            return False
        return close < avg

    return lambda ts: {m: _one(m, ts) for m in indices}
```

- [ ] **Step 4: replay.py 를 헬퍼 사용으로 교체**

`simcore/replay.py` 상단 import에 추가:

```python
from simcore import data as datamod
```

Task 1이 만든 `periods`/`index_by_market`/`sma_by_market` 블록(56-59행 부근)과 `_bearish` 함수(61-73행 부근)를 **통째로** 다음으로 교체:

```python
    periods = {Market.KR: config.signals.market_trend_period_kr,
               Market.US: config.signals.market_trend_period_us}
    bearish_fn = datamod.make_bearish_fn(
        {Market.KR: bundle.kr_index, Market.US: bundle.us_index}, periods)
```

날짜 루프의 `bearish = {Market.KR: _bearish(...), Market.US: _bearish(...)}` (103행 부근)을 다음으로 교체:

```python
        bearish = bearish_fn(ts)
```

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `pytest tests/ -q`
Expected: 204 passed (202 + 신규 2), 0 failed. 특히 `tests/test_replay_integration.py` 의 가드 억제/범용형 테스트가 그대로 통과해야 함(판정 동등성).

- [ ] **Step 6: Commit**

```bash
git add simcore/data.py simcore/replay.py tests/test_data.py
git commit -m "refactor: 하락장 판정을 data.make_bearish_fn 공용 헬퍼로 추출"
```

---

### Task 3: 라이브 배선 — Orchestrator `index_provider` + on_close 가드

가드가 기본값으로 켜지면 라이브도 같은 판정을 써야 한다(리플레이·라이브 동치). `index_provider` 를 주입식으로 추가하고, `on_close` 가 가드 대상 캐릭터가 있을 때만 양 시장 bearish dict 를 계산해 전달한다.

**Files:**
- Modify: `simcore/live/orchestrator.py` (`__init__`, `on_close`, 헬퍼 메서드 추가)
- Modify: `simcore/live/__main__.py:40-49` (`build_app` — 기본 provider 주입)
- Test: `tests/live/test_orchestrator.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: Task 2의 `data.make_bearish_fn`, Task 1의 `bear_guard_characters`/`market_trend_period_kr/us`.
- Produces: `Orchestrator(engine, kis, repo, cfg, fx_provider, index_provider=None)` — `index_provider: (market: str, upto: date) -> pd.Series | None`. `Orchestrator._bearish_by_market(d: date) -> dict[Market, bool] | None` (None = 가드 대상 없음/provider 없음).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/live/test_orchestrator.py` 끝에 추가:

```python
def _guard_cfg():
    from dataclasses import replace
    return replace(Config(), rules=replace(
        Config().rules, bear_guard_characters=frozenset({"국내형", "해외형", "범용형"})))


def test_bearish_by_market_computes_from_provider():
    """provider 지수(KR 하락/US 상승)로 시장별 하락장 dict 계산 — DB 불필요(순수 계산)."""
    from simcore.models import Market
    import numpy as np
    eng = Engine(_guard_cfg())
    eng.start(date(2026, 1, 1), 1300.0)
    idx = pd.bdate_range("2026-01-01", periods=80)
    down = pd.Series(np.linspace(200, 100, 80), index=idx)
    up = pd.Series(np.linspace(100, 200, 80), index=idx)
    orch = Orchestrator(eng, None, None, _guard_cfg(), fx_provider=lambda d: 1300.0,
                        index_provider=lambda market, upto: down if market == "KR" else up)
    out = orch._bearish_by_market(idx[-1].date())
    assert out == {Market.KR: True, Market.US: False}


def test_bearish_by_market_none_when_guard_off_and_skips_provider():
    """가드 대상 캐릭터가 없으면 None 반환 + provider 호출 자체를 스킵."""
    calls = []
    eng = Engine(Config())          # 기본: bear_guard_characters=frozenset()
    eng.start(date(2026, 1, 1), 1300.0)
    orch = Orchestrator(eng, None, None, Config(), fx_provider=lambda d: 1300.0,
                        index_provider=lambda market, upto: calls.append(market))
    assert orch._bearish_by_market(date(2026, 6, 1)) is None
    assert calls == []


def test_bearish_by_market_provider_failure_falls_back_false():
    """지수 로드 예외 → 해당 시장 False (가드 미발동, 라이브 안전 폴백)."""
    from simcore.models import Market
    eng = Engine(_guard_cfg())
    eng.start(date(2026, 1, 1), 1300.0)

    def boom(market, upto):
        raise RuntimeError("network down")
    orch = Orchestrator(eng, None, None, _guard_cfg(), fx_provider=lambda d: 1300.0,
                        index_provider=boom)
    assert orch._bearish_by_market(date(2026, 6, 1)) == {Market.KR: False, Market.US: False}


@needs_db
def test_on_close_passes_bearish_dict_to_engine(session, monkeypatch):
    """on_close 가 evaluate_close 에 bearish_by_market 을 실제로 전달하는지 (배선 검증)."""
    from simcore.models import Market
    import numpy as np
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    cfg = _guard_cfg()
    eng = Engine(cfg)
    eng.start(date(2026, 1, 1), 1300.0)
    idx = pd.bdate_range("2026-01-01", periods=80)
    down = pd.Series(np.linspace(200, 100, 80), index=idx)
    up = pd.Series(np.linspace(100, 200, 80), index=idx)
    orch = Orchestrator(eng, FakeKis({("KR", "005930"): _uptrend()}), repo, cfg,
                        fx_provider=lambda d: 1300.0,
                        index_provider=lambda market, upto: down if market == "KR" else up)
    captured = {}
    orig = eng.evaluate_close

    def spy(d, m, snaps, bearish_by_market=None):
        captured["bear"] = bearish_by_market
        return orig(d, m, snaps, bearish_by_market=bearish_by_market)
    monkeypatch.setattr(eng, "evaluate_close", spy)
    orch.on_close(_uptrend().index[-1].date(), "KR", ["005930"])
    assert captured["bear"] == {Market.KR: True, Market.US: False}
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/live/test_orchestrator.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'index_provider'` (needs_db 테스트는 `TEST_DATABASE_URL` 미설정 시 skip — 그 경우 앞 3개 순수 테스트의 FAIL 확인으로 충분)

- [ ] **Step 3: Orchestrator 구현**

`simcore/live/orchestrator.py` import에 추가:

```python
from simcore import data as datamod
```

`__init__` 시그니처·본문 교체 (13-22행 부근):

```python
    def __init__(self, engine: Engine, kis, repo, cfg: Config, fx_provider,
                 index_provider=None):
        self.engine = engine
        self.kis = kis
        self.repo = repo
        self.cfg = cfg
        self.fx = fx_provider
        # (market:str, upto:date) -> pd.Series | None. None 이면 가드용 지수 미사용(가드 무발동).
        self.index_provider = index_provider
```

(기존 `self._last_price` 주석·초기화는 그대로 유지.)

`on_close` 의 `self.engine.evaluate_close(d, m, snaps)` (71행 부근)을 다음으로 교체:

```python
        self.engine.evaluate_close(d, m, snaps,
                                   bearish_by_market=self._bearish_by_market(d))
```

`on_close` 메서드 아래에 헬퍼 추가:

```python
    def _bearish_by_market(self, d: date) -> dict | None:
        """가드 대상 캐릭터가 있을 때만 양 시장 지수로 하락장 dict 계산 (리플레이와 동일 판정식).
        provider 없음/대상 없음 → None(가드 무발동). 시장별 로드 실패 → 그 시장 False."""
        if not self.cfg.rules.bear_guard_characters or self.index_provider is None:
            return None
        indices = {}
        for mk in (Market.KR, Market.US):
            try:
                indices[mk] = self.index_provider(mk.value, d)
            except Exception as exc:
                print(f"[live] {mk.value} 지수 로드 실패(가드 False 폴백): {exc}")
                indices[mk] = None
        periods = {Market.KR: self.cfg.signals.market_trend_period_kr,
                   Market.US: self.cfg.signals.market_trend_period_us}
        return datamod.make_bearish_fn(indices, periods)(pd.Timestamp(d))
```

- [ ] **Step 4: live/__main__.py 기본 provider 주입**

`simcore/live/__main__.py` 상단 import에 추가:

```python
from datetime import timedelta
from simcore import data as datamod
```

(`from datetime import date` 는 이미 있음 — `timedelta` 만 추가.)

`_fx_provider` 아래에 추가:

```python
def _index_provider(cache: Path):
    """가드용 시장 지수 로더. load_index 내부 폴백(pykrx→yfinance)·캐시 재사용.
    start 를 넉넉히 당겨(180일) LOOKBACK_PAD 와 합쳐 최장 SMA(120일) 워밍업을 보장."""
    def load(market: str, upto: date):
        return datamod.load_index(market, upto - timedelta(days=180), upto, cache)
    return load
```

`build_app` 의 Orchestrator 생성(48행)을 다음으로 교체:

```python
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=_fx_provider(repo),
                        index_provider=_index_provider(Path("data/cache")))
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/live/ -q && pytest tests/ -q`
Expected: 신규 4개 포함 전체 통과(DB 미설정 환경이면 needs_db 는 skip). 기존 라이브 테스트(equivalence 포함)는 `index_provider` 미전달 → None → `evaluate_close(..., bearish_by_market=None)` 이므로 무파손이어야 함.

- [ ] **Step 6: Commit**

```bash
git add simcore/live/orchestrator.py simcore/live/__main__.py tests/live/test_orchestrator.py
git commit -m "feat: 라이브 on_close 하락장 가드 배선 (index_provider 주입)"
```

---

### Task 4: 스윕 도구 `simcore/sweep.py` (그리드 + 검증 모드 + 채택 로직)

`run_replay` 를 인프로세스 반복하는 스윕 CLI. 선정 로직은 순수 함수로 분리해 단위 테스트한다. (스펙은 `scripts/` 를 언급했으나, 이 리포는 패키지 모듈 CLI 관행(`python -m simcore`)이므로 `simcore/sweep.py` + `python -m simcore.sweep` 로 구현 — import/테스트 관행 일치.)

**Files:**
- Create: `simcore/sweep.py`
- Test: `tests/test_sweep.py` (신규)

**Interfaces:**
- Consumes: Task 1 필드, `run_replay(...).summary[char] = {"twr": float, "mdd": float, "pnl_krw": float, "n_trades": int}` (mdd 는 음수).
- Produces: `sweep.improves(off, on) -> bool`, `sweep.pick_single(char, off_summary, runs, key) -> dict | None`, `sweep.pick_universal(off_summary, runs, kr_p, us_p) -> dict | None`. `runs` 항목 형식: `{"kr": int, "us": int, "summary": {char: {...}}}`. CLI: `python -m simcore.sweep --start S --end E [--kr-top N --us-top N --cache DIR --out FILE]` / 검증 모드 `--validate --kr-period P --us-period P --chars 해외형,범용형`.

- [ ] **Step 1: 실패하는 선정 로직 테스트 작성** — `tests/test_sweep.py` 신규:

```python
"""sweep 채택 규칙(순수 함수) 단위 테스트. 규칙: TWR ≥ OFF−1%p AND |MDD| 개선 →
|MDD| 최소, 동률 시 TWR 최대. 후보 없으면 None."""
from simcore.sweep import improves, pick_single, pick_universal


def s(twr, mdd, n=10):
    return {"twr": twr, "mdd": mdd, "pnl_krw": 0.0, "n_trades": n}


OFF = {"국내형": s(0.39, -0.17), "해외형": s(0.16, -0.11), "범용형": s(-0.12, -0.26)}


def test_improves_rule():
    assert improves(OFF["해외형"], s(0.27, -0.065))            # TWR·MDD 모두 개선
    assert improves(OFF["국내형"], s(0.385, -0.15))            # TWR −0.5%p(허용) + MDD 개선
    assert not improves(OFF["국내형"], s(0.30, -0.10))         # TWR −9%p → 탈락
    assert not improves(OFF["해외형"], s(0.20, -0.12))         # MDD 악화 → 탈락


def test_pick_single_dedupes_by_period_and_prefers_min_mdd():
    runs = [
        {"kr": 20, "us": 20, "summary": {"국내형": s(0.30, -0.10)}},   # TWR 손해 커서 탈락
        {"kr": 60, "us": 20, "summary": {"국내형": s(0.385, -0.12)}},  # 후보
        {"kr": 60, "us": 40, "summary": {"국내형": s(0.385, -0.12)}},  # kr 중복 → 1회만
        {"kr": 120, "us": 20, "summary": {"국내형": s(0.383, -0.08)}}, # 후보(|MDD| 최소) → 선정
    ]
    got = pick_single("국내형", OFF, runs, "kr")
    assert got["period"] == 120 and got["mdd"] == -0.08


def test_pick_single_none_when_no_candidate():
    runs = [{"kr": 20, "us": 20, "summary": {"국내형": s(0.10, -0.30)}}]
    assert pick_single("국내형", OFF, runs, "kr") is None


def test_pick_universal_respects_fixed_periods():
    runs = [
        {"kr": 20, "us": 20, "summary": {"범용형": s(-0.11, -0.20)}},
        {"kr": 60, "us": 20, "summary": {"범용형": s(-0.10, -0.18)}},  # kr 고정 60 → 이것만
        {"kr": 60, "us": 40, "summary": {"범용형": s(-0.09, -0.22)}},  # us≠20 → 제외
    ]
    got = pick_universal(OFF, runs, kr_p=60, us_p=20)
    assert (got["kr"], got["us"], got["mdd"]) == (60, 20, -0.18)
    # 고정 기간이 None 이면 그 축은 자유 탐색
    got_free = pick_universal(OFF, runs, kr_p=None, us_p=None)
    assert (got_free["kr"], got_free["us"]) == (60, 20)   # -0.22 는 MDD 악화(-0.26 대비 개선이지만 -0.18 이 최소)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_sweep.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'simcore.sweep'`

- [ ] **Step 3: sweep.py 구현** — `simcore/sweep.py` 신규:

```python
"""하락장 가드 튜닝 스윕: KR×US MA 기간 그리드(가드 전체 on) + OFF 기준 리플레이.

  python -m simcore.sweep --start 2026-01-09 --end 2026-07-09              # 그리드 16+1회
  python -m simcore.sweep --start 2025-07-10 --end 2026-07-09 \
      --validate --kr-period 60 --us-period 20 --chars 해외형,범용형        # OFF vs 후보 2회

채택 규칙: TWR ≥ OFF−1.0%p AND |MDD| 개선 → |MDD| 최소, 동률 시 TWR 최대. 없으면 off.
(스펙: docs/superpowers/specs/2026-07-10-bear-guard-tuning-design.md §1·§6)
"""
from __future__ import annotations
import argparse
import itertools
from dataclasses import replace
from datetime import date
from pathlib import Path

from simcore.config import Config
from simcore import data as datamod, universe
from simcore.engine import DEFAULT_CHARACTERS
from simcore.replay import DataBundle, run_replay

PERIODS = (20, 40, 60, 120)
ALL_CHARS = frozenset(c.name for c in DEFAULT_CHARACTERS)
TWR_TOL = 0.01      # 채택: TWR ≥ OFF − 1.0%p


def improves(off: dict, on: dict, twr_tol: float = TWR_TOL) -> bool:
    """채택 규칙: TWR 손해가 tol 이내 AND |MDD| 개선(감소)."""
    return on["twr"] >= off["twr"] - twr_tol and abs(on["mdd"]) < abs(off["mdd"])


def pick_single(char: str, off_summary: dict, runs: list[dict], key: str) -> dict | None:
    """단일시장 캐릭터 최적 기간. key='kr'|'us' — 같은 기간이면 결과 동일하므로 첫 run만 본다."""
    seen, cands = set(), []
    for r in runs:
        p = r[key]
        if p in seen:
            continue
        seen.add(p)
        summ = r["summary"][char]
        if improves(off_summary[char], summ):
            cands.append((abs(summ["mdd"]), -summ["twr"], p, summ))
    if not cands:
        return None
    cands.sort()
    _, _, p, summ = cands[0]
    return {"period": p, **summ}


def pick_universal(off_summary: dict, runs: list[dict],
                   kr_p: int | None, us_p: int | None) -> dict | None:
    """범용형: 단일시장 캐릭터가 확정한 기간(kr_p/us_p)에 고정. None 축은 자유 탐색."""
    cands = []
    for r in runs:
        if kr_p is not None and r["kr"] != kr_p:
            continue
        if us_p is not None and r["us"] != us_p:
            continue
        summ = r["summary"]["범용형"]
        if improves(off_summary["범용형"], summ):
            cands.append((abs(summ["mdd"]), -summ["twr"], r["kr"], r["us"], summ))
    if not cands:
        return None
    cands.sort()
    _, _, kr, us, summ = cands[0]
    return {"kr": kr, "us": us, **summ}


def _load_bundle(start: date, end: date, kr_top: int, us_top: int, cache: Path) -> DataBundle:
    kr_syms = universe.kospi200(cache, start)[:kr_top]
    us_syms = universe.sp500(cache)[:us_top]
    print(f"[sweep] universe KR {len(kr_syms)} / US {len(us_syms)}, 데이터 로딩...")
    return DataBundle(
        kr=datamod.load_kr_daily(kr_syms, start, end, cache),
        us=datamod.load_us_daily(us_syms, start, end, cache),
        fx=datamod.load_fx(start, end, cache),
        kr_index=datamod.load_index("KR", start, end, cache),
        us_index=datamod.load_index("US", start, end, cache),
    )


def _cfg(kr_p: int, us_p: int, chars: frozenset) -> Config:
    base = Config()
    return replace(base,
                   signals=replace(base.signals,
                                   market_trend_period_kr=kr_p, market_trend_period_us=us_p),
                   rules=replace(base.rules, bear_guard_characters=chars))


def _md_rows(label: str, summary: dict) -> list[str]:
    return [f"| {label} | {name} | {s['twr'] * 100:.2f} | {s['mdd'] * 100:.2f} | {s['n_trades']} |"
            for name, s in summary.items()]


def main() -> None:
    ap = argparse.ArgumentParser(prog="simcore.sweep", description="하락장 가드 튜닝 스윕")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--kr-top", type=int, default=200)
    ap.add_argument("--us-top", type=int, default=100)
    ap.add_argument("--cache", default="data/cache")
    ap.add_argument("--out", default=None, help="markdown 표 저장 경로(기본 stdout)")
    ap.add_argument("--validate", action="store_true", help="그리드 대신 OFF vs 단일 후보 2회")
    ap.add_argument("--kr-period", type=int, default=20)
    ap.add_argument("--us-period", type=int, default=20)
    ap.add_argument("--chars", default=",".join(sorted(ALL_CHARS)),
                    help="가드 적용 캐릭터(쉼표구분, validate 모드용)")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    bundle = _load_bundle(start, end, args.kr_top, args.us_top, Path(args.cache))

    lines = [f"# 가드 스윕 {start}~{end} (kr_top={args.kr_top}, us_top={args.us_top})", "",
             "| 설정 | 캐릭터 | TWR % | MDD % | 거래수 |", "|---|---|---|---|---|"]
    off = run_replay(_cfg(20, 20, frozenset()), bundle, start, end)
    lines += _md_rows("OFF", off.summary)
    print("[sweep] OFF 기준 완료")

    if args.validate:
        chars = frozenset(c for c in args.chars.split(",") if c)
        res = run_replay(_cfg(args.kr_period, args.us_period, chars), bundle, start, end)
        lines += _md_rows(f"ON kr={args.kr_period} us={args.us_period} chars={','.join(sorted(chars))}",
                          res.summary)
    else:
        runs = []
        for kr_p, us_p in itertools.product(PERIODS, PERIODS):
            res = run_replay(_cfg(kr_p, us_p, ALL_CHARS), bundle, start, end)
            runs.append({"kr": kr_p, "us": us_p, "summary": res.summary})
            lines += _md_rows(f"ON kr={kr_p} us={us_p}", res.summary)
            print(f"[sweep] kr={kr_p} us={us_p} 완료")
        kr_pick = pick_single("국내형", off.summary, runs, "kr")
        us_pick = pick_single("해외형", off.summary, runs, "us")
        uni_pick = pick_universal(off.summary, runs,
                                  kr_pick["period"] if kr_pick else None,
                                  us_pick["period"] if us_pick else None)
        lines += ["", "## 채택 규칙 자동 적용 (TWR≥OFF−1%p AND |MDD|개선 → |MDD|최소)",
                  f"- 국내형: {kr_pick or 'off (후보 없음)'}",
                  f"- 해외형: {us_pick or 'off (후보 없음)'}",
                  f"- 범용형: {uni_pick or 'off (후보 없음)'}"]

    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"[sweep] 저장: {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_sweep.py -q && pytest tests/ -q`
Expected: 신규 4개 포함 전체 통과. CLI 스모크: `python -m simcore.sweep --help` 가 usage 출력.

- [ ] **Step 5: Commit**

```bash
git add simcore/sweep.py tests/test_sweep.py
git commit -m "feat: 가드 튜닝 스윕 CLI (그리드+검증 모드, 채택 규칙 자동화)"
```

---

### Task 5: 스윕 실행 + 12개월 검증 + 실험 기록 (코드 무변경)

컨트롤러가 직접 실행·기록한다(서브에이전트 불필요 — 장시간 실행+판단 태스크). **결과가 나쁘더라도 정직하게 기록**하고 채택 규칙을 기계적으로 적용한다.

**Files:**
- Create: `docs/experiments/bear_guard_tuning_sweep_2026-01-09_2026-07-09.md`

**Interfaces:**
- Consumes: Task 4 CLI.
- Produces: 확정 조합 — `bear_guard_characters` 최종 집합, `market_trend_period_kr/us` 최종값. Task 6이 이 값을 config 기본값으로 사용한다.

- [ ] **Step 1: 기존 A/B 실행 조건 확인**

`docs/experiments/replay_bear_guard_ab_2026-01-09_2026-07-09.md` 를 읽고 당시 유니버스 조건(kr-top/us-top, 캐시 경로)을 확인 — 스윕도 **동일 조건**으로 실행해 3자 비교 연속성 유지.

- [ ] **Step 2: 6개월 그리드 스윕 실행**

```bash
python -m simcore.sweep --start 2026-01-09 --end 2026-07-09 \
  --out docs/experiments/bear_guard_tuning_sweep_2026-01-09_2026-07-09.md
```

(kr-top/us-top 은 Step 1에서 확인한 값으로 지정.) 17회 리플레이 — 수 분~수십 분 소요 가능, 진행 로그로 확인. 완료 후 회귀 검증: `ON kr=20 us=20` 행이 v1.6.0 A/B의 가드 v2 결과(범용형 TWR −12.92%/MDD −24.05%)와 일치해야 함(동일 조건이면 결정론).

- [ ] **Step 3: 채택 후보 확정**

스윕 출력의 "채택 규칙 자동 적용" 절을 검토하고 실험 md에 해석 절 추가: 캐릭터별 후보/탈락 사유, 시장별 기간 확정(단일시장 우선 규칙), 범용형 on/off. 국내형 후보가 없으면 **국내형 off가 곧 목표 달성**(가드 손해 −8.5%p 제거)임을 명시.

- [ ] **Step 4: 12개월 검증 실행**

확정 후보로 (예: 해외형·범용형 on, kr=60, us=20 이라면):

```bash
python -m simcore.sweep --start 2025-07-10 --end 2026-07-09 --validate \
  --kr-period <확정KR> --us-period <확정US> --chars <확정 캐릭터들>
```

출력 표를 실험 md에 "12개월 검증" 절로 추가. 판정: 가드 on 캐릭터 각각 `|MDD| 개선 유지 AND TWR ≥ OFF−3.0%p` — 실패 캐릭터는 off로 강등하고 강등 사유 기록. (12개월 데이터가 신규 다운로드되므로 첫 실행이 느릴 수 있음. pykrx 자격증명 없으면 ^KS200 폴백 로그가 나오는 것이 정상.)

- [ ] **Step 5: 최종 확정 기록 + Commit**

실험 md 말미에 "최종 확정" 절: `bear_guard_characters = {...}`, `market_trend_period_kr = N`, `market_trend_period_us = M` + 근거 한 줄.

```bash
git add docs/experiments/bear_guard_tuning_sweep_2026-01-09_2026-07-09.md
git commit -m "test: 가드 튜닝 스윕 16+1회 + 12개월 검증 기록"
```

---

### Task 6: 기본값 채택 + 시드 배선 + 문서 정합 + 재시딩

Task 5 확정값을 config 기본값으로 반영하고, 대시보드 시드가 지수를 배선하도록 고쳐 재시딩한다. **이 태스크의 모든 `<확정...>` 자리는 Task 5 실험 md "최종 확정" 절의 값으로 치환한다** — 다른 출처 금지.

**Files:**
- Modify: `simcore/config.py` (기본값), `dashboard/scripts/seed_from_replay.py:197-203` (지수 배선)
- Modify: `docs/trading-rules.md:131-155` (§6-1), `README.md` (가드 언급부)
- Test: `tests/test_config.py` (기본값 단언 갱신)

**Interfaces:**
- Consumes: Task 5의 확정 조합.
- Produces: 최종 기본 Config — 이후 리플레이/라이브/시드가 플래그 없이 최적 가드로 동작.

- [ ] **Step 1: 기본값 테스트 갱신 (실패 상태)**

`tests/test_config.py` 의 두 단언을 확정값으로 교체:

```python
    assert c.rules.bear_guard_characters == frozenset({<확정 캐릭터들>})
```

`tests/test_data.py::test_market_trend_period_defaults` 도 확정 기간으로 교체:

```python
    assert SignalParams().market_trend_period_kr == <확정KR>
    assert SignalParams().market_trend_period_us == <확정US>
```

Run: `pytest tests/test_config.py tests/test_data.py -q` → Expected: FAIL (기본값 불일치)

- [ ] **Step 2: config 기본값 반영**

`simcore/config.py` 의 세 필드 기본값을 확정값으로 교체 (주석에 근거 실험 md 경로 명시):

```python
    market_trend_period_kr: int = <확정KR>   # 하락장 가드: KR 지수 SMA (bear_guard_tuning_sweep 참조)
    market_trend_period_us: int = <확정US>   # 하락장 가드: US 지수 SMA (bear_guard_tuning_sweep 참조)
```

```python
    # 하락장 가드 적용 캐릭터 (스윕+12개월 검증 채택: docs/experiments/bear_guard_tuning_sweep_*.md)
    bear_guard_characters: frozenset = frozenset({<확정 캐릭터들>})
```

Run: `pytest tests/ -q` → Expected: 전체 통과. **주의**: 기본값 변경으로 기존 테스트가 깨지면(예: 가드 off 를 전제한 리플레이 테스트) 해당 테스트의 Config 를 `replace(..., bear_guard_characters=frozenset())` 로 명시 off — 지수 없는 번들은 판정이 전부 False 라 대부분 무영향이어야 함.

- [ ] **Step 3: seed_from_replay 지수 배선**

`dashboard/scripts/seed_from_replay.py:197-203` 부근 DataBundle 생성에 지수 추가 (import에 `from simcore import data as datamod` 존재 확인 — 없으면 기존 datamod alias 사용):

```python
    guard_on = bool(cfg.rules.bear_guard_characters)
    bundle = DataBundle(
        kr=datamod.load_kr_daily(kr_syms, start, end, cache),
        us=datamod.load_us_daily(us_syms, start, end, cache),
        fx=datamod.load_fx(start, end, cache),
        kr_index=datamod.load_index("KR", start, end, cache) if (guard_on and kr_syms) else None,
        us_index=datamod.load_index("US", start, end, cache) if (guard_on and us_syms) else None,
    )
```

(주변 변수명 `cfg`/`cache` 는 실제 코드에 맞춰 사용. 시드 리플레이가 CLI 리플레이와 같은 가드 조건으로 돌게 하는 것이 목적.)

- [ ] **Step 4: 문서 갱신**

- `docs/trading-rules.md` §6-1: 제목·본문을 "캐릭터별 적용 + 시장별 기간"으로 재작성 — 기본 적용 캐릭터 집합, KR/US 기간, off 캐릭터와 그 근거(스윕 결과 수치), CLI `--bear-guard`(전체 강제 on)/`--no-bear-guard`(전체 off) 갱신. 131행의 "기본 **off**" 문구를 실제 기본값으로 교체.
- `README.md`: `--bear-guard` 설명부를 새 의미로 갱신.
- config.py ↔ trading-rules.md 값 전수 대조(불일치 0).

- [ ] **Step 5: 재시딩 + 스모크**

```bash
DATABASE_URL=<라이브 DB URL> python -m dashboard.scripts.seed_from_replay --force
```

(URL은 기존 T10 재시딩과 동일 환경 사용. `--start/--end` 기본값 2026-01-09~07-09 유지.) 완료 후 대시보드 API 스모크: 3캐릭터 `total == equity` 일치, trades 수가 실험 md의 확정 조합 수치와 일치.

- [ ] **Step 6: 전체 테스트 + Commit**

Run: `pytest tests/ -q` → Expected: 전체 통과.

```bash
git add simcore/config.py dashboard/scripts/seed_from_replay.py docs/trading-rules.md README.md tests/
git commit -m "feat: 가드 튜닝 확정값 기본 적용 + 시드 지수 배선 + 문서 정합"
```

---

## 완료 후 (플랜 밖, 리포 워크플로)

ALL 6 TASKS COMPLETE 후: `.superpowers/sdd/progress.md` 원장 갱신 → 최종 전체브랜치 리뷰(opus) → `gh pr create --base dev` → dev 병합 + 브랜치 삭제 → dev→main 승격 → **v1.7.0** 태그 + CHANGELOG/패치노트 (CLAUDE.md 표준 흐름).
