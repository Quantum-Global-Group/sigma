from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SignalRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=20, examples=["AAPL"])
    timeframe: Literal["daily", "4h", "hourly"] = "daily"


class SignalResponse(BaseModel):
    ticker: str
    timeframe: str
    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    predicted_return: float
    model_version: str
    cached: bool
    timestamp: datetime
