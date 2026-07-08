import os

import pytest

from simcore.live.db import Base, create_all, make_engine, make_session_factory

TEST_DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL 미설정")


@pytest.fixture
def session():
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL 미설정")
    engine = make_engine(TEST_DB)
    Base.metadata.drop_all(engine)
    create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s
    Base.metadata.drop_all(engine)


@pytest.fixture
def sf():
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL 미설정")
    engine = make_engine(TEST_DB)
    Base.metadata.drop_all(engine)
    create_all(engine)
    yield make_session_factory(engine)
    Base.metadata.drop_all(engine)
