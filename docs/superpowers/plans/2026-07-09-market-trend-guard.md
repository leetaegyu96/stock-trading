# 시장지수 추세 필터(하락장 가드) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 하락장(시장지수 < 20일선)에서 신규매수를 차단하는 `bear_market_guard`를 실제 동작시키고, 6개월 리플레이 A/B로 범용형 손실·MDD 개선을 확인한다.

**Architecture:** 지수 데이터(data.py) → DataBundle → run_replay가 시장별 일자별 하락장 플래그 계산 → engine.evaluate_close(market_bearish)가 가드 on+하락장이면 신규매수 후보 제외. 기본 off라 하위호환.

**Tech Stack:** Python, pandas, pytest. 지수: pykrx(코스피200 1028), yfinance(^GSPC).

## Global Constraints

- `bear_market_guard=False`(기본)이면 **모든 계층 동작 무변경**. 가드는 opt-in.
- 가드 발동 시 **신규매수만 차단**; 보유·매도·손절·트레일링·부분매도·쿨다운은 그대로.
- 지수 데이터 없으면 `market_bearish=False`(가드 미작동, 안전 폴백).
- 값은 `docs/trading-rules.md`·`config.py`와 1:1. 커밋 신원 `leetaegyu96 <leetaegyu96@users.noreply.github.com>`, 한국어 커밋. `dev`에서 분기.

## 파일 구조
- `simcore/config.py` (수정) — `SignalParams.market_trend_period=20`.
- `simcore/data.py` (수정) — `load_index`.
- `simcore/replay.py` (수정) — `DataBundle.kr_index/us_index`, run_replay 하락장 판정·전달.
- `simcore/engine.py` (수정) — `evaluate_close(..., market_bearish=False)` 가드.
- `simcore/__main__.py` (수정) — `--bear-guard`, 지수 로드해 bundle에 전달.
- `docs/trading-rules.md`·`README.md` (수정).
- 테스트: `tests/test_engine_orders.py`, `tests/test_data.py`, `tests/test_replay_integration.py`.

---

### Task 1: config + 지수 로더

**Files:** Modify `simcore/config.py`, `simcore/data.py`; Test `tests/test_data.py`

**Interfaces — Produces:** `SignalParams.market_trend_period: int = 20`; `data.load_index(market: str, start, end, cache_dir) -> pd.Series`(지수 종가, KR=코스피200/US=S&P500).

- [ ] **Step 1: 실패 테스트** — `tests/test_data.py`에 추가

```python
def test_market_trend_period_default():
    from simcore.config import SignalParams
    assert SignalParams().market_trend_period == 20
```
(load_index는 네트워크 의존이라 단위테스트는 상수만; 함수 존재/시그니처는 리플레이 통합에서 간접 검증.)

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_data.py -k market_trend_period -q` → FAIL

- [ ] **Step 3: 구현**
`simcore/config.py` `SignalParams`에 필드 추가:
```python
    market_trend_period: int = 20
