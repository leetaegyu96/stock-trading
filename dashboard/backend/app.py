"""simcore 대시보드 백엔드 — FastAPI 스켈레톤 + 조회 REST 엔드포인트."""
from __future__ import annotations

from fastapi import Depends, FastAPI

from simcore.live.repository import Repository

from dashboard.backend import db, queries, summary
from dashboard.backend.schemas import (
    CardSummary,
    EquityPoint,
    FlowOut,
    Metrics,
    PositionOut,
    TradeOut,
)

app = FastAPI(title="simcore dashboard")

# 라이브 KIS 현재가는 Task 5 에서 병합. 이 태스크는 daily_bars 최신 종가(또는 avg_price 폴백)만 사용.
_FALLBACK_FX_RATE = 1300.0


def get_sf():
    """세션팩토리 FastAPI dependency. 테스트에서 `app.dependency_overrides[get_sf]`로 주입."""
    return db.session_factory()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _last_prices(sf, positions: list[dict]) -> dict[str, float]:
    """보유 종목의 daily_bars 최신 종가. 없으면 비워두어 summary 쪽 avg_price 폴백에 맡긴다."""
    repo = Repository(sf)
    prices: dict[str, float] = {}
    for pos in positions:
        bars = repo.load_daily_bars(pos["market"], pos["symbol"])
        if not bars.empty:
            prices[pos["symbol"]] = float(bars["close"].iloc[-1])
    return prices


@app.get("/api/characters", response_model=list[CardSummary])
def list_character_cards(sf=Depends(get_sf)) -> list[CardSummary]:
    cards = []
    for c in queries.list_characters(sf):
        positions = queries.positions(sf, c["name"])
        last_prices = _last_prices(sf, positions)
        cards.append(
            summary.card_summary(sf, c["name"], fx_rate=_FALLBACK_FX_RATE, last_prices=last_prices)
        )
    return cards


@app.get("/api/characters/{name}", response_model=Metrics)
def character_detail(name: str, sf=Depends(get_sf)) -> Metrics:
    return summary.detail_metrics(sf, name)


@app.get("/api/characters/{name}/equity", response_model=list[EquityPoint])
def character_equity(name: str, sf=Depends(get_sf)) -> list[EquityPoint]:
    return [EquityPoint(ts=ts, equity_krw=eq) for ts, eq in queries.equity_series(sf, name)]


@app.get("/api/characters/{name}/positions", response_model=list[PositionOut])
def character_positions(name: str, sf=Depends(get_sf)) -> list[PositionOut]:
    return [PositionOut(**p) for p in queries.positions(sf, name)]


@app.get("/api/characters/{name}/trades", response_model=list[TradeOut])
def character_trades(name: str, limit: int = 200, sf=Depends(get_sf)) -> list[TradeOut]:
    return [TradeOut(**t) for t in queries.trades(sf, name, limit=limit)]


@app.get("/api/characters/{name}/flows", response_model=list[FlowOut])
def character_flows(name: str, sf=Depends(get_sf)) -> list[FlowOut]:
    return [FlowOut(**f) for f in queries.flows(sf, name)]
