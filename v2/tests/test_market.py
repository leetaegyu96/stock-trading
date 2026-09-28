"""시세·종목 리스트 (SPEC §4). 네트워크 없이 FakeKis 로만 검증한다."""
from __future__ import annotations

from datetime import date

import pytest

from v2.backend import market
from v2.backend.trading import TradingError
from v2.tests.factories import FakeClock, FakeKis, make_bars

TODAY = date(2026, 9, 28)          # 월요일 — 주말 보정으로 테스트가 흔들리지 않게 고정


def _svc(kis, clock=None, **kw):
    return market.MarketService(kis, clock=clock or FakeClock(),
                                today=lambda: TODAY, **kw)


def _kr_kis(price=11_000.0):
    closes = [10_000.0 + 100 * i for i in range(25)]       # 10,000 → 12,400
    vols = [1_000.0] * 24 + [3_000.0]
    bars = make_bars(closes, end=TODAY, volumes=vols)
    return FakeKis(prices={"005930": price}, bars={"005930": bars},
                   ranking=["005930", "000660"]), closes, vols


# ---------------------------------------------------------------- 현재가

def test_현재가_정상이면_stale_아님():
    kis, _, _ = _kr_kis()
    price, stale = _svc(kis).current_price("KR", "005930")
    assert (price, stale) == (11_000.0, False)
    assert kis.bar_calls == []          # 성공 시 일봉을 굳이 받지 않는다


def test_현재가_실패시_마지막_종가로_폴백하고_stale():
    kis, closes, _ = _kr_kis()
    kis.prices["005930"] = None         # 실시간 조회 실패
    price, stale = _svc(kis).current_price("KR", "005930")
    assert (price, stale) == (closes[-1], True)


def test_현재가와_일봉_모두_실패면_PRICE_UNAVAILABLE():
    kis = FakeKis(prices={"005930": None}, bars={"005930": None})
    with pytest.raises(TradingError) as e:
        _svc(kis).current_price("KR", "005930")
    assert e.value.code == "PRICE_UNAVAILABLE"


# ---------------------------------------------------------------- 종목 리스트

def test_종목리스트_필드_계산():
    kis, closes, vols = _kr_kis(price=12_000.0)
    info = _svc(kis).list_stocks("KR")[0]

    assert info.symbol == "005930"
    assert info.name == "삼성전자"                      # simcore.names 매핑
    assert info.price == 12_000.0
    # 마지막 봉이 '오늘'이므로 전일 종가는 그 앞 봉이다
    assert info.change_pct == pytest.approx(
        (12_000.0 / closes[-2] - 1) * 100, abs=1e-3)
    assert info.spark7 == [round(c, 4) for c in closes[-7:]]
    assert info.week_change_pct == pytest.approx(
        (12_000.0 / closes[-7] - 1) * 100, abs=1e-3)
    assert info.volume == vols[-1]
    avg20 = sum(vols[-20:]) / 20
    assert info.volume_vs_avg == pytest.approx(3_000.0 / avg20, abs=1e-3)
    assert info.high_52w == pytest.approx(max(closes) * 1.01, abs=1e-2)
    assert info.low_52w == pytest.approx(min(closes) * 0.99, abs=1e-2)
    assert info.stale is False


def test_종목리스트_60초_TTL_캐시():
    kis, _, _ = _kr_kis()
    clock = FakeClock()
    svc = _svc(kis, clock=clock)

    svc.list_stocks("KR")
    calls = len(kis.price_calls)
    svc.list_stocks("KR")
    assert len(kis.price_calls) == calls        # TTL 내: 재조회 없음

    clock.advance(61)
    svc.list_stocks("KR")
    assert len(kis.price_calls) > calls         # TTL 만료 후: 재조회


def test_일봉은_당일_1회만_조회():
    kis, _, _ = _kr_kis()
    kis.prices["005930"] = None                 # 폴백 경로로 일봉을 쓰게 한다
    svc = _svc(kis)
    svc.current_price("KR", "005930")
    svc.current_price("KR", "005930")
    assert kis.bar_calls == [("KR", "005930")]


def test_clear_cache_후에는_다시_조회():
    kis, _, _ = _kr_kis()
    svc = _svc(kis)
    svc.list_stocks("KR")
    before = len(kis.price_calls)
    svc.clear_cache()
    svc.list_stocks("KR")
    assert len(kis.price_calls) > before


def test_일부_종목_실패해도_나머지는_노출():
    closes = [100.0 + i for i in range(10)]
    kis = FakeKis(prices={"005930": 110.0, "000660": None},
                  bars={"005930": make_bars(closes, end=TODAY), "000660": None},
                  ranking=["005930", "000660"])
    out = _svc(kis).list_stocks("KR")
    assert [i.symbol for i in out] == ["005930"]


def test_KR은_시총랭킹_US는_sp500(monkeypatch):
    kis, _, _ = _kr_kis()
    assert _svc(kis).symbols("KR") == ["005930", "000660"]
    assert kis.rank_calls == 1

    monkeypatch.setattr(market._universe, "sp500",
                        lambda cache_dir: ["AAPL", "MSFT"])
    assert _svc(kis).symbols("US") == ["AAPL", "MSFT"]


def test_종목_상세는_최근_30일_일봉_포함():
    closes = [100.0 + i for i in range(60)]
    kis = FakeKis(prices={"005930": 200.0},
                  bars={"005930": make_bars(closes, end=TODAY)})
    detail = _svc(kis).get_stock("KR", "005930")
    assert len(detail.bars) == 30
    assert detail.bars[-1]["close"] == closes[-1]
    assert detail.to_dict()["symbol"] == "005930"


# ---------------------------------------------------------------- 모듈 기본 인스턴스

def test_configure_로_기본_서비스_교체():
    kis, _, _ = _kr_kis()
    market.configure(kis, clock=FakeClock(), today=lambda: TODAY)
    try:
        assert market.current_price("KR", "005930")[0] == 11_000.0
        assert market.list_stocks("KR")[0].symbol == "005930"
        market.clear_cache()
    finally:
        market._default = None
