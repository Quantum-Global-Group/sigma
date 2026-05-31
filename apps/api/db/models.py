import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from db.connection import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clerk_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    default_asset_class: Mapped[str | None] = mapped_column(String(16), default="equity")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="api_keys")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"))
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(20))
    response_ms: Mapped[int | None] = mapped_column(Integer)
    status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text)
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SignalHistory(Base):
    __tablename__ = "signal_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, default="daily")
    asset_class: Mapped[str | None] = mapped_column(String(16))
    signal: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    predicted_return: Mapped[float | None] = mapped_column(Numeric(8, 6))
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    features: Mapped[dict | None] = mapped_column(JSONB)
    component_weights: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    # Outcome labels (migration 009) — backfilled by ml/labeling.py once the
    # forward window has elapsed; nullable until then.
    realized_return: Mapped[float | None] = mapped_column(Numeric(12, 6))
    outcome: Mapped[str | None] = mapped_column(String(8))          # win | loss | flat
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditRecord(Base):
    """Durable decision provenance (migration 009). Mirrors the in-memory
    risk/audit_log.py::AuditRecord; persisted per options tick by db/audit_store.py."""

    __tablename__ = "audit_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False, default="option")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy: Mapped[str | None] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    data: Mapped[dict | None] = mapped_column(JSONB)
    features: Mapped[dict | None] = mapped_column(JSONB)
    signal: Mapped[dict | None] = mapped_column(JSONB)
    risk: Mapped[dict | None] = mapped_column(JSONB)
    gates: Mapped[list | None] = mapped_column(JSONB)
    order_info: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)


class Candle(Base):
    __tablename__ = "candles"

    asset_class: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(10), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(28, 8), nullable=False)
    source: Mapped[str | None] = mapped_column(String(32))


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(28, 8), nullable=False)
    entry_px: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    current_px: Mapped[float | None] = mapped_column(Numeric(20, 8))
    unrealized_pnl: Mapped[float | None] = mapped_column(Numeric(20, 8))
    realized_pnl: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Option-specific fields (migration 008); NULL for equity/crypto rows.
    underlying: Mapped[str | None] = mapped_column(String(20))
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[float | None] = mapped_column(Numeric(12, 4))
    right: Mapped[str | None] = mapped_column(String(4))
    multiplier: Mapped[int | None] = mapped_column(SmallInteger)
    meta: Mapped[dict | None] = mapped_column(JSONB)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(28, 8), nullable=False)
    px: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    fee: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    slippage_bps: Mapped[float | None] = mapped_column(Numeric(10, 4))
    executor: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))
    client_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="market")
    time_in_force: Mapped[str] = mapped_column(String(8), nullable=False, default="day")
    limit_px: Mapped[float | None] = mapped_column(Numeric(20, 8))
    stop_px: Mapped[float | None] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="filled")
    raw: Mapped[dict | None] = mapped_column(JSONB)
    # Option-specific fields (migration 008); NULL for equity/crypto rows.
    underlying: Mapped[str | None] = mapped_column(String(20))
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[float | None] = mapped_column(Numeric(12, 4))
    right: Mapped[str | None] = mapped_column(String(4))
    multiplier: Mapped[int | None] = mapped_column(SmallInteger)
    meta: Mapped[dict | None] = mapped_column(JSONB)


class ExitState(Base):
    __tablename__ = "exit_state"

    position_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True)
    partial_tp_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    breakeven_px: Mapped[float | None] = mapped_column(Numeric(20, 8))
    trailing_stop_px: Mapped[float | None] = mapped_column(Numeric(20, 8))
    high_water_px: Mapped[float | None] = mapped_column(Numeric(20, 8))
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    holdings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_value: Mapped[float | None] = mapped_column(Numeric(15, 2))
    optimization_method: Mapped[str | None] = mapped_column(String(50))
    target_allocation: Mapped[dict | None] = mapped_column(JSONB)
    recommended_trades: Mapped[list | None] = mapped_column(JSONB)
    sharpe_ratio: Mapped[float | None] = mapped_column(Numeric(8, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, server_default=func.now())
