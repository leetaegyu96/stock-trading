import os, pandas as pd, pytest
from datetime import date
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


def _uptrend(n=80):
    idx = pd.bdate_range("2026-01-01", periods=n)
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
