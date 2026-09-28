"""v2 ORM — SPEC §2.2 와 1:1 대응. 금액은 전부 BigInteger 최소단위(§2.1)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
                        Index, Integer, Numeric, String, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    accounts: Mapped[list["Account"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    """캐릭터. 회원당 KR/US 각 1개(SPEC §2.2)."""
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_account_user_kind"),
        CheckConstraint("cash_minor >= 0", name="ck_account_cash_nonneg"),
        CheckConstraint("kind IN ('KR','US')", name="ck_account_kind"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(2), nullable=False)        # 'KR' | 'US'
    currency: Mapped[str] = mapped_column(String(3), nullable=False)    # 'KRW' | 'USD'
    cash_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    seed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 수익률 분모
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    user: Mapped[User] = relationship(back_populates="accounts")
    positions: Mapped[list["Position"]] = relationship(
        back_populates="account", cascade="all, delete-orphan")


class Position(Base):
    """같은 종목은 한 행으로 합산(평단 가중평균). 수량 0 이 되면 행을 지운다."""
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", name="uq_position_account_symbol"),
        CheckConstraint("quantity > 0", name="ck_position_qty_positive"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # 매수 수수료를 포함한 평단 — 손익이 실제 투입액 기준이 되게 한다(SPEC §5.1).
    avg_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    account: Mapped[Account] = relationship(back_populates="positions")
    sell_rule: Mapped["SellRule | None"] = relationship(
        back_populates="position", cascade="all, delete-orphan", uselist=False)


class SellRule(Base):
    """매도벽 — 평단 대비 −n%/+m%. 포지션당 최대 1개(SPEC §6.2)."""
    __tablename__ = "sell_rules"
    __table_args__ = (
        CheckConstraint("stop_loss_pct IS NULL OR (stop_loss_pct > -100 AND stop_loss_pct < 0)",
                        name="ck_rule_stop_range"),
        CheckConstraint("take_profit_pct IS NULL OR "
                        "(take_profit_pct > 0 AND take_profit_pct <= 900)",
                        name="ck_rule_target_range"),
        CheckConstraint("stop_loss_pct IS NOT NULL OR take_profit_pct IS NOT NULL",
                        name="ck_rule_not_empty"),
        CheckConstraint("quantity > 0", name="ck_rule_qty_positive"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    position_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False, unique=True)
    stop_loss_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    take_profit_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    position: Mapped[Position] = relationship(back_populates="sell_rule")


class Trade(Base):
    """체결 원장. append-only — 수정·삭제하지 않는다(SPEC §2.2 불변식 4)."""
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("side IN ('BUY','SELL')", name="ck_trade_side"),
        CheckConstraint("quantity > 0", name="ck_trade_qty_positive"),
        Index("ix_trade_account_ts", "account_id", "executed_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)   # 현금 증감(부호 포함)
    realized_pnl_minor: Mapped[int | None] = mapped_column(BigInteger)   # SELL 만
    # 'MANUAL' | 'AUTO_STOP_LOSS' | 'AUTO_TAKE_PROFIT'
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    sell_rule_id: Mapped[int | None] = mapped_column(BigInteger)
    # 시세 조회 실패로 마지막 종가를 썼는지 — 사후 감사를 위해 체결에 남긴다.
    stale_price: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "ts", name="uq_equity_account_ts"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    equity_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EventLog(Base):
    """'모든 건 기록을 남긴다' — 매매뿐 아니라 규칙 설정·발동·스킵까지."""
    __tablename__ = "event_log"
    __table_args__ = (Index("ix_event_user_ts", "user_id", "ts"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    account_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class KisToken(Base):
    """v1 과 분리된 v2 전용 토큰 저장소(SPEC §4.1)."""
    __tablename__ = "kis_token"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    access_token: Mapped[str] = mapped_column(String(1024), nullable=False)
    expires_at: Mapped[float] = mapped_column(Numeric(20, 3), nullable=False)


class LoginAttempt(Base):
    """로그인 실패 레이트 리밋(SPEC §3)."""
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_key_ts", "key", "ts"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False)   # email|ip
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
