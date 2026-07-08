"""대시보드 백엔드 DB 세션 팩토리 — simcore.live.db 재사용."""
from __future__ import annotations

from simcore.live import db as livedb
from simcore.live.settings import load_settings


def session_factory():
    s = load_settings()
    return livedb.make_session_factory(livedb.make_engine(s.database_url))
