"""인증 계층 테스트 — SPEC §9.1 '인증'·'가입 원자성'·'권한' 항목."""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends
from sqlalchemy import select

from v2.backend import auth, money
from v2.backend.deps import SESSION_COOKIE, require_account, require_position
from v2.backend.models import Account, LoginAttempt, Position, User
from v2.tests.conftest import TEST_FX_RATE, TEST_USER, signup

OTHER = {"email": "someone.else@example.com", "password": "otherpassword1",
         "nickname": "옆사람"}

# 소유권 의존성은 라우트에 걸려야 의미가 있다. B 가 쓸 시그니처 그대로 얹은 검증용 라우터.
probe_router = APIRouter(prefix="/api/probe")


@probe_router.get("/accounts/{account_id}")
def _probe_account(account: Account = Depends(require_account)) -> dict:
    return {"id": account.id, "kind": account.kind}


@probe_router.get("/positions/{position_id}")
def _probe_position(position: Position = Depends(require_position)) -> dict:
    return {"id": position.id, "symbol": position.symbol}


@pytest.fixture
def extra_routers():
    return (probe_router,)


def _error(res) -> dict:
    body = res.json()
    assert set(body) == {"error"}, body            # SPEC §7 오류 봉투 형식 고정
    assert set(body["error"]) == {"code", "message"}, body
    assert body["error"]["message"], "메시지는 비어 있으면 안 된다"
    return body["error"]


# ── 가입 ────────────────────────────────────────────────────────────────────

def test_signup_creates_user_and_two_accounts(client, db):
    res = signup(client)
    assert res.status_code == 200, res.text
    assert res.json()["email"] == TEST_USER["email"]

    user = db.scalar(select(User).where(User.email == TEST_USER["email"]))
    assert user is not None and user.nickname == TEST_USER["nickname"]

    accounts = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    by_kind = {a.kind: a for a in accounts}
    assert set(by_kind) == {"KR", "US"}

    kr = by_kind["KR"]
    assert (kr.currency, kr.cash_minor, kr.seed_minor) == ("KRW", 100_000_000, 100_000_000)

    us = by_kind["US"]
    expected_cents = money.krw_to_usd_cents(100_000_000, TEST_FX_RATE)
    assert (us.currency, us.cash_minor, us.seed_minor) == ("USD", expected_cents, expected_cents)
    # 1억 원 상당의 달러 — 환전 수수료 0.1% 차감 후 7만 달러대
    assert 7_200_000 < us.cash_minor < 7_400_000


def test_password_is_hashed_not_stored_plaintext(client, db):
    signup(client)
    user = db.scalar(select(User).where(User.email == TEST_USER["email"]))
    assert TEST_USER["password"] not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")
    assert auth.verify_password(user.password_hash, TEST_USER["password"])
    assert not auth.verify_password(user.password_hash, "틀린비밀번호12345")


def test_weak_password_rejected(client, db):
    res = signup(client, password="short123")          # 9자 — 최소 10자 미만
    assert res.status_code == 400
    assert _error(res)["code"] == "INVALID_INPUT"
    assert db.scalar(select(User)) is None             # 사용자도 만들어지지 않는다


def test_invalid_email_rejected(client, db):
    for bad in ("not-an-email", "a@b", "@example.com", "사람 @example.com"):
        res = signup(client, email=bad)
        assert res.status_code == 400, bad
        assert _error(res)["code"] == "INVALID_INPUT"
    assert db.scalar(select(User)) is None


def test_duplicate_email_rejected(client, db):
    assert signup(client).status_code == 200
    res = signup(client, nickname="다른닉네임")
    assert res.status_code == 409
    assert _error(res)["code"] == "EMAIL_TAKEN"
    assert len(db.scalars(select(User)).all()) == 1


def test_duplicate_email_is_case_insensitive(client, db):
    assert signup(client, email="Trader@Example.com").status_code == 200
    res = signup(client, email="TRADER@EXAMPLE.COM")
    assert res.status_code == 409
    assert _error(res)["code"] == "EMAIL_TAKEN"
    users = db.scalars(select(User)).all()
    assert len(users) == 1
    assert users[0].email == "trader@example.com"      # 소문자로 정규화 저장


