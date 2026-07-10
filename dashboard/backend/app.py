"""simcore 대시보드 백엔드 — FastAPI 스켈레톤 + 조회 REST 엔드포인트 + WS 실시간 브로드캐스트."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse

from simcore.config import Config
from simcore.engine import DEFAULT_CHARACTERS
from simcore.live.kis_client import KisClient
from simcore.live.ratelimit import RateLimiter
from simcore.live.repository import DbTokenStore, Repository
from simcore.live.settings import load_settings
from simcore.models import DecisionType
from simcore.names import display_name
from simcore import signal_display as sd

from dashboard.backend import db, flows, queries, summary
from dashboard.backend.broadcaster import Broadcaster, ConnectionManager
from dashboard.backend.constants import FALLBACK_FX_RATE
from dashboard.backend.live_prices import current_prices
from dashboard.backend.schemas import (
    CardSummary,
    DashboardOut,
    EquityPoint,
    FlowOut,
    MarketStatusOut,
    Metrics,
    PositionOut,
    TradeOut,
)

# 카드/집계(list_character_cards)는 daily_bars 최신 종가(또는 avg_price 폴백)만 사용한다.
# dashboard.backend.constants.FALLBACK_FX_RATE 와 동일해야 한다(seed_from_replay 도 공유).
_FALLBACK_FX_RATE = FALLBACK_FX_RATE
# WS 백그라운드 폴링 주기(초). 테스트는 poll_once 를 직접 호출하므로 이 값에 의존하지 않는다.
_WS_POLL_INTERVAL_SEC = float(os.environ.get("WS_POLL_INTERVAL_SEC", "5.0"))

manager = ConnectionManager()
broadcaster = Broadcaster(manager, fx_rate=_FALLBACK_FX_RATE)
_SCORES = Config().scores


async def _broadcast_loop(interval: float) -> None:
    """주기적으로 poll_once 를 호출해 변경분만 push하는 백그라운드 루프."""
    while True:
        try:
            await broadcaster.poll_once(db.session_factory())
        except Exception:
            logging.getLogger(__name__).exception("broadcast poll failed")
            # 폴링 1회 실패는 무시하고 다음 주기에 재시도
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


def _safe_decision_type(raw) -> DecisionType | None:
    """DB의 decision_type이 미확정/레거시/손상값이어도 500을 내지 않고 None으로
    폴백한다 — summarize()는 decision_type=None이면 레거시(score-only) 경로로 요약한다.
    임의의 결정을 지어내지 않는다."""
    if not raw:
        return None
    try:
        return DecisionType(raw)
    except (ValueError, TypeError):
        return None


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


@app.get("/api/status", response_model=list[MarketStatusOut])
def market_status(sf=Depends(get_sf)) -> list[MarketStatusOut]:
    """시장별 데이터 기준(run_state) — as-of 표시용(P0)."""
    return [MarketStatusOut(**row) for row in queries.market_status(sf)]


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(sf=Depends(get_sf)) -> DashboardOut:
    """일일 현황판: 시장별 movers·캐릭터별 요약·통합 최근 체결."""
    movers = queries.universe_movers(sf)
    for market in movers.values():
        for lst in market.values():
            for m in lst:
                m["name"] = display_name(m["symbol"], m["market"])
    last_prices_by_char = {}
    for name in [s.name for s in DEFAULT_CHARACTERS]:
        last_prices_by_char[name] = queries.last_prices(sf, queries.positions(sf, name))
    chars = summary.character_portfolios(sf, _FALLBACK_FX_RATE, last_prices_by_char)
    rts = queries.recent_trades(sf)
    for t in rts:
        t["name"] = display_name(t["symbol"], t["market"])
    return DashboardOut(movers=movers, characters=chars, recent_trades=rts)


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
    out = []
    for t in queries.trades(sf, name, limit=limit):
        score = t["green_score"] if t["side"] == "BUY" else t["red_score"]
        out.append(TradeOut(
            **t,
            signal_summary=sd.summarize(
                t["fired"], score, t["side"], _SCORES,
                decision_type=_safe_decision_type(t["decision_type"]),
                trigger_rule=t["trigger_rule"],
            ),
            signal_detail=sd.detail(t["fired"], _SCORES),
        ))
    return out


@app.get("/api/characters/{name}/flows", response_model=list[FlowOut])
def character_flows(name: str, sf=Depends(get_sf)) -> list[FlowOut]:
    return [FlowOut(**f) for f in queries.flows(sf, name)]


@app.post("/api/characters/{name}/deposit")
def deposit_flow(name: str, body: flows.DepositIn, sf=Depends(get_sf)) -> dict:
    return flows.deposit(sf, name, body)


@app.post("/api/characters/{name}/withdraw")
def withdraw_flow(name: str, body: flows.WithdrawIn, sf=Depends(get_sf)) -> dict:
    return flows.withdraw(sf, name, body)


# --- React 정적 빌드 서빙 + SPA 폴백 -----------------------------------------
# dashboard/frontend/dist 가 존재하면(빌드됨) 정적 자산 + index.html 을 서빙하고,
# API/WS 가 아닌 알 수 없는 경로는 index.html 로 폴백해 클라이언트 라우팅을 지원한다.
# dist 가 없으면(아직 빌드 전) 안내 메시지를 200 으로 반환한다.
# 존재 여부는 요청마다 확인한다(테스트가 dist 를 동적으로 생성/삭제하고, 빌드 후
# 서버 재기동 없이도 즉시 반영되어야 하므로 앱 부팅 시점에 고정하지 않는다).
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_FRONTEND_NOT_BUILT_MSG = (
    "프론트엔드가 아직 빌드되지 않았습니다. dashboard/frontend에서 npm run build 하세요."
)


def _serve_frontend(rel_path: str):
    """dist/{rel_path} 정적 파일이 있으면 그것을, 없으면 index.html(SPA 폴백)을 반환.
    dist 자체가 없으면 안내 메시지를 200 으로 반환한다."""
    dist_root = _FRONTEND_DIST.resolve()
    if not dist_root.is_dir():
        return PlainTextResponse(_FRONTEND_NOT_BUILT_MSG, status_code=200)

    index_file = dist_root / "index.html"
    if rel_path:
        candidate = (dist_root / rel_path).resolve()
        # path traversal 방지: dist 밖을 벗어나는 경로는 무시하고 index.html 로 폴백.
        if candidate.is_file() and dist_root in candidate.parents:
            return FileResponse(candidate)

    if index_file.is_file():
        return FileResponse(index_file)
    return PlainTextResponse(_FRONTEND_NOT_BUILT_MSG, status_code=200)


@app.get("/")
async def frontend_root():
    return _serve_frontend("")


@app.get("/{full_path:path}")
async def frontend_spa_fallback(full_path: str):
    # /api/* 와 /ws 는 위에서 이미 라우트가 정의되어 우선 매칭되므로, 여기 도달했다는
    # 것은 정의되지 않은 api/ws 경로라는 뜻 → SPA 로 폴백하지 않고 404 를 유지한다.
    if full_path == "ws" or full_path.startswith("ws/") or full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    return _serve_frontend(full_path)
