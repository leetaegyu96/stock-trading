import os, pandas as pd, pytest
from datetime import date, datetime
from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.live.orchestrator import Orchestrator
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory


class FakeKis:
    def __init__(self, bars): self.bars = bars     # {(market,symbol): DataFrame}
    def daily_bars(self, market, symbol, start, end): return self.bars[(market, symbol)]
    def current_price(self, market, symbol): return float(self.bars[(market, symbol)].iloc[-1]["close"])
    def market_cap_ranking(self, n): return ["005930"]


def _uptrend(n=80, end=None):
    idx = pd.bdate_range(end=end, periods=n) if end else pd.bdate_range("2026-01-01", periods=n)
    base = pd.Series(range(n), index=idx) * 1.0 + 100
    return pd.DataFrame({"open": base, "high": base + 2, "low": base - 1,
                         "close": base + 1, "volume": [1e6] * n}, index=idx)


@needs_db
def test_on_close_persists_signals_and_equity(session):
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    d0 = date(2026, 1, 1)
    eng.start(d0, 1300.0)
    kis = FakeKis({("KR", "005930"): _uptrend()})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    last = _uptrend().index[-1].date()
    orch.on_close(last, "KR", ["005930"])
    # equity 기록됨 + run_state 갱신 + 중복 호출 무시
    assert repo.get_run_state("KR").last_close_date == last
    orch.on_close(last, "KR", ["005930"])   # 멱등: 재실행 무시


@needs_db
def test_on_close_values_cross_market_holding_at_last_price(session):
    """범용형이 US 종목 보유 + KR on_close 시, 반대 시장 leg 가 평단(원가)이 아니라
    최근가로 평가되는지 (Important #1 회귀 가드)."""
    from simcore.models import Market, TradeReason
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    st = eng.states["범용형"]
    st.portfolio.convert_to_usd(1000.0, 1300.0)
    st.portfolio.buy(date(2026, 1, 2), "AAPL", Market.US, 5, 150.0, TradeReason.SIGNAL_BUY)
    # US 보유 종목의 일봉 캐시 (마지막 종가 190, 평단 150 과 다름)
    us_bars = pd.DataFrame({"open": [188.], "high": [192.], "low": [187.],
                            "close": [190.], "volume": [1e6]},
                           index=pd.to_datetime(["2026-01-05"]))
    repo.upsert_daily_bars("US", "AAPL", us_bars)
    kis = FakeKis({("KR", "005930"): _uptrend()})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    orch.on_close(_uptrend().index[-1].date(), "KR", ["005930"])
    # KR 마감인데도 US 보유 종목이 최근가(190)로 시드됨 — 원가(150) 폴백 아님
    assert orch._last_price["AAPL"] == 190.0


@needs_db
def test_on_close_idempotent_no_duplicate_equity(session):
    """같은 날 on_close 2회 호출 시 equity_curve 행이 늘지 않는다 (멱등 강화)."""
    from simcore.live import db
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    kis = FakeKis({("KR", "005930"): _uptrend()})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    last = _uptrend().index[-1].date()
    orch.on_close(last, "KR", ["005930"])
    with sf() as s:
        n1 = s.query(db.EquityPoint).count()
    orch.on_close(last, "KR", ["005930"])       # no-op
    with sf() as s:
        n2 = s.query(db.EquityPoint).count()
    assert n1 == n2 and n1 > 0


