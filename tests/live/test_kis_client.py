import httpx, respx
from datetime import date
from simcore.live.kis_client import KisClient, InMemoryTokenStore
from simcore.live.ratelimit import RateLimiter
from simcore.live.settings import LiveSettings

BASE = "https://openapi.koreainvestment.com:9443"


def _client(clock_val=1000.0):
    s = LiveSettings(kis_app_key="AK", kis_app_secret="SK",
                     database_url="postgresql://x", kis_env="real")
    limiter = RateLimiter(1e9)  # 테스트에선 무제한
    return KisClient(s, InMemoryTokenStore(), limiter,
                     client=httpx.Client(base_url=BASE), clock=lambda: clock_val)


@respx.mock
def test_token_issued_once_and_cached():
    tok = respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "TOKEN", "expires_in": 86400}))
    price = respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price").mock(
        return_value=httpx.Response(200, json={"output": {"stck_prpr": "70000"}}))
    c = _client()
    assert c.current_price("KR", "005930") == 70000.0
    assert c.current_price("KR", "005930") == 70000.0
    assert tok.call_count == 1          # 토큰은 1회만 발급
    assert price.call_count == 2


@respx.mock
def test_daily_bars_parsed():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice").mock(
        return_value=httpx.Response(200, json={"output2": [
            {"stck_bsop_date": "20260707", "stck_oprc": "100", "stck_hgpr": "110",
             "stck_lwpr": "90", "stck_clpr": "105", "acml_vol": "1000"},
        ]}))
    c = _client()
    df = c.daily_bars("KR", "005930", date(2026, 7, 1), date(2026, 7, 7))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.iloc[0]["close"] == 105.0


@respx.mock
def test_daily_bars_empty_output2_returns_empty_dataframe():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice").mock(
        return_value=httpx.Response(200, json={"output2": []}))
    c = _client()
    df = c.daily_bars("KR", "005930", date(2026, 7, 1), date(2026, 7, 7))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 0


@respx.mock
def test_reissues_token_on_401():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    route = respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price")
    route.side_effect = [httpx.Response(401, json={}),
                         httpx.Response(200, json={"output": {"stck_prpr": "5"}})]
    c = _client()
    assert c.current_price("KR", "005930") == 5.0
    assert route.call_count == 2


@respx.mock
def test_market_cap_ranking():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    respx.get(f"{BASE}/uapi/domestic-stock/v1/ranking/market-cap").mock(
        return_value=httpx.Response(200, json={"output": [
            {"mksc_shrn_iscd": "005930"}, {"mksc_shrn_iscd": "000660"},
            {"mksc_shrn_iscd": "373220"}]}))
    c = _client()
    assert c.market_cap_ranking(2) == ["005930", "000660"]


@respx.mock
def test_overseas_price():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    respx.get(f"{BASE}/uapi/overseas-price/v1/quotations/price").mock(
        return_value=httpx.Response(200, json={"output": {"last": "191.24"}}))
    c = _client()
    assert c.current_price("US", "NAS:AAPL") == 191.24
