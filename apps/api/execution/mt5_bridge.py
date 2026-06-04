"""MT5 bridge executor.

MT5 itself runs on EvoX2/Windows beside the BlackBull demo terminal. This
executor calls that local bridge from the DGX worker and preserves SIGMA's
paper-first guardrails.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import settings

from .base import (
    ExecutionReport,
    Executor,
    Fill,
    Order,
    OrderIntent,
    OrderStatus,
    Side,
    new_id,
)

logger = logging.getLogger(__name__)


class Mt5BridgeExecutor(Executor):
    name = "mt5_bridge"

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        secret: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = (base_url or settings.mt5_bridge_url).rstrip("/")
        self.secret = secret if secret is not None else settings.mt5_bridge_secret
        self._client = client
        if not self.base_url:
            raise ValueError("MT5 bridge URL missing — set MT5_BRIDGE_URL.")
        if not settings.mt5_paper and not settings.mt5_allow_live:
            raise ValueError(
                "Live MT5 trading is disabled. Set MT5_ALLOW_LIVE=true to enable "
                "(MT5_PAPER=false)."
            )

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=settings.mt5_bridge_timeout_seconds)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {"X-MT5-Bridge-Secret": self.secret} if self.secret else {}

    @staticmethod
    def mt5_symbol(symbol: str) -> str:
        return symbol.upper().replace("/", "").replace("-", "").replace("_", "")

    def _volume(self, intent: OrderIntent) -> float:
        if "mt5_volume" in intent.metadata:
            return float(intent.metadata["mt5_volume"])
        if intent.qty is None or intent.qty <= 0:
            return 0.0
        if settings.mt5_qty_is_lots:
            return round(float(intent.qty), 4)
        return round(float(intent.qty) / max(settings.mt5_units_per_lot, 1.0), 4)

    async def place(self, intent: OrderIntent) -> ExecutionReport:
        order = Order(order_id=new_id("mt5"), intent=intent, submitted_at=datetime.now(timezone.utc))
        volume = self._volume(intent)
        if volume <= 0:
            order.status = OrderStatus.REJECTED
            order.rejected_reason = "positive MT5 volume required"
            return ExecutionReport(order=order, fills=[])

        payload = {
            "symbol": self.mt5_symbol(intent.symbol),
            "side": intent.side.value,
            "volume": volume,
            "client_order_id": intent.normalized_client_order_id(),
            "deviation": settings.mt5_deviation_points,
            "paper": settings.mt5_paper,
        }
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: self._post_order(payload))
        except Exception as exc:
            logger.exception("[mt5_bridge] order failed for %s", intent.symbol)
            order.status = OrderStatus.REJECTED
            order.rejected_reason = str(exc)
            return ExecutionReport(order=order, fills=[])

        ticket = str(data.get("ticket") or data.get("order_id") or order.order_id)
        status = str(data.get("status") or "filled").lower()
        filled_qty = float(data.get("filled_qty") or data.get("volume") or volume)
        price = float(data.get("price") or intent.limit_px or 0.0)
        now = datetime.now(timezone.utc)

        order.order_id = ticket
        order.filled_qty = filled_qty
        order.avg_fill_price = price or None
        order.updated_at = now
        order.status = OrderStatus.FILLED if status == "filled" and filled_qty > 0 else OrderStatus.SUBMITTED

        fills = []
        if order.status == OrderStatus.FILLED and price > 0:
            ref = intent.limit_px
            slippage_bps = abs(price - ref) / ref * 10_000.0 if ref else None
            fills.append(Fill(
                fill_id=new_id("fill"),
                order_id=ticket,
                asset_class=intent.asset_class,
                symbol=intent.symbol,
                side=intent.side,
                qty=filled_qty,
                price=price,
                timestamp=now,
                commission=float(data.get("commission", 0) or 0),
                slippage_bps=round(slippage_bps, 4) if slippage_bps is not None else None,
                executor=self.name,
                external_id=ticket,
                metadata=data,
            ))
        return ExecutionReport(order=order, fills=fills)

    async def get_account_equity(self) -> Optional[float]:
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, self._get_account)
        except Exception:
            logger.exception("[mt5_bridge] account fetch failed")
            return None
        for key in ("equity", "balance"):
            val = data.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return None

    def _post_order(self, payload: dict) -> dict:
        resp = self.client.post(f"{self.base_url}/orders", json=payload, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _get_account(self) -> dict:
        resp = self.client.get(f"{self.base_url}/account", headers=self._headers())
        resp.raise_for_status()
        return resp.json()
