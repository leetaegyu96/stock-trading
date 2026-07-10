import shutil
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simcore.live import db
from simcore.models import Market

from tests.dashboard.conftest import needs_db
from dashboard.backend.app import app, get_kis, get_sf


def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "dashboard" / "frontend"
_DIST_DIR = _FRONTEND_DIR / "dist"


@pytest.fixture(autouse=True)
def _clean_frontend_dist():
    """빌드 산출물(dist)이 테스트 전후로 남지 않도록 보장한다(hermetic)."""
    shutil.rmtree(_DIST_DIR, ignore_errors=True)
    yield
    shutil.rmtree(_DIST_DIR, ignore_errors=True)


def test_root_without_dist_returns_friendly_message():
    assert not _DIST_DIR.exists()
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "빌드" in r.text


def test_root_serves_built_index_when_dist_exists():
    _DIST_DIR.mkdir(parents=True, exist_ok=True)
    (_DIST_DIR / "index.html").write_text("<html><body>dashboard-app</body></html>", encoding="utf-8")

    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "dashboard-app" in r.text
    assert "text/html" in r.headers["content-type"]


def test_api_and_ws_not_shadowed_by_spa_when_dist_exists():
    _DIST_DIR.mkdir(parents=True, exist_ok=True)
    (_DIST_DIR / "index.html").write_text("<html><body>dashboard-app</body></html>", encoding="utf-8")

    # /api/* 는 여전히 JSON.
    r_api = TestClient(app).get("/api/health")
    assert r_api.status_code == 200
    assert r_api.json() == {"status": "ok"}

    # 존재하지 않는 /api/* 경로는 SPA index.html 로 폴백하지 않고 404.
    r_unknown_api = TestClient(app).get("/api/does-not-exist")
    assert r_unknown_api.status_code == 404

    # 알 수 없는 클라이언트 라우트는 index.html 로 폴백(SPA 라우팅 지원).
    r_fallback = TestClient(app).get("/characters/some-name")
    assert r_fallback.status_code == 200
    assert "dashboard-app" in r_fallback.text


def _seed_full(s, name="테스트형"):
    """test_summary._seed 와 동일한 손계산 검증용 시드(자산곡선/입출금/포지션/현금/거래)."""
    s.merge(db.CharacterRow(name=name, base_currency="KRW"))

    s.add(db.CapitalFlowRow(date=date(2026, 1, 1), character=name,
                             amount_krw=10_000_000.0, fx_rate=1.0))
    s.add(db.CapitalFlowRow(date=date(2026, 1, 3), character=name,
                             amount_krw=2_000_000.0, fx_rate=1.0))

    for d, eq in [
        (1, 10_000_000.0),
        (2, 10_500_000.0),
        (3, 12_700_000.0),
        (4, 12_900_000.0),
        (5, 12_800_000.0),
    ]:
        s.add(db.EquityPoint(ts=datetime(2026, 1, d, 15, 30), character=name, equity_krw=eq))

    s.add(db.PositionRow(character=name, symbol="AAPL", market=Market.US.value,
                          quantity=5, avg_price=150.0, opened_date=date(2026, 1, 2)))

    s.add(db.CashBalance(character=name, currency="KRW", amount=500_000.0))
    s.add(db.CashBalance(character=name, currency="USD", amount=1_000.0))

    pnls = [1000.0, -500.0, 2000.0, -300.0, 1500.0]
    for i, pnl in enumerate(pnls):
        s.add(db.TradeRow(
            ts=datetime(2026, 1, i + 1, 9, 30), date=date(2026, 1, i + 1),
            character=name, symbol=f"SYM{i}", market=Market.KR.value, side="SELL",
            quantity=1, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_SELL",
            green_count=0, red_count=0, fired=[], realized_pnl=pnl,
        ))