@needs_db
def test_on_close_persists_candidate_signal_status_scoped_to_market(session):
    """Task 3: on_close 는 그 시장의 후보(engine.last_candidates)를 signal_status 에
    기록해야 하고, 다른 시장의 on_close 가 그 행을 지우면 안 된다(market 스코프 교체)."""
    from simcore.live import db
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    kr_bars, us_bars = _uptrend(), _uptrend()
    kis = FakeKis({("KR", "005930"): kr_bars, ("US", "AAPL"): us_bars})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)

    kr_last = kr_bars.index[-1].date()
    orch.on_close(kr_last, "KR", ["005930"])

    kr_rows = repo.signal_status()
    assert kr_rows  # 후보 상태가 기록됨(005930 은 미보유 → 후보 평가 대상)
    assert all(r["market"] == "KR" for r in kr_rows)
    assert any(r["symbol"] == "005930" and r["kind"] == "후보" for r in kr_rows)
    with sf() as s:
        assert s.query(db.SignalStatusRow).count() == len(kr_rows)

    us_last = us_bars.index[-1].date()
    orch.on_close(us_last, "US", ["AAPL"])

    rows = repo.signal_status()
    markets = {r["market"] for r in rows}
    assert markets == {"KR", "US"}  # US 마감이 KR 행을 지우지 않음
    assert any(r["symbol"] == "005930" for r in rows)
    assert any(r["symbol"] == "AAPL" for r in rows)


@needs_db
def test_on_close_persists_holding_signal_status_with_stop_px(session):
    """Task 3: 보유 종목은 kind=보유 로 기록되고, stop_px=avg_price*(1+locked_stop_pct),
    close=self._last_price[symbol] 이어야 한다(스펙 §5 — run_replay 말미와 동일 계산)."""
    from simcore.models import Market, TradeReason
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 1, 2), "005930", Market.KR, 10, 100.0, TradeReason.SIGNAL_BUY)
    kr_bars = _uptrend()
    kis = FakeKis({("KR", "005930"): kr_bars})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    kr_last = kr_bars.index[-1].date()
    orch.on_close(kr_last, "KR", ["005930"])

    pos = st.portfolio.positions["005930"]
    rows = repo.signal_status()
    held = next(r for r in rows if r["symbol"] == "005930" and r["kind"] == "보유")
    assert held["market"] == "KR"
    assert held["stop_px"] == pytest.approx(pos.avg_price * (1 + pos.locked_stop_pct))
    assert held["close"] == pytest.approx(orch._last_price["005930"])
    # 기존 on_close 동작(회귀): 실제로 마감·멱등 처리는 그대로다.
    assert repo.get_run_state("KR").last_close_date == kr_last


@needs_db
def test_on_close_carries_forward_red_score_when_snapshot_missing(session):
    """보유 종목이 이번 마감의 universe 프레임에 없으면(상위 랭킹 이탈 등) red_score=0
    으로 기록하지 않고, 직전 signal_status(kind=보유) 행의 red_score 를 승계한다
    (스냅 누락을 '무위험'으로 오인하는 것 방지 — Task 3 리뷰 반영)."""
    from simcore.models import Market, TradeReason
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 1, 2), "005930", Market.KR, 10, 100.0, TradeReason.SIGNAL_BUY)
    # 직전 마감(예: 전일)에 기록된 보유 상태 — red_score=7
    repo.replace_signal_status([{
        "date": date(2026, 1, 5), "character": "국내형", "symbol": "005930",
        "market": "KR", "kind": "보유", "green_score": 0, "red_score": 7,
        "buy_gate": False, "status": "", "block_reason": "",
        "stop_px": 100.0, "trail_px": None, "close": 100.0,
    }], market="KR")
    kr_bars = _uptrend()
    kis = FakeKis({("KR", "005930"): kr_bars})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    # universe 가 비어있음 → 보유종목 005930 은 이번 마감 스냅에 없음(랭킹 이탈 등 시나리오)
    orch.on_close(date(2026, 1, 6), "KR", [])
    rows = repo.signal_status()
    held = next(r for r in rows if r["symbol"] == "005930" and r["kind"] == "보유")
    assert held["red_score"] == 7  # 0 으로 리셋되지 않고 직전값 승계


