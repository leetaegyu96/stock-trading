"""KIS 현재가 병합 + 폴백(daily_bars 마지막 종가) 테스트."""
from __future__ import annotations

from datetime import date

from simcore.live import db
from simcore.live.repository import Repository

from tests.dashboard.conftest import needs_db
from dashboard.backend.live_prices import current_prices


class _FakeKis:
    """일부 심볼은 성공(가격 반환), 일부는 예외를 던진다."""

    def __init__(self, prices: dict[tuple[str, str], float], fail: "set[tuple[str, str]]"):
        self._prices = prices
        self._fail = fail

    def current_price(self, market: str, symbol: str) -> float:
        if (market, symbol) in self._fail:
            raise RuntimeError(f"KIS 현재가 조회 실패: {market}/{symbol}")
        return self._prices[(market, symbol)]


@needs_db
def test_current_prices_uses_live_price_when_kis_succeeds(sf):
    repo = Repository(sf)
    kis = _FakeKis(prices={("KR", "005930"): 71000.0}, fail=set())

    result = current_prices(kis, {"KR": ["005930"]}, repo)

    assert result == {"005930": {"price": 71000.0, "stale": False}}


@needs_db
def test_current_prices_falls_back_to_daily_bars_close_on_kis_failure(sf):
    with sf() as s:
        s.add(db.DailyBarRow(market="US", symbol="AAPL", date=date(2026, 1, 1),
                              open=150.0, high=155.0, low=149.0, close=150.0, volume=1000.0))
        s.add(db.DailyBarRow(market="US", symbol="AAPL", date=date(2026, 1, 2),
                              open=155.0, high=162.0, low=154.0, close=160.0, volume=1200.0))
        s.commit()

    repo = Repository(sf)
    kis = _FakeKis(prices={}, fail={("US", "AAPL")})

    result = current_prices(kis, {"US": ["AAPL"]}, repo)

    # 폴백은 daily_bars 의 최신(2026-01-02) 종가를 사용하고 stale=True.
    assert result == {"AAPL": {"price": 160.0, "stale": True}}


@needs_db
def test_current_prices_mixed_success_and_failure(sf):
    with sf() as s:
        s.add(db.DailyBarRow(market="KR", symbol="000660", date=date(2026, 1, 2),
                              open=100.0, high=110.0, low=95.0, close=105.0, volume=500.0))
        s.commit()

    repo = Repository(sf)
    kis = _FakeKis(prices={("KR", "005930"): 71000.0}, fail={("KR", "000660")})

    result = current_prices(kis, {"KR": ["005930", "000660"]}, repo)

    assert result == {
        "005930": {"price": 71000.0, "stale": False},
        "000660": {"price": 105.0, "stale": True},
    }


@needs_db
def test_current_prices_stale_with_no_price_when_no_daily_bars_either(sf):
    repo = Repository(sf)
    kis = _FakeKis(prices={}, fail={("US", "TSLA")})

    result = current_prices(kis, {"US": ["TSLA"]}, repo)

    assert result == {"TSLA": {"price": None, "stale": True}}