@needs_db
def test_list_characters_returns_all_seeded_cards(sf):
    with sf() as s:
        s.merge(db.CharacterRow(name="국내형", base_currency="KRW"))
        s.merge(db.CharacterRow(name="해외형", base_currency="USD"))
        s.merge(db.CharacterRow(name="범용형", base_currency="KRW"))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    cards = r.json()
    assert len(cards) == 3
    for card in cards:
        assert set(card) == {
            "name", "base_currency", "markets", "benchmark_delta", "benchmark_available",
            "total_asset_krw", "twr", "pnl_krw", "today_pnl_pct",
            "equity_spark", "n_positions", "cash_krw",
        }

    # 각 카드가 name 으로 식별되고, DEFAULT_CHARACTERS 매핑(시장/기준통화)이 반영된다.
    by_name = {c["name"]: c for c in cards}
    assert set(by_name) == {"국내형", "해외형", "범용형"}
    assert by_name["국내형"]["base_currency"] == "KRW"
    assert by_name["국내형"]["markets"] == ["KR"]
    assert by_name["해외형"]["base_currency"] == "USD"
    assert by_name["해외형"]["markets"] == ["US"]
    assert by_name["범용형"]["base_currency"] == "KRW"
    assert by_name["범용형"]["markets"] == ["KR", "US"]
    assert all(c["benchmark_delta"] is None for c in cards)
    assert all(c["benchmark_available"] is False for c in cards)


@needs_db
def test_list_characters_card_uses_avg_price_fallback_without_daily_bars(sf):
    with sf() as s:
        _seed_full(s)
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    [card] = r.json()
    assert card["n_positions"] == 1
    assert card["cash_krw"] == 500_000.0 + 1_000.0 * 1300.0
    # daily_bars 미시딩 → avg_price(150.0) 폴백, fx_rate 상수(1300.0)
    assert card["total_asset_krw"] == card["cash_krw"] + 5 * 150.0 * 1300.0


@needs_db
def test_list_characters_card_uses_latest_daily_bar_close_when_available(sf):
    with sf() as s:
        _seed_full(s)
        s.add(db.DailyBarRow(market=Market.US.value, symbol="AAPL", date=date(2026, 1, 1),
                              open=150.0, high=155.0, low=149.0, close=155.0, volume=1000.0))
        s.add(db.DailyBarRow(market=Market.US.value, symbol="AAPL", date=date(2026, 1, 2),
                              open=155.0, high=162.0, low=154.0, close=160.0, volume=1200.0))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    [card] = r.json()
    # 최신(2026-01-02) 종가 160.0 사용
    assert card["total_asset_krw"] == card["cash_krw"] + 5 * 160.0 * 1300.0


@needs_db
def test_character_detail_returns_metrics(sf):
    with sf() as s:
        _seed_full(s)
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters/테스트형")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    body = r.json()
    assert body["twr"] == pytest.approx(0.0752, rel=1e-3)
    assert body["n_trades"] == 5
    assert body["win_rate"] == pytest.approx(0.6)


@needs_db
def test_character_equity_returns_points_in_order(sf):
    with sf() as s:
        _seed_full(s)
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters/테스트형/equity")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    points = r.json()
    assert len(points) == 5
    assert points[0]["ts"] == "2026-01-01T15:30:00"
    assert points[0]["equity_krw"] == 10_000_000.0
    assert points[-1]["equity_krw"] == 12_800_000.0


class _FakeKis:
    """일부 심볼은 성공(가격 반환), 일부는 예외를 던지는 KIS 더블."""

    def __init__(self, prices: dict[tuple[str, str], float], fail: "set[tuple[str, str]]" = frozenset()):
        self._prices = prices
        self._fail = fail

    def current_price(self, market: str, symbol: str) -> float:
        if (market, symbol) in self._fail:
            raise RuntimeError(f"KIS 현재가 조회 실패: {market}/{symbol}")
        return self._prices[(market, symbol)]


@needs_db
def test_character_positions_returns_rows(sf):
    with sf() as s:
        _seed_full(s)
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    app.dependency_overrides[get_kis] = lambda: _FakeKis(prices={("US", "AAPL"): 160.0})
    try:
        r = TestClient(app).get("/api/characters/테스트형/positions")
    finally:
        app.dependency_overrides.pop(get_sf, None)
        app.dependency_overrides.pop(get_kis, None)

    assert r.status_code == 200
    [pos] = r.json()
    assert pos["symbol"] == "AAPL"
    assert pos["market"] == "US"
    assert pos["quantity"] == 5
    assert pos["avg_price"] == 150.0
    assert pos["opened_date"] == "2026-01-02"
    # KIS 현재가 병합: 성공분은 live 가격 사용, stale=False.
    assert pos["current_price"] == 160.0
    assert pos["eval_value"] == 5 * 160.0
    assert pos["pnl_pct"] == pytest.approx(160.0 / 150.0 - 1.0)
    assert pos["stale"] is False


