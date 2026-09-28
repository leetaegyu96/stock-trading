"""v2 백엔드 테스트 공용 픽스처.

실 DB(Postgres)를 쓴다 — SQLite 로 바꾸면 JSONB·CITEXT 성 제약·행 잠금 같은
운영에서 실제로 문제가 되는 부분을 검증하지 못한다. `V2_TEST_DATABASE_URL` 이
없으면 전부 skip (v1 `tests/live/conftest.py` 와 같은 관용구).
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from v2.backend import deps
from v2.backend.db import create_all, make_engine, make_session_factory
from v2.backend.models import Base
from v2.backend.routers.auth import router as auth_router
from v2.backend.settings import load_settings

# 가입 시 해외 캐릭터 환전에 쓰는 고정 환율 — 기대값을 계산으로 검증할 수 있게 고정한다.
TEST_FX_RATE = 1372.6

TEST_USER = {"email": "trader@example.com", "password": "verysecret123", "nickname": "초보투자자"}


def _test_db_url() -> str | None:
    """환경변수 우선, 없으면 .env 를 읽는 설정에서 가져온다."""
    url = os.environ.get("V2_TEST_DATABASE_URL")
    if url:
        return url
    try:
        return load_settings().test_database_url
    except Exception:
        return None


TEST_DB_URL = _test_db_url()
needs_db = pytest.mark.skipif(not TEST_DB_URL, reason="V2_TEST_DATABASE_URL 미설정")


def make_test_app(*routers) -> FastAPI:
    """테스트용 앱 조립기. app.py 는 통합 담당이 만들므로 여기서는 라우터만 끼운다.

    다른 작업자는 자기 라우터를 넘겨(`make_test_app(auth_router, my_router)`) 쓰거나,
    `extra_routers` 픽스처를 override 해 기본 `client` 에 얹으면 된다.
    """
    app = FastAPI(title="v2 test app")
    deps.install_error_handler(app)
    for r in routers:
        app.include_router(r)
    return app


@pytest.fixture(scope="session")
def engine():
    if not TEST_DB_URL:
        pytest.skip("V2_TEST_DATABASE_URL 미설정")
    eng = make_engine(TEST_DB_URL)
    create_all(eng)
    return eng


@pytest.fixture(scope="session")
def sf(engine):
    """세션 팩토리. 앱 의존성과 테스트가 같은 엔진(=같은 트랜잭션 가시성)을 쓴다."""
    return make_session_factory(engine)


@pytest.fixture(autouse=True)
def _clean_db(engine):
    """매 테스트마다 전 테이블 TRUNCATE — 앞 테스트가 남긴 행에 기대지 않게 한다."""
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db(sf):
    with sf() as session:
        yield session


@pytest.fixture
def settings():
    """테스트용 설정. 쿠키를 TestClient(http://testserver)가 실제로 보관·전송하도록
    secure 를 끄고 path 를 '/' 로 넓힌다. 운영 값은 .env 가 그대로 쓴다."""
    return load_settings().model_copy(update={
        "database_url": TEST_DB_URL,
        "cookie_secure": False,
        "cookie_path": "/",
    })


@pytest.fixture
def extra_routers():
    """기본 `client` 에 얹을 추가 라우터. 각 테스트 모듈에서 override 한다."""
    return ()


@pytest.fixture
def app(settings, sf, extra_routers):
    application = make_test_app(auth_router, *extra_routers)
    application.dependency_overrides[deps.get_settings] = lambda: settings
    application.dependency_overrides[deps.get_sf] = lambda: sf
    application.dependency_overrides[deps.get_fx_rate] = lambda: TEST_FX_RATE
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def signup(client: TestClient, email: str = TEST_USER["email"],
           password: str = TEST_USER["password"],
           nickname: str = TEST_USER["nickname"]):
    """가입 요청 헬퍼. 두 번째 사용자(권한 테스트용)를 만들 때도 쓴다."""
    return client.post("/api/auth/signup",
                       json={"email": email, "password": password, "nickname": nickname})


@pytest.fixture
def auth_client(app):
    """가입+로그인이 끝난 클라이언트. `.user` 에 {id, email, nickname} 이 들어 있다."""
    with TestClient(app) as c:
        res = signup(c)
        assert res.status_code == 200, res.text
        c.user = res.json()
        yield c