@needs_db
def test_on_close_defaults_red_score_zero_when_no_prior_row(session):
    """직전 signal_status 행 자체가 없으면(첫 마감 등) red_score=0 폴백은 유지된다."""
    from simcore.models import Market, TradeReason
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 1, 2), "005930", Market.KR, 10, 100.0, TradeReason.SIGNAL_BUY)
    kr_bars = _uptrend()
    kis = FakeKis({("KR", "005930"): kr_bars})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    orch.on_close(date(2026, 1, 6), "KR", [])
    rows = repo.signal_status()
    held = next(r for r in rows if r["symbol"] == "005930" and r["kind"] == "보유")
    assert held["red_score"] == 0


@needs_db
def test_on_tick_triggers_stop_loss(session):
    """보유 종목 현재가가 손절선 아래면 on_tick 이 즉시 청산 (유사봉 o=h=l=c)."""
    from simcore.models import Market, TradeReason
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 1, 2), "005930", Market.KR, 10, 100000.0,
                     TradeReason.SIGNAL_BUY)
    bars = {("KR", "005930"): pd.DataFrame(
        {"open": [92000.], "high": [92000.], "low": [92000.], "close": [92000.],
         "volume": [1.]}, index=pd.to_datetime(["2026-01-05"]))}     # 평단 대비 -8%
    orch = Orchestrator(eng, FakeKis(bars), repo, Config(), fx_provider=lambda d: 1300.0)
    orch.on_tick(date(2026, 1, 5), "KR")
    assert "005930" not in st.portfolio.positions       # 손절 청산됨


@needs_db
def test_on_open_applies_pending_flow(session):
    """대기 입출금이 개장 시 반영되고 capital_flows 에 기록된다."""
    from simcore.models import Currency
    from simcore.live import db
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    krw_before = eng.states["국내형"].portfolio.cash[Currency.KRW]
    repo.enqueue_flow("국내형", 5_000_000.0)
    orch = Orchestrator(eng, FakeKis({("KR", "005930"): _uptrend()}), repo, Config(),
                        fx_provider=lambda d: 1300.0)
    orch.on_open(date(2026, 1, 6), "KR", ["005930"])
    assert repo.pending_flow_requests() == []           # 큐 소비됨
    assert eng.states["국내형"].portfolio.cash[Currency.KRW] == krw_before + 5_000_000.0
    with sf() as s:
        assert s.query(db.CapitalFlowRow).count() == 1  # 원장 기록됨


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


class _IntradayFakeKis(FakeKis):
    """on_close 용 FakeKis 확장: 체결강도(None=조건 스킵) + 추세 지속 현재가(게이트 통과).

    daily_bars 는 실제 KIS 동작을 모사한다 — 조회 구간(end)이 `today` 이상이면
    당일자 "잠정"(장중 진행 중) 봉을 확정 히스토리에 덧붙여 반환한다. 이를 통해
    on_intraday 이 실수로 당일자(d)까지 확정 히스토리를 조회/캐시하면 그 잠정봉이
    그대로 DB에 영속되는 회귀 리스크를 테스트가 재현할 수 있다."""
    def __init__(self, bars, today):
        super().__init__(bars)
        self.today = today

    def execution_strength(self, market, symbol):
        return None

    def current_price(self, market, symbol):
        # 마지막 확정 종가보다 한 걸음 더 오른 값 — 잠정봉이 상승 추세를 이어가야
        # G7(신고가 돌파) 등 게이트 신호가 유지된다(평탄 종가는 게이트 미통과).
        return float(self.bars[(market, symbol)].iloc[-1]["close"]) + 1.0

    def daily_bars(self, market, symbol, start, end):
        base = self.bars[(market, symbol)]
        if pd.Timestamp(end) >= pd.Timestamp(self.today):
            last = base.iloc[-1]
            partial = pd.DataFrame({
                "open": [last["open"]], "high": [last["high"]],
                "low": [last["low"]], "close": [float(last["close"]) + 1.0],
                "volume": [last["volume"]],
            }, index=[pd.Timestamp(self.today)])
            return pd.concat([base, partial])
        return base


