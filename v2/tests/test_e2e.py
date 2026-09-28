"""goal 시나리오 — 가입부터 자동매도까지 HTTP 로 전 경로를 통과한다 (SPEC §9.3).

서비스 단위 테스트가 통과해도 라우터 조립·직렬화·권한이 어긋나면 사용자는 아무것도
못 한다. 이 파일은 **실제 API 표면**만 두드려서 그 조립을 고정한다.

시세는 가짜로 주입한다 — 자동매도 발동을 검증하려면 가격을 마음대로 움직여야 하고,
테스트가 장 시간이나 외부 네트워크에 의존해서는 안 된다.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from v2.backend import market as market_mod
from v2.backend import sellwall
from v2.backend.money import to_minor
from v2.backend.routers.accounts import router as accounts_router
from v2.backend.routers.orders import router as orders_router
from v2.tests.conftest import needs_db, signup

KR_SYMBOL = "005930"      # 삼성전자
PRICE = 70_000            # 테스트 내내 조작할 기준가


class FakePriceFeed:
    """`market` 모듈 자리에 꽂는 가짜. 라우터와 sellwall 이 쓰는 함수만 흉내낸다."""

    def __init__(self, price: float = PRICE):
        self.price = float(price)
        self.stale = False
        self.fail = False

    def current_price(self, kind: str, symbol: str) -> tuple[float, bool]:
        if self.fail:
            from v2.backend.trading import TradingError
            raise TradingError("PRICE_UNAVAILABLE", f"{symbol} 시세를 가져오지 못했습니다.")
        return self.price, self.stale


@pytest.fixture
def feed(monkeypatch):
    f = FakePriceFeed()
    monkeypatch.setattr(market_mod, "current_price", f.current_price)
    return f


@pytest.fixture
def extra_routers():
    return (accounts_router, orders_router)


def _accounts(client) -> dict[str, dict]:
    res = client.get("/api/accounts")
    assert res.status_code == 200, res.text
    return {a["kind"]: a for a in res.json()}


@needs_db
def test_goal_signup_to_auto_sell(auth_client, feed, sf):
    """가입 → 캐릭터 2개 → 매수 → 매도벽 → 자동매도 → 기록까지 한 번에."""
    c = auth_client

    # ① 가입 결과: 캐릭터 2개, 국내 1억 / 해외 약 $72,781
    accts = _accounts(c)
    assert set(accts) == {"KR", "US"}
    assert accts["KR"]["cash"] == 100_000_000
    assert accts["KR"]["currency"] == "KRW"
    assert accts["US"]["currency"] == "USD"
    assert 72_000 < accts["US"]["cash"] < 73_000      # 1억 ÷ 1372.6 − 환전수수료
    assert accts["KR"]["return_pct"] == 0.0
    kr_id = accts["KR"]["id"]

    # ② 매수 — 100주 @70,000 = 7,000,000 + 수수료 1,050
    res = c.post(f"/api/accounts/{kr_id}/buy", json={"symbol": KR_SYMBOL, "quantity": 100})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["trade"]["side"] == "BUY"
    assert body["trade"]["name"] == "삼성전자"          # 종목명이 응답에 실린다
    assert body["trade"]["price"] == 70_000
    assert body["trade"]["fee"] == 1_050
    assert body["position"]["quantity"] == 100
    assert body["account"]["cash"] == 100_000_000 - 7_000_000 - 1_050

    # ③ 보유 목록에 나온다
    positions = c.get(f"/api/accounts/{kr_id}/positions").json()
    assert len(positions) == 1
    pos = positions[0]
    assert pos["symbol"] == KR_SYMBOL and pos["name"] == "삼성전자"
    assert pos["sell_rule"] is None
    pos_id = pos["id"]
    avg = pos["avg_price"]                              # 수수료 포함 평단

    # ④ 매도벽 설정 −5% / +15% — 발동가를 서버가 계산해 내려준다
    res = c.put(f"/api/positions/{pos_id}/sell-rule",
                json={"stop_loss_pct": -5, "take_profit_pct": 15})
    assert res.status_code == 200, res.text
    rule = res.json()["sell_rule"]
    assert rule["active"] is True and rule["quantity"] == 100
    assert rule["stop_price"] == pytest.approx(round(avg * 0.95), abs=1)
    assert rule["take_price"] == pytest.approx(round(avg * 1.15), abs=1)

    # ⑤ 가격이 익절선 위로 → 감시 1틱에 자동 매도
    feed.price = rule["take_price"] + 500
    stats = sellwall.scan_once(sf, feed, now=datetime.now())
    assert stats["fired"] == 1, stats

    # ⑥ 포지션이 사라지고, 거래내역에 자동매도가 근거와 함께 남는다
    assert c.get(f"/api/accounts/{kr_id}/positions").json() == []
    trades = c.get(f"/api/accounts/{kr_id}/trades").json()
    assert trades["total"] == 2
    auto = [t for t in trades["items"] if t["reason"] == "AUTO_TAKE_PROFIT"]
    assert len(auto) == 1
    sold = auto[0]
    assert sold["quantity"] == 100
    assert sold["realized_pnl"] > 0
    # 발동선과 실제 체결가가 나란히 — 체결은 발동선이 아니라 현재가로 된다(SPEC §6.2)
    assert sold["trigger_price"] == rule["take_price"]
    assert sold["price"] == feed.price
    assert sold["price"] > sold["trigger_price"]

    # ⑦ 수익이 계좌에 반영된다
    after = _accounts(c)["KR"]
    assert after["position_count"] == 0
    assert after["cash"] > 100_000_000
    assert after["return_pct"] > 0

    # ⑧ 활동 로그가 전 과정을 담는다
    kinds = {e["kind"] for e in c.get(f"/api/accounts/{kr_id}/events").json()}
    assert {"BUY", "SELL", "RULE_SET", "AUTO_SELL_FIRED"} <= kinds


@needs_db
def test_stop_loss_fires_and_records_loss(auth_client, feed, sf):
    """손절 쪽도 같은 경로로 동작하고 손실이 기록된다."""
    c = auth_client
    kr_id = _accounts(c)["KR"]["id"]
    c.post(f"/api/accounts/{kr_id}/buy", json={"symbol": KR_SYMBOL, "quantity": 10})
    pos = c.get(f"/api/accounts/{kr_id}/positions").json()[0]
    rule = c.put(f"/api/positions/{pos['id']}/sell-rule",
                 json={"stop_loss_pct": -5, "take_profit_pct": 15}).json()["sell_rule"]

    feed.price = rule["stop_price"] - 100          # 손절선 아래로 급락
    assert sellwall.scan_once(sf, feed, now=datetime.now())["fired"] == 1

    sold = [t for t in c.get(f"/api/accounts/{kr_id}/trades").json()["items"]
            if t["side"] == "SELL"][0]
    assert sold["reason"] == "AUTO_STOP_LOSS"
    assert sold["realized_pnl"] < 0
    assert sold["tax"] > 0                          # KR 매도는 거래세를 문다


@needs_db
def test_price_failure_does_not_auto_sell(auth_client, feed, sf):
    """시세를 못 가져오면 자동매도하지 않는다 — 오래된 값으로 남의 돈을 팔지 않는다."""
    c = auth_client
    kr_id = _accounts(c)["KR"]["id"]
    c.post(f"/api/accounts/{kr_id}/buy", json={"symbol": KR_SYMBOL, "quantity": 10})
    pos = c.get(f"/api/accounts/{kr_id}/positions").json()[0]
    c.put(f"/api/positions/{pos['id']}/sell-rule", json={"take_profit_pct": 1})

    feed.fail = True
    stats = sellwall.scan_once(sf, feed, now=datetime.now())
    assert stats["fired"] == 0
    assert len(c.get(f"/api/accounts/{kr_id}/positions").json()) == 1   # 그대로 보유
    kinds = {e["kind"] for e in c.get(f"/api/accounts/{kr_id}/events").json()}
    assert "PRICE_STALE" in kinds


@needs_db
def test_manual_partial_sell_keeps_average(auth_client, feed):
    """부분 매도는 평단을 유지하고 수량만 줄인다."""
    c = auth_client
    kr_id = _accounts(c)["KR"]["id"]
    c.post(f"/api/accounts/{kr_id}/buy", json={"symbol": KR_SYMBOL, "quantity": 100})
    before = c.get(f"/api/accounts/{kr_id}/positions").json()[0]

    feed.price = PRICE + 5_000
    res = c.post(f"/api/accounts/{kr_id}/sell", json={"symbol": KR_SYMBOL, "quantity": 40})
    assert res.status_code == 200, res.text
    after = res.json()["position"]
    assert after["quantity"] == 60
    assert after["avg_price"] == before["avg_price"]


@needs_db
def test_cannot_touch_other_users_account(auth_client, app, feed):
    """남의 계정·포지션에는 접근할 수 없다(수평 권한 상승 차단)."""
    from fastapi.testclient import TestClient

    victim_kr = _accounts(auth_client)["KR"]["id"]
    auth_client.post(f"/api/accounts/{victim_kr}/buy",
                     json={"symbol": KR_SYMBOL, "quantity": 1})
    victim_pos = auth_client.get(f"/api/accounts/{victim_kr}/positions").json()[0]["id"]

    with TestClient(app) as attacker:
        assert signup(attacker, email="attacker@example.com").status_code == 200
        assert attacker.get(f"/api/accounts/{victim_kr}").status_code == 403
        assert attacker.get(f"/api/accounts/{victim_kr}/positions").status_code == 403
        assert attacker.post(f"/api/accounts/{victim_kr}/buy",
                             json={"symbol": KR_SYMBOL, "quantity": 1}).status_code == 403
        assert attacker.put(f"/api/positions/{victim_pos}/sell-rule",
                            json={"stop_loss_pct": -5}).status_code == 403


@needs_db
def test_cannot_buy_wrong_market_or_overspend(auth_client, feed):
    """캐릭터의 시장이 아닌 종목, 잔고를 넘는 수량은 사람이 읽을 이유와 함께 거부된다."""
    c = auth_client
    accts = _accounts(c)
    us_id = accts["US"]["id"]
    kr_id = accts["KR"]["id"]

    res = c.post(f"/api/accounts/{us_id}/buy", json={"symbol": KR_SYMBOL, "quantity": 1})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "MARKET_MISMATCH"

    res = c.post(f"/api/accounts/{kr_id}/buy", json={"symbol": KR_SYMBOL, "quantity": 999_999})
    assert res.status_code == 400
    err = res.json()["error"]
    assert err["code"] == "INSUFFICIENT_CASH"
    assert "원" in err["message"]            # 초보가 읽을 한국어 설명


@needs_db
def test_invalid_sell_rule_rejected(auth_client, feed):
    """손절은 음수, 익절은 양수여야 한다."""
    c = auth_client
    kr_id = _accounts(c)["KR"]["id"]
    c.post(f"/api/accounts/{kr_id}/buy", json={"symbol": KR_SYMBOL, "quantity": 1})
    pos_id = c.get(f"/api/accounts/{kr_id}/positions").json()[0]["id"]

    res = c.put(f"/api/positions/{pos_id}/sell-rule", json={"stop_loss_pct": 5})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_SELL_RULE"


@needs_db
def test_sell_rule_can_be_cleared(auth_client, feed, sf):
    """해제하면 가격이 발동선을 넘어도 팔리지 않는다."""
    c = auth_client
    kr_id = _accounts(c)["KR"]["id"]
    c.post(f"/api/accounts/{kr_id}/buy", json={"symbol": KR_SYMBOL, "quantity": 10})
    pos_id = c.get(f"/api/accounts/{kr_id}/positions").json()[0]["id"]
    rule = c.put(f"/api/positions/{pos_id}/sell-rule",
                 json={"take_profit_pct": 10}).json()["sell_rule"]

    assert c.delete(f"/api/positions/{pos_id}/sell-rule").status_code == 200
    feed.price = rule["take_price"] + 1_000
    assert sellwall.scan_once(sf, feed, now=datetime.now())["fired"] == 0
    assert len(c.get(f"/api/accounts/{kr_id}/positions").json()) == 1


@needs_db
def test_market_mismatch_reported_before_price_lookup(auth_client, monkeypatch):
    """시장이 안 맞으면 시세를 조회하기도 전에 그 사실을 알려준다.

    순서가 반대면 명백한 사용자 실수가 'PRICE_UNAVAILABLE'(서버가 시세를 못 가져옴)로
    보고돼, 사용자는 자기 실수 대신 장애를 의심하게 된다.
    """
    called = []

    def _boom(kind, symbol):
        called.append((kind, symbol))
        from v2.backend.trading import TradingError
        raise TradingError("PRICE_UNAVAILABLE", "시세 없음")

    monkeypatch.setattr(market_mod, "current_price", _boom)
    us_id = _accounts(auth_client)["US"]["id"]
    res = auth_client.post(f"/api/accounts/{us_id}/buy",
                           json={"symbol": KR_SYMBOL, "quantity": 1})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "MARKET_MISMATCH"
    assert called == [], "시장이 안 맞는데 시세를 조회했다"


def test_v2_test_helpers_do_not_pollute_shared_env():
    """v2 테스트 임포트가 v1 의 전제를 바꾸지 않는다(회귀 가드).

    `factories` 가 .env 전체를 os.environ 에 올리던 시절, v2 테스트를 먼저 수집하는 것만으로
    `tests/live/test_settings.py` 의 기본값 검증이 깨졌다.
    """
    import os

    import v2.tests.factories  # noqa: F401  — 임포트 부작용 자체가 검증 대상

    leaked = [k for k in ("KIS_ENV", "KIS_APP_KEY", "DATABASE_URL")
              if k in os.environ and not k.startswith("V2_")]
    assert leaked == [], f"v2 테스트가 공용 환경변수를 오염시켰다: {leaked}"
