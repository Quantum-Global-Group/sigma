from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

Side = Literal["buy", "sell"]


@dataclass
class OrderRequest:
    asset_class: str
    symbol: str
    side: Side
    qty: float                    # base-asset quantity
    notional: Optional[float] = None  # quote-asset notional (for market buys)
    limit_px: Optional[float] = None  # None = market


@dataclass
class Fill:
    asset_class: str
    symbol: str
    ts: datetime
    side: Side
    qty: float
    px: float
    fee: float
    slippage_bps: Optional[float]
    executor: str
    external_id: Optional[str] = None
    raw: Optional[dict] = None


class Executor(ABC):
    name: str = ""

    @abstractmethod
    async def place(self, order: OrderRequest) -> Fill:
        """Submit an order and return the resulting fill."""
