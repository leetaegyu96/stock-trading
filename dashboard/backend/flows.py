"""입출금 예약 — 요청 검증 + `Repository.enqueue_flow` 위임.

입금은 양수, 출금은 음수 금액으로 `flow_requests`에 pending 상태로 적재한다.
실제 반영(포지션 정리·현금 갱신)은 별도 워커(라이브 루프)의 몫이며, 이 모듈은
요청을 큐에 넣는 역할만 한다.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from simcore.engine import DEFAULT_CHARACTERS
from simcore.live.repository import Repository

_KNOWN_CHARACTERS = {c.name for c in DEFAULT_CHARACTERS}


class DepositIn(BaseModel):
    amount_krw: float


class WithdrawIn(BaseModel):
    amount_krw: float
    liquidate: list[str] = Field(default_factory=list)


def _validate(name: str, amount_krw: float) -> None:
    if name not in _KNOWN_CHARACTERS:
        raise HTTPException(status_code=404, detail=f"알 수 없는 캐릭터: {name}")
    if amount_krw <= 0:
        raise HTTPException(status_code=400, detail="amount_krw는 0보다 커야 합니다")


def deposit(sf, name: str, body: DepositIn) -> dict:
    _validate(name, body.amount_krw)
    request_id = Repository(sf).enqueue_flow(name, body.amount_krw)
    return {"queued": True, "request_id": request_id}


def withdraw(sf, name: str, body: WithdrawIn) -> dict:
    _validate(name, body.amount_krw)
    request_id = Repository(sf).enqueue_flow(name, -body.amount_krw, liquidate=body.liquidate)
    return {"queued": True, "request_id": request_id}
