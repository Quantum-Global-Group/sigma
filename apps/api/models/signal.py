from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

AssetClass = Literal["equity", "crypto"]
Timeframe = Literal["daily", "4h", "hourly", "5m", "1m"]


class SignalRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32, examples=["AAPL", "BTC-USD"])
    timeframe: Timeframe = "daily"
    asset_class: AssetClass = "equity"


class SignalResponse(BaseModel):
    ticker: str
    timeframe: str
    asset_class: AssetClass = "equity"
    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    predicted_return: float
    model_version: str
    cached: bool
    timestamp: datetime
    component_weights: Optional[dict] = None
