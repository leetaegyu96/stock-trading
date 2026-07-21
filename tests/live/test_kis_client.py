import httpx, pytest, respx
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
                     client=httpx.Client(base_url=BASE), clock=lambda: clock_val,
                     sleep=lambda _s: None)  # 백오프 대기 없이 즉시 재시도


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
def test_reissues_token_on_expired_token_body_http500():
    """KIS는 토큰 만료를 401이 아니라 HTTP 500 + 본문(EGW00123)으로 응답한다.
    낡은 토큰으로는 계속 만료 에러가 나므로, 토큰을 재발급해야만 복구된다."""
    tokens = iter(["OLD", "NEW", "NEW", "NEW"])
    tok = respx.post(f"{BASE}/oauth2/tokenP").mock(side_effect=lambda req: httpx.Response(
        200, json={"access_token": next(tokens), "expires_in": 86400}))

    def handler(req):
        if req.headers.get("authorization") == "Bearer NEW":
            return httpx.Response(200, json={"output": {"stck_prpr": "5"}})
        return httpx.Response(500, json={"rt_cd": "1", "msg_cd": "EGW00123",
                                         "msg1": "기간이 만료된 token 입니다."})

    respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price").mock(side_effect=handler)
    c = _client()
    assert c.current_price("KR", "005930") == 5.0
    assert tok.call_count == 2          # 최초 발급 + 만료 감지 후 1회 재발급


@respx.mock
def test_reissues_token_on_expired_token_body_http200():
    """만료 응답이 HTTP 200 + 본문(msg1 "만료된 token")으로 오는 변형도 재발급으로 복구."""
    tokens = iter(["OLD", "NEW", "NEW", "NEW"])
    tok = respx.post(f"{BASE}/oauth2/tokenP").mock(side_effect=lambda req: httpx.Response(
        200, json={"access_token": next(tokens), "expires_in": 86400}))

    def handler(req):
        if req.headers.get("authorization") == "Bearer NEW":
            return httpx.Response(200, json={"output": {"stck_prpr": "7"}})
        return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "EGW00123",
                                         "msg1": "기간이 만료된 token 입니다."})

    respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price").mock(side_effect=handler)
    c = _client()
    assert c.current_price("KR", "005930") == 7.0
    assert tok.call_count == 2


@respx.mock
def test_generic_500_backs_off_without_reissuing_token():
    """일반 서버오류(500)는 토큰 문제가 아니므로 재발급하지 않고 백오프 재시도만."""
    tok = respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    route = respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price")
    route.side_effect = [
        httpx.Response(500, json={"rt_cd": "1", "msg_cd": "EGW00205", "msg1": "일시적 오류"}),
        httpx.Response(200, json={"output": {"stck_prpr": "9"}}),
    ]
    c = _client()
    assert c.current_price("KR", "005930") == 9.0
    assert route.call_count == 2
    assert tok.call_count == 1          # 일반 500엔 토큰 재발급 없음


@respx.mock
def test_expired_token_reissued_at_most_once_per_request():
    """재발급 후에도 계속 만료 에러면 발급폭주(EGW00133) 방지를 위해 요청당 1회만 재발급하고 포기."""
    tok = respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    route = respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price").mock(
        return_value=httpx.Response(500, json={"rt_cd": "1", "msg_cd": "EGW00123",
                                               "msg1": "기간이 만료된 token 입니다."}))
    c = _client()
    with pytest.raises(RuntimeError):
        c.current_price("KR", "005930")
    assert tok.call_count == 2          # 최초 발급 + 재발급 1회 (그 이상 재발급 안 함)
    assert route.call_count == 2        # 재발급 1회 → 실패 확인 1회, 즉시 포기


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


def _client_with_stub(monkeypatch, payload):
    c = KisClient.__new__(KisClient)  # __init__ 우회(네트워크·토큰 없음)
    monkeypatch.setattr(c, "_get", lambda path, tr_id, params: payload)
    return c


def test_execution_strength_kr_parses_cttr(monkeypatch):
    c = _client_with_stub(monkeypatch, {"output": {"cttr": "123.45"}})
    assert c.execution_strength("KR", "005930") == 123.45


def test_execution_strength_us_returns_none(monkeypatch):
    c = _client_with_stub(monkeypatch, {"output": {"cttr": "123.45"}})
    assert c.execution_strength("US", "AAPL") is None


def test_execution_strength_missing_field_returns_none(monkeypatch):
    c = _client_with_stub(monkeypatch, {"output": {}})
    assert c.execution_strength("KR", "005930") is None
@respx.mock
def test_overseas_price_class_share_ticker_converted_to_kis_format():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    route = respx.get(f"{BASE}/uapi/overseas-price/v1/quotations/price").mock(
        return_value=httpx.Response(200, json={"output": {"last": "455.10"}}))
    c = _client()
    assert c.current_price("US", "BRK-B") == 455.10
    assert route.calls.last.request.url.params["SYMB"] == "BRK/B"


@respx.mock
def test_overseas_daily_class_share_ticker_converted_to_kis_format():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    route = respx.get(f"{BASE}/uapi/overseas-price/v1/quotations/dailyprice").mock(
        return_value=httpx.Response(200, json={"output2": [
            {"xymd": "20260707", "open": "450", "high": "460",
             "low": "445", "clos": "455", "tvol": "1000"},
        ]}))
    c = _client()
    df = c.daily_bars("US", "BRK-B", date(2026, 7, 1), date(2026, 7, 7))
    assert df.iloc[0]["close"] == 455.0
    assert route.calls.last.request.url.params["SYMB"] == "BRK/B"


@respx.mock
def test_overseas_price_explicit_exchange_ticker_also_converted():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    route = respx.get(f"{BASE}/uapi/overseas-price/v1/quotations/price").mock(
        return_value=httpx.Response(200, json={"output": {"last": "455.10"}}))
    c = _client()
    assert c.current_price("US", "NYS:BRK-B") == 455.10
    assert route.calls.last.request.url.params["SYMB"] == "BRK/B"
