"""대시보드 백엔드 DB 세션 팩토리 — simcore.live.db 재사용."""
from __future__ import annotations

from functools import lru_cache

from simcore.live import db as livedb
from simcore.live.settings import load_settings


@lru_cache(maxsize=1)
def session_factory():
    """엔진 + 세션팩토리를 프로세스당 1회만 생성해 재사용한다.

    이전에는 호출될 때마다 새 엔진(및 커넥션 풀)을 만들어 절대 dispose 되지 않았다.
    HTTP 요청마다(get_sf/get_kis), WS 브로드캐스트 루프에서 5초마다 호출되므로
    장시간 구동 시 커넥션 누수/풀 고갈로 이어졌다. lru_cache 로 동일 sessionmaker
    객체를 반환하도록 싱글턴화한다."""
    s = load_settings()
    return livedb.make_session_factory(livedb.make_engine(s.database_url))