@needs_db
def test_character_positions_falls_back_when_kis_fails(sf):
    with sf() as s:
        _seed_full(s)
        s.add(db.DailyBarRow(market="US", symbol="AAPL", date=date(2026, 1, 2),
                              open=155.0, high=162.0, low=154.0, close=158.0, volume=1200.0))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    app.dependency_overrides[get_kis] = lambda: _FakeKis(prices={}, fail={("US", "AAPL")})
    try:
        r = TestClient(app).get("/api/characters/테스트형/positions")
    finally:
        app.dependency_overrides.pop(get_sf, None)
        app.dependency_overrides.pop(get_kis, None)

    assert r.status_code == 200
    [pos] = r.json()
    # KIS 실패 → daily_bars 마지막 종가로 폴백, stale=True.
    assert pos["current_price"] == 158.0
    assert pos["eval_value"] == 5 * 158.0
    assert pos["pnl_pct"] == pytest.approx(158.0 / 150.0 - 1.0)
    assert pos["stale"] is True


@needs_db
def test_character_trades_returns_rows_and_respects_limit(sf):
    with sf() as s:
        _seed_full(s)
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r_all = TestClient(app).get("/api/characters/테스트형/trades")
        r_limited = TestClient(app).get("/api/characters/테스트형/trades?limit=2")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r_all.status_code == 200
    body = r_all.json()
    trades = body["items"]
    assert body["total"] == 5
    assert len(trades) == 5
    assert trades[0]["symbol"] == "SYM4"  # 최신순
    assert trades[0]["realized_pnl"] == 1500.0

    assert r_limited.status_code == 200
    limited_body = r_limited.json()
    assert len(limited_body["items"]) == 2
    assert limited_body["total"] == 5  # total은 limit 적용 전 건수


@needs_db
def test_character_trades_filters_by_query_params(sf):
    with sf() as s:
        _seed_full(s)
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r_symbol = TestClient(app).get("/api/characters/테스트형/trades?symbol=SYM2")
        r_side = TestClient(app).get("/api/characters/테스트형/trades?side=SELL")
        r_date = TestClient(app).get(
            "/api/characters/테스트형/trades?date_from=2026-01-02&date_to=2026-01-02"
        )
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r_symbol.status_code == 200
    body = r_symbol.json()
    assert body["total"] == 1
    assert body["items"][0]["symbol"] == "SYM2"

    assert r_side.status_code == 200
    assert r_side.json()["total"] == 5  # _seed_full 은 전부 SELL

    assert r_date.status_code == 200
    date_body = r_date.json()
    assert date_body["total"] == 1
    assert date_body["items"][0]["date"] == "2026-01-02"


@needs_db
def test_character_lifecycles_endpoint_groups_entry_to_exit(sf):
    with sf() as s:
        s.merge(db.CharacterRow(name="국내형", base_currency="KRW"))
        s.add(db.TradeRow(ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
                           character="국내형", symbol="005930", market=Market.KR.value, side="BUY",
                           quantity=10, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_BUY",
                           green_count=0, red_count=0, fired=[], realized_pnl=0.0,
                           decision_type="BUY", trigger_rule="R1"))
        s.add(db.TradeRow(ts=datetime(2026, 1, 2, 9, 30), date=date(2026, 1, 2),
                           character="국내형", symbol="005930", market=Market.KR.value, side="SELL",
                           quantity=10, price=1100.0, fee=0.0, tax=0.0, reason="SIGNAL_SELL",
                           green_count=0, red_count=0, fired=[], realized_pnl=1000.0,
                           decision_type="SELL", trigger_rule="R2"))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters/국내형/lifecycles")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    [life] = r.json()
    assert life["symbol"] == "005930"
    assert life["name"] == "삼성전자"
    assert life["open"] is False
    assert life["entry_date"] == "2026-01-01"
    assert life["exit_date"] == "2026-01-02"
    assert life["realized_pnl_sum"] == 1000.0
    assert life["qty_peak"] == 10
    assert life["entry_trigger"] == "R1"
    assert len(life["trades"]) == 2
    assert life["trades"][0]["signal_summary"] != ""


