"""simcore 대시보드 백엔드 — FastAPI 스켈레톤 + 조회 REST 엔드포인트 + WS 실시간 브로드캐스트."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect

from simcore.live.kis_client import KisClient
from simcore.live.ratelimit import RateLimiter
from simcore.live.repository import DbTokenStore, Repository
from simcore.live.settings import load_settings

from dashboard.backend import db, flows, queries, summary
from dashboard.backend.broadcaster import Broadcaster, ConnectionManager
from dashboard.backend.live_prices import current_prices
from dashboard.backend.schemas import (
    CardSummary,
    EquityPoint,
    FlowOut,
    Metrics,
    PositionOut,
    TradeOut,
)

# 카드/집계(list_character_cards)는 daily_bars 최신 종가(또는 avg_price 폴백)만 사용한다.
_FALLBACK_FX_RATE = 1300.0
# WS 백그라운드 폴링 주기(초). 테스트는 poll_once 를 직접 호출하므로 이 값에 의존하지 않는다.
_WS_POLL_INTERVAL_SEC = float(os.environ.get("WS_POLL_INTERVAL_SEC", "5.0"))

manager = ConnectionManager()
broadcaster = Broadcaster(manager, fx_rate=_FALLBACK_FX_RATE)


async def _broadcast_loop(interval: float) -> None:
    """주기적으로 poll_once 를 호출해 변경분만 push하는 백그라운드 루프."""
    while True:
        try:
            await broadcaster.poll_once(db.session_factory())
        except Exception:
            pass  # 폴링 1회 실패는 무시하고 다음 주기에 재시도
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_broadcast_loop(_WS_POLL_INTERVAL_SEC))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="simcore dashboard", lifespan=lifespan)


def get_sf():
    """세션팩토리 FastAPI dependency. 테스트에서 `app.dependency_overrides[get_sf]`로 주입."""
    return db.session_factory()


def get_kis():
    """KIS 클라이언트 FastAPI dependency. 테스트에서 `app.dependency_overrides[get_kis]`로 주입(Fake kis).

    토큰은 `DbTokenStore`(DB 영속)를 통해 캐시를 공유하므로, 매 요청마다 클라이언트를 새로
    만들어도 유효 토큰이 있으면 추가 발급이 일어나지 않는다."""
    settings = load_settings()
    sf = db.session_factory()
    return KisClient(settings, DbTokenStore(sf), RateLimiter(settings.kis_rate_limit_per_sec))


def _symbols_by_market(positions: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for p in positions:
        result.setdefault(p["market"], []).append(p["symbol"])
    return result


def _merge_live_price(pos: dict, live: dict | None) -> dict:
    """포지션에 현재가·평가액(eval_value)·손익%(pnl_pct)·stale 을 병합한다.
    live 정보가 없거나 폴백 가격조차 없으면 avg_price 로 더 폴백하고 stale=True."""
    live = live or {"price": None, "stale": True}
    price = live["price"] if live["price"] is not None else pos["avg_price"]
    stale = live["stale"] or live["price"] is None
    pnl_pct = (price / pos["avg_price"] - 1.0) if pos["avg_price"] else 0.0
    return {
        **pos,
        "current_price": price,
        "eval_value": pos["quantity"] * price,
        "pnl_pct": pnl_pct,
        "stale": stale,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/characters", response_model=list[CardSummary])
def list_character_cards(sf=Depends(get_sf)) -> list[CardSummary]:
    return broadcaster.snapshot(sf)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, sf=Depends(get_sf)) -> None:
    """접속 시 초기 카드 스냅샷 1회 전송 후, 연결을 유지하며 브로드캐스트를 수신한다."""
    await manager.connect(websocket)
    try:
        await websocket.send_json(broadcaster.snapshot_message(sf))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


@app.get("/api/characters/{name}", response_model=Metrics)
def character_detail(name: str, sf=Depends(get_sf)) -> Metrics:
    return summary.detail_metrics(sf, name)


@app.get("/api/characters/{name}/equity", response_model=list[EquityPoint])
def character_equity(name: str, sf=Depends(get_sf)) -> list[EquityPoint]:
    return [EquityPoint(ts=ts, equity_krw=eq) for ts, eq in queries.equity_series(sf, name)]


@app.get("/api/characters/{name}/positions", response_model=list[PositionOut])
def character_positions(name: str, sf=Depends(get_sf), kis=Depends(get_kis)) -> list[PositionOut]:
    positions = queries.positions(sf, name)
    repo = Repository(sf)
    prices = current_prices(kis, _symbols_by_market(positions), repo)
    return [PositionOut(**_merge_live_price(p, prices.get(p["symbol"]))) for p in positions]


@app.get("/api/characters/{name}/trades", response_model=list[TradeOut])
def character_trades(name: str, limit: int = 200, sf=Depends(get_sf)) -> list[TradeOut]:
    return [TradeOut(**t) for t in queries.trades(sf, name, limit=limit)]


@app.get("/api/characters/{name}/flows", response_model=list[FlowOut])
def character_flows(name: str, sf=Depends(get_sf)) -> list[FlowOut]:
    return [FlowOut(**f) for f in queries.flows(sf, name)]


@app.post("/api/characters/{name}/deposit")
def deposit_flow(name: str, body: flows.DepositIn, sf=Depends(get_sf)) -> dict:
    return flows.deposit(sf, name, body)


@app.post("/api/characters/{name}/withdraw")
def withdraw_flow(name: str, body: flows.WithdrawIn, sf=Depends(get_sf)) -> dict:
    return flows.withdraw(sf, name, body)