@pytest.fixture
def intraday_orch_setup(session):
    from dataclasses import replace
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    eng = Engine(cfg)
    eng.start(date(2026, 1, 1), 1300.0)
    # 확정 히스토리: 2026-07-20(테스트 당일) 이전 영업일까지의 상승 추세(매수 게이트 통과 조건).
    hist = _uptrend(80, end=pd.Timestamp("2026-07-17"))
    kis = _IntradayFakeKis({("KR", "005930"): hist}, today=date(2026, 7, 20))
    orch = Orchestrator(eng, kis, repo, cfg, fx_provider=lambda d: 1300.0)
    return orch, repo, "KR", "005930"


@needs_db
def test_on_intraday_buys_and_persists(intraday_orch_setup):
    """게이트 통과 종목이 장중에 즉시 체결되고 상태가 영속된다."""
    from simcore.live import db
    orch, repo, market, sym = intraday_orch_setup   # fixture가 신호=매수 상태로 구성
    now = datetime(2026, 7, 20, 10, 0, 0)
    orch.on_intraday(now, date(2026, 7, 20), market, [sym])
    # 엔진 포지션에 체결 반영
    assert any(sym in st.portfolio.positions for st in orch.engine.states.values())
    # 거래가 DB에 append 되었는지
    with repo.sf() as s:
        assert s.query(db.TradeRow).count() > 0


@needs_db
def test_on_intraday_never_persists_today_daily_bar(intraday_orch_setup):
    """Critical 회귀 가드: on_intraday 은 장중 잠정봉을 당일(d)자 확정 일봉으로
    DB 에 영속시켜서는 안 된다. 그렇게 되면 이후 on_close(d, ...) 이 캐시 커트오프
    (cached.index.max()==d) 때문에 재조회를 건너뛰고, 잠정가가 그대로 당일 확정
    종가로 굳어버린다(신호 평가·record_equity·이후 이력 오염)."""
    from simcore.live import db
    orch, repo, market, sym = intraday_orch_setup
    d = date(2026, 7, 20)
    now = datetime(d.year, d.month, d.day, 10, 0, 0)
    orch.on_intraday(now, d, market, [sym])
    with repo.sf() as s:
        rows = (s.query(db.DailyBarRow)
                 .filter_by(market=market, symbol=sym, date=d).all())
        assert rows == [], (
            "on_intraday 이 당일(d)자 잠정봉을 확정 일봉으로 DB에 저장했다 — "
            "on_close 캐시 커트오프가 그 이후 재조회를 영구히 건너뛴다."
        )
        max_date = (s.query(db.DailyBarRow)
                     .filter_by(market=market, symbol=sym)
                     .order_by(db.DailyBarRow.date.desc()).first())
        assert max_date is not None and max_date.date < d


@needs_db
def test_on_intraday_skips_symbol_that_raises_and_still_buys_good_one(session):
    """안전 감사 Fix 2 크래시가드: 유니버스 안의 한 종목 처리 중 예외(체결강도 조회
    실패)가 나도 on_intraday 전체가 죽지 않는다. 그 종목만 통째로 스킵(원자적 —
    snaps/strengths 둘 다 미기록)되고, 나머지 유효 종목은 정상적으로 매수+영속된다."""
    from dataclasses import replace
    from simcore.live import db
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    cfg = Config(rules=replace(Config().rules, intraday_enabled=True))
    eng = Engine(cfg)
    eng.start(date(2026, 1, 1), 1300.0)
    good_hist = _uptrend(80, end=pd.Timestamp("2026-07-17"))
    bad_hist = _uptrend(80, end=pd.Timestamp("2026-07-17"))
    kis = _IntradayFakeKis(
        {("KR", "005930"): good_hist, ("KR", "000660"): bad_hist},
        today=date(2026, 7, 20))
    orig_strength = kis.execution_strength

    def boom(market, symbol):
        if symbol == "000660":
            raise RuntimeError("체결강도 조회 실패(모의 — per-symbol 크래시 재현)")
        return orig_strength(market, symbol)
    kis.execution_strength = boom

    orch = Orchestrator(eng, kis, repo, cfg, fx_provider=lambda d: 1300.0)
    now = datetime(2026, 7, 20, 10, 0, 0)
    orch.on_intraday(now, date(2026, 7, 20), "KR", ["005930", "000660"])  # 죽지 않아야 함

    assert any("005930" in st.portfolio.positions for st in eng.states.values())
    assert not any("000660" in st.portfolio.positions for st in eng.states.values())
    with repo.sf() as s:
        assert s.query(db.TradeRow).count() > 0