```
`simcore/data.py`에 추가(기존 load_fx 패턴·LOOKBACK_PAD_DAYS 재사용):
```python
def load_index(market: str, start: Date, end: Date, cache_dir: Path) -> pd.Series:
    """시장 대표 지수 종가. KR=코스피200(pykrx 1028), US=S&P500(^GSPC)."""
    pad_start = start - timedelta(days=LOOKBACK_PAD_DAYS)
    if market == "KR":
        def fetch():
            from pykrx import stock
            s = stock.get_index_ohlcv(f"{pad_start:%Y%m%d}", f"{end:%Y%m%d}", "1028")["종가"]
            s.index = pd.to_datetime(s.index)
            return s.rename("close").to_frame()
        key = _key("IDX", "KOSPI200", pad_start, end)
    else:
        def fetch():
            import yfinance as yf
            raw = yf.download("^GSPC", start=pad_start, end=end + timedelta(days=1),
                              auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            s = raw["Close"] if "Close" in raw.columns else raw["close"]
            s.index = pd.to_datetime(s.index).tz_localize(None)
            return s.rename("close").to_frame()
        key = _key("IDX", "SP500", pad_start, end)
    df = _cached(cache_dir, key, fetch)
    return df["close"].astype(float).sort_index() if not df.empty else pd.Series(dtype="float64")
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_data.py -q` → PASS

- [ ] **Step 5: 커밋** — `git add simcore/config.py simcore/data.py tests/test_data.py && git commit -m "feat: 시장 지수 로더 + market_trend_period 설정"`

---

### Task 2: 엔진 하락장 가드

**Files:** Modify `simcore/engine.py`; Test `tests/test_engine_orders.py`

**Interfaces — Produces:** `evaluate_close(self, d, market, snaps, market_bearish: bool = False)`. 매수 후보 루프에서 `self.config.rules.bear_market_guard and market_bearish`이면 신규매수 후보를 만들지 않는다.

- [ ] **Step 1: 실패 테스트** — `tests/test_engine_orders.py`에 추가

```python
from dataclasses import replace
from simcore.config import Config
from simcore.engine import Engine
from simcore.models import Market, SymbolSnapshot


def _buy_snap(sym="AAA"):
    return SymbolSnapshot(sym, Market.KR, ("G1", "G7", "G5", "G4"), (), 100.0, 0.01, 1000.0,
                          green_score=19, red_score=0, buy_gate=True)


def test_bear_guard_blocks_new_buys_when_enabled():
    cfg = replace(Config(), rules=replace(Config().rules, bear_market_guard=True))
    eng = Engine(cfg); eng.start(__import__("datetime").date(2026, 1, 2), 1300.0)
    from datetime import date
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()}, market_bearish=True)
    assert not eng.states["국내형"].pending_buys        # 하락장 → 매수 차단


def test_bear_guard_off_allows_buys_in_downtrend():
    from datetime import date
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)   # guard off(기본)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()}, market_bearish=True)
    assert any(b.symbol == "AAA" for b in eng.states["국내형"].pending_buys)


def test_bear_guard_enabled_but_not_bearish_allows_buys():
    cfg = replace(Config(), rules=replace(Config().rules, bear_market_guard=True))
    from datetime import date
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()}, market_bearish=False)
    assert any(b.symbol == "AAA" for b in eng.states["국내형"].pending_buys)


def test_bear_guard_still_allows_sells_in_downtrend():
    cfg = replace(Config(), rules=replace(Config().rules, bear_market_guard=True))
    from datetime import date
    eng = Engine(cfg); eng.start(date(2026, 1, 2), 1300.0)
    # 보유 만들기
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": _buy_snap()})  # 평시 매수예약
    eng.fill_open(date(2026, 1, 5), Market.KR, {"AAA": 100.0}, 1300.0)
    # 하락장 + 강한 적신호 → 매도는 정상 예약
    s = SymbolSnapshot("AAA", Market.KR, (), ("R1", "R4", "R11"), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=15, buy_gate=False)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s}, market_bearish=True)
    assert any(ps.symbol == "AAA" for ps in eng.states["국내형"].pending_sells)
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_engine_orders.py -k bear_guard -q` → FAIL (TypeError market_bearish 또는 매수됨)

- [ ] **Step 3: 구현** — `simcore/engine.py` `evaluate_close` 시그니처와 매수 루프 수정

시그니처: `def evaluate_close(self, d: Date, market: Market, snaps: dict[str, SymbolSnapshot], market_bearish: bool = False) -> None:`

매수 후보 루프 진입 직전에 가드:
```python
            # 매수 후보 (하락장 가드: guard on + 하락장이면 신규매수 차단)
            if self.config.rules.bear_market_guard and market_bearish:
                continue
            held = set(st.portfolio.positions) | {b.symbol for b in st.pending_buys}
            for sym, s in snaps.items():
                ...
