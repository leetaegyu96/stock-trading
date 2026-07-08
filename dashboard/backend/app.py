"""simcore 대시보드 백엔드 — FastAPI 스켈레톤."""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="simcore dashboard")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