@needs_db
def test_trades_include_name_and_signal_summary(sf):
    with sf() as s:
        s.merge(db.CharacterRow(name="국내형", base_currency="KRW"))
        s.add(db.TradeRow(
            ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
            character="국내형", symbol="005930", market=Market.KR.value, side="BUY",
            quantity=1, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_BUY",
            green_count=2, red_count=0, fired=["G1", "G2"], realized_pnl=0.0,
            green_score=20, red_score=0,
        ))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters/국내형/trades")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    rows = r.json()["items"]
    assert rows, "거래가 있어야 함"
    t = rows[0]
    assert "name" in t and "signal_summary" in t and "signal_detail" in t
    assert "green_score" in t and "red_score" in t
    assert t["name"] == "삼성전자"
    assert t["green_score"] == 20
    assert t["red_score"] == 0
    assert t["signal_summary"] != ""
    assert t["signal_detail"]
    assert t["decision_type"] == "BUY"
    assert t["trigger_rule"] == ""


@needs_db
def test_forced_sell_trade_renders_decision_based_summary(sf):
    with sf() as s:
        s.merge(db.CharacterRow(name="국내형", base_currency="KRW"))
        s.add(db.TradeRow(
            ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
            character="국내형", symbol="005930", market=Market.KR.value, side="SELL",
            quantity=1, price=1000.0, fee=0.0, tax=0.0, reason="FORCED_SELL",
            green_count=0, red_count=0, fired=[], realized_pnl=-500.0,
            green_score=0, red_score=0,
            decision_type="FORCED_SELL", trigger_rule="R18",
        ))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters/국내형/trades")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    [t] = r.json()["items"]
    assert t["decision_type"] == "FORCED_SELL"
    assert t["trigger_rule"] == "R18"
    assert "강제 전량매도" in t["signal_summary"]


@needs_db
def test_trades_with_unknown_decision_type_does_not_500(sf):
    """감사 Minor: DB에 손상/미확정 decision_type(빈 문자열 등 DecisionType이 아닌
    값)이 들어 있어도 /trades 는 500이 아니라 200을 반환하고, 임의의 결정을
    지어내지 않고 레거시(점수 기반) 요약으로 폴백해야 한다."""
    with sf() as s:
        s.merge(db.CharacterRow(name="국내형", base_currency="KRW"))
        s.add(db.TradeRow(
            ts=datetime(2026, 1, 1, 9, 30), date=date(2026, 1, 1),
            character="국내형", symbol="005930", market=Market.KR.value, side="SELL",
            quantity=1, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_SELL",
            green_count=0, red_count=2, fired=["R1", "R4"], realized_pnl=-500.0,
            green_score=0, red_score=9,
            decision_type="BOGUS_UNKNOWN", trigger_rule="",
        ))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters/국내형/trades")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    [t] = r.json()["items"]
    assert t["decision_type"] == "BOGUS_UNKNOWN"  # 원본 값은 그대로 노출(폴백은 요약 로직만)
    assert t["signal_summary"] != ""               # 레거시 경로로 요약 생성(크래시 없음)