```
(주의: `continue`는 `for st in self.states.values()` 루프의 다음 캐릭터로 넘어가며, 쿨다운 감소·매도 판정은 이미 위에서 수행된 뒤이므로 그대로 유지된다.)

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_engine_orders.py -q` → PASS(기존 포함)

- [ ] **Step 5: 커밋** — `git add simcore/engine.py tests/test_engine_orders.py && git commit -m "feat: 엔진 하락장 가드 (지수 추세 필터 시 신규매수 차단)"`

---

### Task 3: 리플레이 지수 연동

**Files:** Modify `simcore/replay.py`; Test `tests/test_replay_integration.py`

**Interfaces — Consumes:** Task1 지수, Task2 엔진 param. **Produces:** `DataBundle.kr_index/us_index`; run_replay가 시장별 일자별 `market_bearish` 계산·전달.

- [ ] **Step 1: 실패 테스트** — `tests/test_replay_integration.py`에 추가

```python
def test_bear_guard_suppresses_buys_in_index_downtrend():
    import numpy as np, pandas as pd
    from datetime import date
    from dataclasses import replace
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 400, 220)
    df = pd.DataFrame({"open": up, "high": up + 2, "low": up - 2, "close": up,
                       "volume": np.linspace(1e3, 5e3, 220)}, index=idx)
    # 종목은 상승, 그러나 지수는 하락 추세 → 가드 on이면 매수 억제
    down_index = pd.Series(np.linspace(400, 100, 220), index=idx)
    bundle = DataBundle(kr={"AAA": df}, us={}, fx=pd.Series(1300.0, index=idx),
                        kr_index=down_index)
    cfg_on = replace(Config(), rules=replace(Config().rules, bear_market_guard=True))
    res_on = run_replay(cfg_on, bundle, date(2025, 9, 1), date(2026, 2, 1))
    res_off = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    n_on = 0 if res_on.trades.empty else (res_on.trades.side == "BUY").sum()
    n_off = 0 if res_off.trades.empty else (res_off.trades.side == "BUY").sum()
    assert n_on < n_off        # 가드가 하락장 매수를 억제
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_replay_integration.py -k bear_guard -q` → FAIL

- [ ] **Step 3: 구현** — `simcore/replay.py`

