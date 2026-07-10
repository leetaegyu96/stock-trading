"""SQLAlchemy ORM 스키마 (스펙 §5)."""
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import (String, Float, Integer, Boolean, Date, DateTime, ForeignKey,
                        create_engine)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import JSON

# 운영 DB(Postgres)는 네이티브 ARRAY, 테스트용 sqlite(:memory:)는 JSON으로 저장.
# with_variant 는 Postgres 동작을 그대로 유지하면서 sqlite 호환성만 추가한다.
_StringArray = ARRAY(String).with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class CharacterRow(Base):
    __tablename__ = "characters"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    base_currency: Mapped[str] = mapped_column(String)


class CashBalance(Base):
    __tablename__ = "cash_balances"
    character: Mapped[str] = mapped_column(String, primary_key=True)
    currency: Mapped[str] = mapped_column(String, primary_key=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)


class PositionRow(Base):
    __tablename__ = "positions"
    character: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    market: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[float] = mapped_column(Float)
    opened_date: Mapped[date] = mapped_column(Date)
    peak_price: Mapped[float] = mapped_column(Float, default=0.0)
    locked_stop_pct: Mapped[float] = mapped_column(Float, default=0.0)


class PendingOrder(Base):
    __tablename__ = "pending_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)         # BUY/SELL
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    green_count: Mapped[int] = mapped_column(Integer, default=0)
    red_count: Mapped[int] = mapped_column(Integer, default=0)
    green_score: Mapped[int] = mapped_column(Integer, default=0)
    red_score: Mapped[int] = mapped_column(Integer, default=0)
    change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    fired: Mapped[list[str]] = mapped_column(_StringArray, default=list)
    reason: Mapped[str] = mapped_column(String, default="SIGNAL_SELL")
    partial: Mapped[bool] = mapped_column(Boolean, default=False)
    created_date: Mapped[date] = mapped_column(Date)
    # 결정 시점 확정 필드(Task1/2) — 재시작 후에도 보존해야 함. 비어있으면(레거시/미확정)
    # rehydrate 시 None 으로 복원되고, engine._sell/_buy 의 방어적 fallback이 적용된다.
    decision_type: Mapped[str] = mapped_column(String, default="")
    trigger_rule: Mapped[str] = mapped_column(String, default="")


class Cooldown(Base):
    __tablename__ = "cooldowns"
    character: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    market: Mapped[str] = mapped_column(String)
    remaining_days: Mapped[int] = mapped_column(Integer)


class RunState(Base):
    __tablename__ = "run_state"
    market: Mapped[str] = mapped_column(String, primary_key=True)
    last_open_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_fx_rate: Mapped[float] = mapped_column(Float, default=0.0)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)


class KisToken(Base):
    __tablename__ = "kis_token"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    access_token: Mapped[str] = mapped_column(String)
    expires_at: Mapped[float] = mapped_column(Float)


class TradeRow(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    date: Mapped[date] = mapped_column(Date)
    character: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float)
    tax: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String)
    green_count: Mapped[int] = mapped_column(Integer, default=0)
    red_count: Mapped[int] = mapped_column(Integer, default=0)
    green_score: Mapped[int] = mapped_column(Integer, default=0)
    red_score: Mapped[int] = mapped_column(Integer, default=0)
    fired: Mapped[list[str]] = mapped_column(_StringArray, default=list)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    decision_type: Mapped[str] = mapped_column(String, default="BUY")
    trigger_rule: Mapped[str] = mapped_column(String, default="")


class BenchmarkRow(Base):
    """캐릭터별 벤치마크(지수) 수익률 스냅샷. query-path에서 네트워크를 타지 않도록
    seed_from_replay(리플레이 배치)가 미리 계산해 적재한다 — 요청 시점 계산 금지."""
    __tablename__ = "benchmarks"
    character: Mapped[str] = mapped_column(String, primary_key=True)
    benchmark_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_name: Mapped[str] = mapped_column(String, default="")
    ts: Mapped[datetime] = mapped_column(DateTime)


class CapitalFlowRow(Base):
    __tablename__ = "capital_flows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date)
    character: Mapped[str] = mapped_column(String)
    amount_krw: Mapped[float] = mapped_column(Float)
    fx_rate: Mapped[float] = mapped_column(Float)


class FlowRequest(Base):
    __tablename__ = "flow_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character: Mapped[str] = mapped_column(String)
    amount_krw: Mapped[float] = mapped_column(Float)
    liquidate: Mapped[list[str]] = mapped_column(_StringArray, default=list)
    status: Mapped[str] = mapped_column(String, default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EquityPoint(Base):
    __tablename__ = "equity_curve"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    character: Mapped[str] = mapped_column(String)
    equity_krw: Mapped[float] = mapped_column(Float)


class DailyBarRow(Base):
    __tablename__ = "daily_bars"
    market: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)


class UniverseRow(Base):
    __tablename__ = "universe"
    market: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)


def make_engine(url: str):
    return create_engine(url, future=True)


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False, future=True)


def create_all(engine) -> None:
    Base.metadata.create_all(engine)
