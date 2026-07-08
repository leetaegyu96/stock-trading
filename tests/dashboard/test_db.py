"""dashboard.backend.db.session_factory 싱글턴 검증 — DB 연결 불필요."""
from __future__ import annotations

from dashboard.backend.db import session_factory


def test_session_factory_is_singleton():
    """매 호출마다 새 엔진/커넥션풀을 만들지 않고 동일 객체를 재사용해야 한다."""
    assert session_factory() is session_factory()