@needs_db
def test_dashboard_endpoint_shape(sf):
    with sf() as s:
        # movers: KR·US 각 2봉 → 등락률 계산 대상
        s.add(db.DailyBarRow(market=Market.KR.value, symbol="005930", date=date(2026, 1, 1),
                              open=70000.0, high=71000.0, low=69500.0, close=70000.0, volume=1000.0))
        s.add(db.DailyBarRow(market=Market.KR.value, symbol="005930", date=date(2026, 1, 2),
                              open=70000.0, high=73000.0, low=69800.0, close=73500.0, volume=1200.0))
        s.add(db.DailyBarRow(market=Market.US.value, symbol="AAPL", date=date(2026, 1, 1),
                              open=150.0, high=155.0, low=149.0, close=155.0, volume=1000.0))
        s.add(db.DailyBarRow(market=Market.US.value, symbol="AAPL", date=date(2026, 1, 2),
                              open=155.0, high=155.0, low=140.0, close=140.0, volume=1200.0))

        # 캐릭터(국내형) 보유·거래
        s.merge(db.CharacterRow(name="국내형", base_currency="KRW"))
        s.add(db.PositionRow(character="국내형", symbol="005930", market=Market.KR.value,
                              quantity=10, avg_price=68000.0, opened_date=date(2026, 1, 1)))
        for d, eq in [(1, 10_000_000.0), (2, 10_300_000.0)]:
            s.add(db.EquityPoint(ts=datetime(2026, 1, d, 15, 30), character="국내형", equity_krw=eq))
        s.add(db.TradeRow(
            ts=datetime(2026, 1, 2, 9, 30), date=date(2026, 1, 2),
            character="국내형", symbol="005930", market=Market.KR.value, side="BUY",
            quantity=10, price=68000.0, fee=0.0, tax=0.0, reason="SIGNAL_BUY",
            green_count=1, red_count=0, fired=["G1"], realized_pnl=0.0,
        ))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/dashboard")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    d = r.json()
    assert "movers" in d and "characters" in d and "recent_trades" in d

    # movers: 시장별 up/down, name(display_name) 포함
    assert set(d["movers"]) >= {"KR", "US"}
    kr_up = d["movers"]["KR"]["up"]
    assert kr_up and kr_up[0]["symbol"] == "005930"
    assert kr_up[0]["name"] == "삼성전자"
    assert kr_up[0]["change_pct"] == pytest.approx(73500.0 / 70000.0 - 1.0)
    us_down = d["movers"]["US"]["down"]
    assert us_down and us_down[0]["symbol"] == "AAPL"
    assert us_down[0]["change_pct"] == pytest.approx(140.0 / 155.0 - 1.0)

    # 캐릭터 요약은 DEFAULT_CHARACTERS 3개
    assert len(d["characters"]) == 3
    by_name = {c["name"]: c for c in d["characters"]}
    assert set(by_name) == {"국내형", "해외형", "범용형"}
    kr_char = by_name["국내형"]
    assert kr_char["n_positions"] == 1
    assert kr_char["best"]["symbol"] == "005930"
    assert kr_char["best"]["name"] == "삼성전자"
    assert kr_char["today_pnl_pct"] == pytest.approx(10_300_000.0 / 10_000_000.0 - 1.0)
    # 보유 없는 캐릭터는 best/worst 없음
    assert by_name["해외형"]["n_positions"] == 0
    assert by_name["해외형"]["best"] is None

    # 최근 체결: name(display_name) 포함
    assert d["recent_trades"]
    t = d["recent_trades"][0]
    assert t["symbol"] == "005930" and t["name"] == "삼성전자"
    assert t["character"] == "국내형"


@needs_db
def test_market_status_endpoint_returns_per_market_dates(sf):
    with sf() as s:
        s.add(db.RunState(market="KR", last_open_date=date(2026, 7, 10),
                           last_close_date=date(2026, 7, 10), last_fx_rate=1.0))
        s.add(db.RunState(market="US", last_open_date=date(2026, 7, 9),
                           last_close_date=date(2026, 7, 9), last_fx_rate=1300.0))
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/status")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    rows = r.json()
    by_market = {row["market"]: row for row in rows}
    assert set(by_market) == {"KR", "US"}
    assert by_market["KR"]["last_close_date"] == "2026-07-10"
    assert by_market["US"]["last_close_date"] == "2026-07-09"


@needs_db
def test_character_flows_returns_rows(sf):
    with sf() as s:
        _seed_full(s)
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        r = TestClient(app).get("/api/characters/테스트형/flows")
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert r.status_code == 200
    flows = r.json()
    assert len(flows) == 2
    assert flows[0]["amount_krw"] == 10_000_000.0
    assert flows[1]["amount_krw"] == 2_000_000.0
