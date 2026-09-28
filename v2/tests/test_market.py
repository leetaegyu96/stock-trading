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
    info = _svc(kis).list_stocks("KR")[0][0]

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
    out, total = _svc(kis).list_stocks("KR")
    assert [i.symbol for i in out] == ["005930"]
    assert total == 2      # 실패한 종목도 유니버스에는 들어 있다


def test_KR은_시총랭킹_US는_sp500(monkeypatch):
    kis, _, _ = _kr_kis()
    assert _svc(kis).symbols("KR") == ["005930", "000660"]
    assert kis.rank_calls == 1

    # US 는 v2 전용 유니버스(_us_universe). 네트워크·캐시를 타지 않도록 폴백만 남긴다.
    svc = _svc(kis)
    monkeypatch.setattr(market.MarketService, "_us_universe",
                        lambda self: ["AAPL", "MSFT"])
    assert svc.symbols("US") == ["AAPL", "MSFT"]


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
        assert market.list_stocks("KR")[0][0].symbol == "005930"
        market.clear_cache()
    finally:
        market._default = None


# ── 페이지네이션 ─────────────────────────────────────────────────────────
def _paged_kis(n: int = 75):
    """n 종목짜리 가짜 유니버스."""
    syms = [f"{i:06d}" for i in range(n)]
    closes = [100.0 + i for i in range(40)]
    return FakeKis(prices={s: 100.0 for s in syms},
                   bars={s: make_bars(closes, end=TODAY) for s in syms},
                   ranking=syms)


def test_페이지네이션_구간만_돌려준다():
    svc = _svc(_paged_kis(75))
    first, total = svc.list_stocks("KR", offset=0, limit=30)
    assert total == 75 and len(first) == 30
    second, _ = svc.list_stocks("KR", offset=30, limit=30)
    assert len(second) == 30
    assert {i.symbol for i in first}.isdisjoint({i.symbol for i in second})
    last, _ = svc.list_stocks("KR", offset=60, limit=30)
    assert len(last) == 15, "마지막 페이지는 남은 만큼만"


def test_페이지네이션은_요청_구간만_조회한다():
    """500종목을 한꺼번에 채우면 KIS 호출이 1,000회다 — 비용이 보이는 만큼에 비례해야 한다."""
    kis = _paged_kis(75)
    svc = _svc(kis)
    svc.list_stocks("KR", offset=0, limit=10)
    assert len(kis.price_calls) <= 10, f"요청 범위 밖까지 조회했다: {len(kis.price_calls)}"


def test_페이지별로_캐시된다():
    kis = _paged_kis(60)
    svc = _svc(kis)
    svc.list_stocks("KR", offset=0, limit=30)
    before = len(kis.price_calls)
    svc.list_stocks("KR", offset=0, limit=30)          # 같은 페이지 → 캐시
    assert len(kis.price_calls) == before
    svc.list_stocks("KR", offset=30, limit=30)         # 다른 페이지 → 새로 조회
    assert len(kis.price_calls) > before


def test_범위를_벗어난_offset은_빈_페이지():
    svc = _svc(_paged_kis(10))
    items, total = svc.list_stocks("KR", offset=999, limit=30)
    assert items == [] and total == 10


# ── 초보용 유니버스 구성 ─────────────────────────────────────────────────
def test_파생상품은_유니버스에서_제외된다():
    """거래량·등락률 랭킹 상위는 레버리지·인버스 ETF 가 점령한다.

    '주식 초보' 모의투자에서 설명 없이 인버스2X 를 목록 앞에 놓는 건 도움이 아니라 함정이다.
    """
    d = market.MarketService._is_derivative
    for name in ("KODEX 200선물인버스2X", "KODEX 인버스", "TIGER 200선물인버스2X",
                 "KODEX 2차전지산업레버리지", "KBSTAR 코스닥150선물인버스",
                 "ACE 미국30년국채", "삼성 레버리지 WTI원유 ETN"):
        assert d(name) is True, f"걸러졌어야 한다: {name}"
    for name in ("삼성전자", "SK하이닉스", "두산에너빌리티", "한국비엔씨",
                 "현대차", "POSCO홀딩스"):
        assert d(name) is False, f"보통주인데 걸러졌다: {name}"


def test_파생상품_필터가_빈_이름에_안전하다():
    assert market.MarketService._is_derivative("") is False


def test_시총랭킹_실패한_유니버스는_캐시하지_않는다():
    """일시적 실패가 하루 종일 목록 순서를 망치면 안 된다.

    실제로 시총 랭킹이 간헐적으로 0행을 반환했고, 그때 만들어진(잡주가 앞에 오는) 순서가
    하루치로 캐시돼 첫 화면이 '동국생명과학, 더블유에스아이…' 로 채워졌다.
    """
    kis, _, _ = _kr_kis()
    svc = _svc(kis)

    def build(partial: bool):
        def _fake():
            svc._kr_universe_partial = partial
            return ["005930", "000660"]
        return _fake

    svc._kr_universe = build(True)          # 시총 랭킹 실패 상황
    svc.symbols("KR")
    assert "KR" not in svc._symbols, "골격 없는 유니버스가 캐시됐다"

    svc._kr_universe = build(False)         # 정상 복구
    svc.symbols("KR")
    assert "KR" in svc._symbols, "정상 유니버스는 캐시되어야 한다"
