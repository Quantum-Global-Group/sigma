from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class BacktestRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=20)
    start_date: str = Field(..., examples=["2024-01-01"])
    end_date: str = Field(..., examples=["2025-01-01"])
    initial_capital: float = Field(100_000.0, gt=0)
    rebalance_freq: Literal["daily", "weekly", "monthly"] = "monthly"

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip().upper() for t in v if t.strip()]
        if not cleaned:
            raise ValueError("at least one ticker is required")
        return cleaned


class EquityPoint(BaseModel):
    date: str
    value: float


class TradeEntry(BaseModel):
    date: str
    ticker: str
    action: Literal["BUY", "SELL", "REBALANCE"]
    weight: float


class BacktestResult(BaseModel):
    tickers: list[str]
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    equity_curve: list[EquityPoint]
    trade_log: list[TradeEntry]
    timestamp: datetime
