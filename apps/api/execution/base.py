"""Execution domain model + Executor interface.

Upgraded from the original OrderRequest/Fill pair to a broker-agnostic
OrderIntent → ExecutionReport model (ported from tradeFlux
`core/orders.py`), adding idempotency via a deterministic client_order_id.
The idempotency key lets the worker safely retry a tick without
double-placing live orders.

Executors implement `place(OrderIntent) -> ExecutionReport`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    OPG = "opg"


class OrderStatus(str, Enum):
    NEW = "new"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass(frozen=True)
class OrderIntent:
    """Broker-agnostic instruction to trade.

    `qty` is in base-asset units (float supports fractional shares / crypto).
    For BUY market orders an adapter may instead use `notional` (quote-asset
    dollar amount). `client_order_id` is the idempotency key — deterministic
    for a given logical order so retries collapse to one broker order."""

    asset_class: str
    symbol: str
    side: Side
    order_type: OrderType = OrderType.MARKET
    qty: Optional[float] = None
    notional: Optional[float] = None
    limit_px: Optional[float] = None
    stop_px: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    signal_time: Optional[datetime] = None
    client_order_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_client_order_id(self) -> str:
        return self.client_order_id or new_id("intent")


@dataclass
class Order:
    order_id: str
    intent: OrderIntent
    status: OrderStatus = OrderStatus.NEW
    submitted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    rejected_reason: Optional[str] = None


@dataclass(frozen=True)
class Fill:
    """A single fill event. Commission is in currency units, not a percent."""

    fill_id: str
    order_id: str
    asset_class: str
    symbol: str
    side: Side
    qty: float
    price: float
    timestamp: datetime
    commission: float = 0.0
    slippage_bps: Optional[float] = None
    executor: Optional[str] = None
    external_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass
class ExecutionReport:
    """Result of a submission. `order` carries broker status; `fills` are any
    fills observed synchronously (paper fills immediately; live brokers like
    Alpaca may report zero fills here and settle asynchronously)."""

    order: Order
    fills: list[Fill] = field(default_factory=list)

    @property
    def filled_qty(self) -> float:
        return sum(f.qty for f in self.fills) or float(self.order.filled_qty)

    @property
    def avg_fill_price(self) -> Optional[float]:
        if self.fills:
            notional = sum(f.qty * f.price for f in self.fills)
            qty = sum(f.qty for f in self.fills)
            return notional / qty if qty else None
        return self.order.avg_fill_price


class Executor:
    name: str = ""

    async def place(self, intent: OrderIntent) -> ExecutionReport:
        """Submit an order intent and return an execution report."""
        raise NotImplementedError

    async def get_account_equity(self) -> Optional[float]:
        """Return the live account equity for position sizing, or None.

        Venues backed by a real broker (Alpaca) override this to report the
        actual balance. Paper/sim executors return None, so the worker falls
        back to settings.default_equity."""
        return None