def test_orchestrator_lock_is_reentrant_rlock():
    """안전 감사 Fix 1: Orchestrator 는 __init__ 에서 재진입 가능한 락(threading.RLock)을
    만들어야 한다 — 같은 스레드에서 두 번 acquire 해도 데드락 없이 통과해야 각 핸들러
    내부의 중첩 호출(예: 락 안에서 다른 락-보호 헬퍼 호출)이 안전하다."""
    import threading
    eng = Engine(Config())
    eng.start(date(2026, 1, 1), 1300.0)
    orch = Orchestrator(eng, None, None, Config(), fx_provider=lambda d: 1300.0)
    assert hasattr(orch, "_lock")
    assert type(orch._lock) is type(threading.RLock())  # 일반 Lock 이 아니라 RLock
    acquired = orch._lock.acquire(timeout=1)
    assert acquired, "첫 acquire 부터 실패"
    reentered = orch._lock.acquire(timeout=1)   # 재진입: 일반 Lock 이면 여기서 타임아웃/False
    assert reentered, "재진입 acquire 실패 — RLock 이 아니거나 잘못 구성됨"
    orch._lock.release()
    orch._lock.release()


def test_evaluate_intraday_survives_position_vanishing_mid_iteration():
    """안전 감사 Fix 3 방어 검증: engine.evaluate_intraday 의 매도 루프가
    `for sym in list(st.portfolio.positions):` 로 키를 스냅샷한 뒤에도, 그 사이 포지션이
    사라지면(동시성 하에서 가능) `st.portfolio.positions[sym]` 직접 인덱싱은 KeyError 를
    낸다 — `.get(sym)` + `if pos is None: continue` 로 방어되어야 한다.
    포지션 딕셔너리를 get() 호출 시점에 스스로 키를 지우는 딕셔너리로 바꿔치기해서
    '조회 시점에 막 사라진 포지션'을 결정적으로 재현한다."""
    from simcore.models import Market, SymbolSnapshot, TradeReason

    class _VanishingPositions(dict):
        def get(self, key, default=None):
            self.pop(key, None)   # 조회되는 순간 사라지는 포지션을 재현
            return default

    cfg = Config()
    eng = Engine(cfg)
    eng.start(date(2026, 1, 1), 1300.0)
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 1, 2), "005930", Market.KR, 10, 100.0, TradeReason.SIGNAL_BUY)
    st.portfolio.positions = _VanishingPositions(st.portfolio.positions)

    snaps = {"005930": SymbolSnapshot("005930", Market.KR, (), (), 100.0, 0.0, 1.0,
                                       green_score=0, red_score=0, buy_gate=False)}
    eq = eng.snapshot({"005930": 100.0}, 1300.0)
    # Fix 3 적용 전이었다면 st.portfolio.positions[sym] 직접 인덱싱에서 KeyError.
    eng.evaluate_intraday(date(2026, 1, 6), Market.KR, snaps, {}, 1300.0,
                          datetime(2026, 1, 6, 10, 0, 0), day_equity=eq, cur_equity=eq)
