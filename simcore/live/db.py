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


class SignalStatusRow(Base):
    """마감 시점 후보·보유 상태 스냅샷(감사 Phase B). 전량 교체 방식으로 최신 마감분만
    유지한다 — 요청 경로는 이 테이블만 읽고 evaluate_frame 등 무거운 계산을 하지 않는다."""
    __tablename__ = "signal_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date)
    character: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String)
    # 라이브 on_close 는 시장 하나씩 마감하므로, replace 시 그 시장 분만 지우고 나머지
    # 시장은 보존해야 한다(전량교체 시맨틱을 market 단위로 좁히기 위한 컬럼).
    market: Mapped[str] = mapped_column(String, default="")
    kind: Mapped[str] = mapped_column(String)          # "후보" | "보유"
    green_score: Mapped[int] = mapped_column(Integer, default=0)
    red_score: Mapped[int] = mapped_column(Integer, default=0)
    buy_gate: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="")
    block_reason: Mapped[str] = mapped_column(String, default="")
    stop_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)


class IntradayScanRow(Base):
    """장중 스캔 하트비트 — 시장별 최신 1행. 매 스캔(0건 매매·전건 실패 포함)마다 upsert 되어
    '언제/몇 종목/게이트 통과 몇/매수·매도 몇'을 남긴다. 요청 경로는 이 행만 읽는다(관찰 전용)."""
    __tablename__ = "intraday_scan"
    market: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime)      # 마지막 스캔 시각(시장 tz)
    universe_size: Mapped[int] = mapped_column(Integer, default=0)  # 시도 종목 수
    evaluated: Mapped[int] = mapped_column(Integer, default=0)      # 신호계산 성공 종목 수
    failed: Mapped[int] = mapped_column(Integer, default=0)         # 조회/계산 실패 스킵 수
    gate_pass: Mapped[int] = mapped_column(Integer, default=0)      # 매수게이트 통과 종목 수
    buys: Mapped[int] = mapped_column(Integer, default=0)           # 이번 스캔 매수 건수
    sells: Mapped[int] = mapped_column(Integer, default=0)          # 이번 스캔 매도 건수
    scan_minutes: Mapped[int] = mapped_column(Integer, default=0)   # 스캔 주기(분)


class IntradayGuardRow(Base):
    """장중 가드(휩쏘 캡·킬스위치) 영속 스냅샷(#26). CharacterState 의
    intraday_day/intraday_day_start_equity/intraday_buys/intraday_sells/
    intraday_last_sell_ts 를 캐릭터별 1행으로 저장한다 — 재시작(rehydrate) 시
    이 값이 복원되지 않으면 _intraday_roll_day 가 재시작 시점 equity 로
    day_start_equity 를 재기준해 킬스위치·매수/매도 캡이 조용히 리셋된다."""
    __tablename__ = "intraday_guards"
    character: Mapped[str] = mapped_column(String, primary_key=True)
    intraday_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    day_start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    buys_json: Mapped[str] = mapped_column(String, default="{}")
    sells_json: Mapped[str] = mapped_column(String, default="{}")
    last_sell_ts_json: Mapped[str] = mapped_column(String, default="{}")


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
