"""WS /ws + broadcaster.py 테스트."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from simcore.live import db

from tests.dashboard.conftest import needs_db
from dashboard.backend.app import app, get_sf
from dashboard.backend.broadcaster import Broadcaster, ConnectionManager


def _seed_characters(s, names: list[str]) -> None:
    for name in names:
        s.merge(db.CharacterRow(name=name, base_currency="KRW"))


@needs_db
def test_ws_sends_initial_cards_snapshot_on_connect(sf):
    with sf() as s:
        _seed_characters(s, ["국내형", "해외형", "범용형"])
        s.commit()

    app.dependency_overrides[get_sf] = lambda: sf
    try:
        with TestClient(app).websocket_connect("/ws") as ws:
            msg = ws.receive_json()
    finally:
        app.dependency_overrides.pop(get_sf, None)

    assert msg["type"] == "cards"
    assert {c["name"] for c in msg["data"]} == {"국내형", "해외형", "범용형"}


class _FakeWebSocket:
    """실제 소켓 없이 ConnectionManager/Broadcaster 를 단위 테스트하기 위한 더블."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        if self.fail:
            raise RuntimeError("전송 실패(시뮬레이션)")
        self.sent.append(data)


def test_connection_manager_connect_and_disconnect():
    manager = ConnectionManager()
    ws = _FakeWebSocket()

    asyncio.run(manager.connect(ws))
    assert ws.accepted is True
    assert ws in manager.connections

    manager.disconnect(ws)
    assert ws not in manager.connections
    # 이미 제거된 연결을 다시 disconnect 해도 에러 없이 무시된다.
    manager.disconnect(ws)


def test_connection_manager_broadcast_isolates_failing_connection():
    manager = ConnectionManager()
    good = _FakeWebSocket()
    bad = _FakeWebSocket(fail=True)
    asyncio.run(manager.connect(good))
    asyncio.run(manager.connect(bad))

    message = {"type": "cards", "data": []}
    asyncio.run(manager.broadcast(message))

    # 실패한 연결은 제거되지만, 성공한 연결은 정상 수신하고 그대로 유지된다.
    assert good.sent == [message]
    assert bad not in manager.connections
    assert good in manager.connections


@needs_db
def test_poll_once_broadcasts_only_on_change(sf):
    with sf() as s:
        _seed_characters(s, ["국내형"])
        s.commit()

    manager = ConnectionManager()
    ws = _FakeWebSocket()
    asyncio.run(manager.connect(ws))
    broadcaster = Broadcaster(manager)

    changed = asyncio.run(broadcaster.poll_once(sf))
    assert changed is True
    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "cards"
    assert {c["name"] for c in ws.sent[0]["data"]} == {"국내형"}

    # 데이터 변화 없음 → 추가 push 없음.
    changed_again = asyncio.run(broadcaster.poll_once(sf))
    assert changed_again is False
    assert len(ws.sent) == 1

    # 캐릭터 추가 → 변경 감지되어 다시 push.
    with sf() as s:
        _seed_characters(s, ["해외형"])
        s.commit()

    changed_third = asyncio.run(broadcaster.poll_once(sf))
    assert changed_third is True
    assert len(ws.sent) == 2
    assert {c["name"] for c in ws.sent[1]["data"]} == {"국내형", "해외형"}