`DataBundle`에 필드 추가:
```python
@dataclass
class DataBundle:
    kr: dict[str, pd.DataFrame]
    us: dict[str, pd.DataFrame]
    fx: pd.Series
    kr_index: pd.Series | None = None
    us_index: pd.Series | None = None
```
run_replay 초기(신호 프레임 계산 부근)에서 지수 20일선·시장 매핑 준비:
```python
    period = config.signals.market_trend_period
    index_by_market = {Market.KR: bundle.kr_index, Market.US: bundle.us_index}
    sma_by_market = {m: (s.rolling(period).mean() if s is not None else None)
                     for m, s in index_by_market.items()}

    def _bearish(market, ts) -> bool:
        s = index_by_market.get(market); sma = sma_by_market.get(market)
        if s is None or sma is None:
            return False
        try:
            close = float(s.asof(ts)); avg = float(sma.asof(ts))
        except (KeyError, ValueError):
            return False
        if pd.isna(close) or pd.isna(avg):
            return False
        return close < avg
```
그리고 `engine.evaluate_close(d, market, snaps)` 호출을 `engine.evaluate_close(d, market, snaps, market_bearish=_bearish(market, ts))`로 교체.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_replay_integration.py -q` → PASS

- [ ] **Step 5: 커밋** — `git add simcore/replay.py tests/test_replay_integration.py && git commit -m "feat: 리플레이 지수 추세 연동(시장별 하락장 판정→가드)"`

---

### Task 4: CLI + 문서

**Files:** Modify `simcore/__main__.py`, `docs/trading-rules.md`, `README.md`

**Interfaces — Produces:** `--bear-guard` 플래그, 지수 로드해 bundle 주입.

- [ ] **Step 1: 구현** — `simcore/__main__.py`
  - argparse: `ap.add_argument("--bear-guard", action="store_true", help="하락장 가드(지수<20일선 시 신규매수 차단)")`.
  - 적용: `if args.bear_guard: cfg = replace(cfg, rules=replace(cfg.rules, bear_market_guard=True))`.
  - 지수 로드해 bundle에 주입:
    ```python
    kr_index = datamod.load_index("KR", start, end, cache) if kr_syms else None
    us_index = datamod.load_index("US", start, end, cache) if us_syms else None
    bundle = DataBundle(kr=..., us=..., fx=..., kr_index=kr_index, us_index=us_index)
    ```
    (기존 벤치마크용 k200/^GSPC 조회와 중복되지만, load_index는 캐시되므로 부담 적음. 벤치마크 블록은 그대로 두거나 load_index 재사용 — 최소 변경으로 bundle 주입만 추가.)

- [ ] **Step 2: 실행 확인** — `python -m simcore --start 2026-01-09 --end 2026-07-09 --bear-guard --kr-top 50 --us-top 50`가 인자 파싱·정상 기동(네트워크 있으면 완주). 최소한 `--help`에 `--bear-guard` 노출 확인: `python -m simcore --help | grep bear-guard`.

- [ ] **Step 3: trading-rules.md + README** — `docs/trading-rules.md`에 "하락장 가드" 절(지수 20일선 이탈 시 신규매수 차단, 기본 off, `--bear-guard`로 활성) 추가. README 리플레이 예시에 `--bear-guard` 옵션 한 줄 언급.

- [ ] **Step 4: 커밋** — `git add simcore/__main__.py docs/trading-rules.md README.md && git commit -m "feat: --bear-guard CLI + 하락장 가드 문서화"`

---

### Task 5: A/B 실험 + 검증

**Files:** Create `docs/experiments/replay_bear_guard_ab_2026-01-09_2026-07-09.md`

- [ ] **Step 1: 전체 회귀** — `python -m pytest -q` → 전부 통과.
- [ ] **Step 2: A/B 실행**
  - A(baseline): `python -m simcore --start 2026-01-09 --end 2026-07-09 --kr-top 50 --us-top 50 --out out/ab_off`
  - B(guard): `python -m simcore --start 2026-01-09 --end 2026-07-09 --kr-top 50 --us-top 50 --bear-guard --out out/ab_on`
  네트워크/캐시로 수 분. 실패 시 캐시 확인.
- [ ] **Step 3: 비교·기록** — 두 실행의 캐릭터별 TWR·MDD·거래수·승률을 표로 `docs/experiments/replay_bear_guard_ab_2026-01-09_2026-07-09.md`에 기록. **범용형 손실·MDD가 개선됐는지**(가드 on이 off 대비) 명시. 개선 없거나 악화 시 관찰·해석도 정직하게 기록(튜닝 방향 제언).
- [ ] **Step 4: 커밋** — `git add docs/experiments/ && git commit -m "test: 하락장 가드 A/B 리플레이(2026-01-09~07-09) 결과 기록"`

---

## Self-Review 체크
- **커버리지**: §2 규칙=Task2·3, §3 엔진=Task2, §4 데이터=Task1·3, §5 config=Task1, §6 라이브(무변경)=기본 off로 자동, §7 실험=Task5, §8 문서=Task4, §9 테스트=각 태스크. 매핑 완료.
- **타입 일관성**: `market_bearish`(Task2 param)↔run_replay 전달(Task3)↔기본 False. `DataBundle.kr_index/us_index`(Task3)↔`__main__` 주입(Task4)↔`load_index`(Task1). `market_trend_period`(Task1)↔replay 사용(Task3).
- **하위호환**: guard 기본 False → 모든 기존 호출/테스트 무영향(evaluate_close 신규 param 기본값, DataBundle 신규 필드 기본 None).
- **플레이스홀더 없음**: 로직 태스크 완결 코드. 실험(Task5)은 실행·기록 절차.
