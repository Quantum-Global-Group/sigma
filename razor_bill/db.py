from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


class Base(DeclarativeBase):
    pass


# Database engine and session
engine = create_async_engine(settings.db_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


def SessionLocal() -> AsyncSession:
    return async_session()


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    t: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    o: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)
    l: Mapped[float] = mapped_column(Float, nullable=False)
    c: Mapped[float] = mapped_column(Float, nullable=False)
    v: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="coinbase")


class FeatureRow(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    t: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    rsi: Mapped[float] = mapped_column(Float, nullable=False)
    atr: Mapped[float] = mapped_column(Float, nullable=False)
    ema_fast: Mapped[float] = mapped_column(Float, nullable=False)
    ema_slow: Mapped[float] = mapped_column(Float, nullable=False)
    mom_1: Mapped[float] = mapped_column(Float, nullable=False)
    mom_3: Mapped[float] = mapped_column(Float, nullable=False)
    mom_12: Mapped[float] = mapped_column(Float, nullable=False)
    vol_realized: Mapped[float] = mapped_column(Float, nullable=False)
    rolling_vol_50: Mapped[float] = mapped_column(Float, nullable=False)
    v_spike: Mapped[float] = mapped_column(Float, nullable=False)
    breakout_20: Mapped[float] = mapped_column(Float, nullable=False)
    regime: Mapped[str] = mapped_column(String(8), default="neutral")


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    t: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    signal: Mapped[float] = mapped_column(Float, nullable=False)
    weight_model: Mapped[float] = mapped_column(Float, nullable=False)
    weight_sent: Mapped[float] = mapped_column(Float, nullable=False)
    weight_regime: Mapped[float] = mapped_column(Float, nullable=False)
    conf: Mapped[float] = mapped_column(Float, nullable=False)
    risk_var_95: Mapped[float] = mapped_column(Float, nullable=False)
    atr: Mapped[float] = mapped_column(Float, nullable=False)


class PositionRow(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    entry_px: Mapped[float] = mapped_column(Float, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_px: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    t: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    px: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False)
    slip: Mapped[float] = mapped_column(Float, nullable=False)


class ExitStateRow(Base):
    __tablename__ = "exit_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    took_partial: Mapped[int] = mapped_column(Integer, default=0)
    breakeven_px: Mapped[float] = mapped_column(Float, default=0.0)
    tight_trailing: Mapped[float] = mapped_column(Float, default=0.0)