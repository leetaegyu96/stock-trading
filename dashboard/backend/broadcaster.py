"""WebSocket 실시간 브로드캐스트 — 카드 스냅샷 폴링 후 변경분만 push.

`ConnectionManager` 는 연결된 WebSocket 을 추적하고, 전송 실패한 연결만 개별
제거한다(다른 연결은 영향받지 않음). `Broadcaster` 는 `/api/characters` 와
동일한 카드 스냅샷(summary.card_summary 재사용)을 만들고, 직전 스냅샷과
비교해 변경이 있을 때만 브로드캐스트한다. 주기적 폴링 루프는 app 쪽
startup 백그라운드 태스크가 담당하며, 테스트는 `poll_once`를 직접 호출한다.
"""
from __future__ import annotations

from fastapi import WebSocket

from dashboard.backend import queries, summary
from dashboard.backend.constants import FALLBACK_FX_RATE
from dashboard.backend.schemas import CardSummary

# dashboard.backend.constants.FALLBACK_FX_RATE 와 동일해야 한다(seed_from_replay 도 공유).
_FALLBACK_FX_RATE = FALLBACK_FX_RATE


class ConnectionManager:
    """연결된 WebSocket 목록 관리."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        """모든 연결에 메시지를 보낸다. 개별 전송 실패는 그 연결만 제거하고 나머지엔 계속 보낸다."""
        dead: list[WebSocket] = []
        for websocket in list(self._connections):
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)

    @property
    def connections(self) -> list[WebSocket]:
        return list(self._connections)


def _serialize(cards: list[CardSummary]) -> list[dict]:
    return [c.model_dump(mode="json") for c in cards]


class Broadcaster:
    """카드 스냅샷 계산(=/api/characters 와 동일) + 변경분만 push."""

    def __init__(self, manager: ConnectionManager, fx_rate: float = _FALLBACK_FX_RATE) -> None:
        self._manager = manager
        self._fx_rate = fx_rate
        self._last_payload: list[dict] | None = None

    def snapshot(self, sf) -> list[CardSummary]:
        """`/api/characters` 와 동일한 카드 목록을 계산한다."""
        cards = []
        for c in queries.list_characters(sf):
            positions = queries.positions(sf, c["name"])
            prices = queries.last_prices(sf, positions)
            cards.append(
                summary.card_summary(sf, c["name"], fx_rate=self._fx_rate, last_prices=prices)
            )
        return cards

    def snapshot_message(self, sf) -> dict:
        """현재 스냅샷을 WS 메시지 포맷으로 변환(캐시에 반영하지 않음 — 초기 접속 시 1회 전송용)."""
        return {"type": "cards", "data": _serialize(self.snapshot(sf))}

    async def poll_once(self, sf) -> bool:
        """현재 스냅샷을 직전 캐시와 비교해 변경 시에만 브로드캐스트한다. 변경 여부를 반환한다."""
        message = self.snapshot_message(sf)
        if message["data"] == self._last_payload:
            return False
        self._last_payload = message["data"]
        await self._manager.broadcast(message)
        return True