def test_signup_is_atomic_when_account_creation_fails(sf, db, monkeypatch):
    """캐릭터 생성이 깨지면 사용자도 남지 않아야 한다(SPEC §3)."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("환전 실패")

    monkeypatch.setattr(auth.money, "krw_to_usd_cents", boom)
    with sf() as session:
        with pytest.raises(RuntimeError):
            auth.signup(session, TEST_USER["email"], TEST_USER["password"],
                        TEST_USER["nickname"], TEST_FX_RATE)

    assert db.scalar(select(User)) is None
    assert db.scalar(select(Account)) is None


# ── 로그인 ──────────────────────────────────────────────────────────────────

def test_login_success(client):
    signup(client)
    client.cookies.clear()
    res = client.post("/api/auth/login",
                      json={"email": TEST_USER["email"], "password": TEST_USER["password"]})
    assert res.status_code == 200
    assert res.json()["nickname"] == TEST_USER["nickname"]
    assert client.cookies.get(SESSION_COOKIE)
    assert client.get("/api/auth/me").status_code == 200


def test_login_accepts_different_email_case(client):
    signup(client)
    client.cookies.clear()
    res = client.post("/api/auth/login",
                      json={"email": TEST_USER["email"].upper(),
                            "password": TEST_USER["password"]})
    assert res.status_code == 200


def test_login_with_wrong_password_fails(client, db):
    signup(client)
    client.cookies.clear()
    res = client.post("/api/auth/login",
                      json={"email": TEST_USER["email"], "password": "wrongpassword1"})
    assert res.status_code == 401
    assert _error(res)["code"] == "UNAUTHORIZED"
    assert not client.cookies.get(SESSION_COOKIE)
    assert db.scalars(select(LoginAttempt)).all()      # 실패가 기록된다


def test_login_with_unknown_email_fails(client):
    res = client.post("/api/auth/login",
                      json={"email": "nobody@example.com", "password": "whateverpass1"})
    assert res.status_code == 401
    assert _error(res)["code"] == "UNAUTHORIZED"


def test_login_rate_limited_after_five_failures(client):
    signup(client)
    client.cookies.clear()
    bad = {"email": TEST_USER["email"], "password": "wrongpassword1"}
    for _ in range(auth.RATE_MAX_FAILS):
        assert client.post("/api/auth/login", json=bad).status_code == 401

    res = client.post("/api/auth/login", json=bad)
    assert res.status_code == 429
    assert _error(res)["code"] == "RATE_LIMITED"

    # 올바른 비밀번호라도 잠금 창 안에서는 통과시키지 않는다.
    res = client.post("/api/auth/login",
                      json={"email": TEST_USER["email"], "password": TEST_USER["password"]})
    assert res.status_code == 429


def test_successful_login_clears_failure_count(client):
    signup(client)
    client.cookies.clear()
    bad = {"email": TEST_USER["email"], "password": "wrongpassword1"}
    for _ in range(auth.RATE_MAX_FAILS - 1):
        assert client.post("/api/auth/login", json=bad).status_code == 401

    ok = client.post("/api/auth/login",
                     json={"email": TEST_USER["email"], "password": TEST_USER["password"]})
    assert ok.status_code == 200
    # 실패 카운트가 남아 있었다면 아래 401 이 429 가 됐을 것이다.
    assert client.post("/api/auth/login", json=bad).status_code == 401


# ── 세션 ────────────────────────────────────────────────────────────────────

def test_session_cookie_is_httponly(client):
    res = signup(client)
    raw = res.headers["set-cookie"].lower()
    assert raw.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in raw
    assert "samesite=lax" in raw
    assert "path=/" in raw


def test_me_requires_authentication(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert _error(res)["code"] == "UNAUTHORIZED"


def test_me_rejects_forged_token(client):
    signup(client)
    client.cookies.clear()
    # 서명이 맞지 않는 토큰 — 만료·위조·쓰레기값은 전부 같은 401 로 수렴해야 한다.
    client.cookies.set(SESSION_COOKIE, "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.forged")
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert _error(res)["code"] == "UNAUTHORIZED"


def test_me_returns_profile(auth_client):
    res = auth_client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.json() == auth_client.user


def test_logout_clears_session(auth_client):
    assert auth_client.post("/api/auth/logout").status_code == 200
    assert not auth_client.cookies.get(SESSION_COOKIE)
    assert auth_client.get("/api/auth/me").status_code == 401


def test_logout_requires_authentication(client):
    res = client.post("/api/auth/logout")
    assert res.status_code == 401
    assert _error(res)["code"] == "UNAUTHORIZED"


# ── 소유권(수평 권한 상승 차단) ──────────────────────────────────────────────

def _accounts_of(db, email: str) -> list[Account]:
    user = db.scalar(select(User).where(User.email == email))
    return list(db.scalars(select(Account).where(Account.user_id == user.id)))


def test_own_account_is_accessible(auth_client, db):
    account = _accounts_of(db, TEST_USER["email"])[0]
    res = auth_client.get(f"/api/probe/accounts/{account.id}")
    assert res.status_code == 200
    assert res.json()["id"] == account.id


def test_other_users_account_is_forbidden(client, db):
    signup(client, **OTHER)                        # 피해자
    victim = _accounts_of(db, OTHER["email"])[0]
    client.cookies.clear()
    signup(client)                                 # 공격자로 로그인 상태 전환

    res = client.get(f"/api/probe/accounts/{victim.id}")
    assert res.status_code == 403
    assert _error(res)["code"] == "FORBIDDEN"


def test_unknown_account_is_not_found(auth_client):
    res = auth_client.get("/api/probe/accounts/999999")
    assert res.status_code == 404
    assert _error(res)["code"] == "NOT_FOUND"


def test_account_access_requires_login(client, db):
    signup(client, **OTHER)
    account = _accounts_of(db, OTHER["email"])[0]
    client.cookies.clear()
    res = client.get(f"/api/probe/accounts/{account.id}")
    assert res.status_code == 401
    assert _error(res)["code"] == "UNAUTHORIZED"


def test_other_users_position_is_forbidden(client, db):
    signup(client, **OTHER)
    victim = _accounts_of(db, OTHER["email"])[0]
    position = Position(account_id=victim.id, symbol="005930", quantity=10,
                        avg_price_minor=70_000)
    db.add(position)
    db.commit()

    client.cookies.clear()
    signup(client)
    res = client.get(f"/api/probe/positions/{position.id}")
    assert res.status_code == 403
    assert _error(res)["code"] == "FORBIDDEN"


def test_own_position_is_accessible(auth_client, db):
    account = _accounts_of(db, TEST_USER["email"])[0]
    position = Position(account_id=account.id, symbol="005930", quantity=3,
                        avg_price_minor=70_000)
    db.add(position)
    db.commit()

    res = auth_client.get(f"/api/probe/positions/{position.id}")
    assert res.status_code == 200
    assert res.json()["symbol"] == "005930"


def test_unknown_position_is_not_found(auth_client):
    res = auth_client.get("/api/probe/positions/999999")
    assert res.status_code == 404
    assert _error(res)["code"] == "NOT_FOUND"
