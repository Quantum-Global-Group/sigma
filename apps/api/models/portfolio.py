from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PortfolioRequest(BaseModel):
    holdings: dict[str, float] = Field(..., description='Dollar value per ticker, e.g. {"AAPL": 1000.0, "MSFT": 2500.0}')
    method: Literal["mvo", "quantum_qaoa", "equal_weight"] = "mvo"
    risk_aversion: float = Field(1.0, ge=0.0, le=10.0)

    @field_validator("holdings")
    @classmethod
    def _validate_holdings(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError("holdings must contain at least one ticker")
        if any(amount < 0 for amount in v.values()):
            raise ValueError("holdings amounts must be non-negative")
        return v


class TradeRecommendation(BaseModel):
    ticker: str
    action: Literal["BUY", "SELL"]
    amount: float


class RebalanceResponse(BaseModel):
    method: str
    fallback: bool
    target_allocation: dict[str, float]
    recommended_trades: list[TradeRecommendation]
    sharpe_ratio: float | None
    timestamp: datetime
