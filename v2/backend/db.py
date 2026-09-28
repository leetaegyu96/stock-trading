"""엔진·세션 팩토리. v1 의 simcore.live.db 와 같은 관용구."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from v2.backend.models import Base


def make_engine(url: str):
    # pool_pre_ping: 유휴 커넥션이 끊긴 뒤 첫 쿼리가 죽는 것을 막는다(데몬이 장시간 뜬다).
    return create_engine(url, pool_pre_ping=True, future=True)


def create_all(engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def transaction(sf: sessionmaker[Session]):
    """커밋/롤백을 보장하는 세션 스코프."""
    s = sf()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
