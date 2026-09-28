"""v2 앱 조립 — FastAPI + 매도벽 감시 스케줄러 + React 정적 서빙.

nginx 가 `/stock-v2/` 프리픽스를 벗겨 넘기므로 앱은 루트 기준으로 동작한다(v1과 동일).
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse

from v2.backend import market as market_mod
from v2.backend import scheduler as sched_mod
from v2.backend.db import create_all, make_engine, make_session_factory
from v2.backend.deps import install_error_handler
from v2.backend.routers import accounts, auth, market as market_router, orders
from v2.backend.settings import load_settings

log = logging.getLogger("v2")

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_NOT_BUILT = ("프론트엔드가 아직 빌드되지 않았습니다. "
              "v2/frontend 에서 VITE_BASE_PATH=/stock-v2/ npm run build 하세요.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    engine = make_engine(settings.database_url)
    create_all(engine)
    sf = make_session_factory(engine)
    # KIS 클라이언트·캐시를 프로세스 1회 초기화. 라우터는 모듈 레벨 함수를 그대로 쓴다.
    market_mod.init_from_settings(sf, settings)
    _warm_market_cache()
    scheduler = sched_mod.build_scheduler(sf, market_mod, settings)
    if scheduler.get_jobs():
        scheduler.start()
        log.info("[v2] 매도벽 감시 시작 — 잡 %d개", len(scheduler.get_jobs()))
    else:
        log.info("[v2] 매도벽 감시 비활성(V2_SELLWALL_ENABLED=false)")
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def _warm_market_cache() -> None:
    """종목 목록을 백그라운드로 미리 채운다.

    콜드 캐시에서는 종목 30개 × (현재가+일봉)을 받아야 해서 첫 요청이 몇 초 걸린다.
    그 몇 초를 **첫 방문자가 대신 기다리는 것**이 이 앱에서 제일 흔한 나쁜 첫인상이라,
    기동 직후 미리 받아 둔다. 실패해도 그냥 넘어간다 — 요청 시점에 다시 시도한다.
    """
    def run() -> None:
        for kind in ("KR", "US"):
            try:
                market_mod.list_stocks(kind)
            except Exception as exc:
                log.warning("[v2] %s 종목 예열 실패(요청 시 재시도): %s", kind, exc)

    threading.Thread(target=run, name="market-warmup", daemon=True).start()


app = FastAPI(title="stock-trading v2", lifespan=lifespan)
install_error_handler(app)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(market_router.router)
app.include_router(orders.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": "v2"}


def _serve_frontend(rel_path: str):
    """dist/{rel}이 있으면 그 파일, 없으면 index.html(SPA 폴백).

    dist 존재 여부를 요청마다 확인한다 — 빌드 후 서버 재기동 없이 반영되어야 한다(v1과 동일).
    """
    dist = _FRONTEND_DIST.resolve()
    if not dist.is_dir():
        return PlainTextResponse(_NOT_BUILT)
    if rel_path:
        target = (dist / rel_path).resolve()
        # 경로 이탈(../) 차단 — dist 밖 파일이 새어나가면 안 된다.
        if target.is_file() and target.is_relative_to(dist):
            return FileResponse(target)
    index = dist / "index.html"
    return FileResponse(index) if index.is_file() else PlainTextResponse(_NOT_BUILT)


@app.get("/")
def index():
    return _serve_frontend("")


@app.get("/{full_path:path}")
def spa(full_path: str):
    return _serve_frontend(full_path)
