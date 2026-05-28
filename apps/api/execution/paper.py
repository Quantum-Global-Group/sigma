"""Paper executor — simulated fills with size-aware slippage, fees, latency,
and partial-fill modeling. Fills immediately (synchronous).

Upgraded to the OrderIntent -> ExecutionReport contract."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone

from config import settings

from .base import (
    Executor,
    ExecutionReport,
    Fill,
    Order,
    OrderIntent,
    OrderStatus,
    Side,
    new_id,
)

logger = logging.getLogger(__name__)


class PaperExecutor(Executor):
    name = "paper"

    async def place(self, intent: OrderIntent) -> ExecutionReport:
        ref_px = intent.limit_px
        if ref_px is None or ref_px <= 0:
            raise ValueError(
                "PaperExecutor requires a reference price via OrderIntent.limit_px "
                "(use the latest candle close)."
            )

        order = Order(
            order_id=new_id("paper"),
            intent=intent,
            submitted_at=datetime.now(timezone.utc),
        )

        qty = intent.qty or 0.0
        if qty <= 0:
            order.status = OrderStatus.REJECTED
            order.rejected_reason = "qty <= 0"
            return ExecutionReport(order=order, fills=[])

        slippage_bps = self._calculate_slippage_bps(ref_px, qty)
        slip_px = ref_px * (slippage_bps / 10_000.0)
        exec_px = ref_px + slip_px if intent.side == Side.BUY else ref_px - slip_px

        fee_bps = settings.maker_fee_bps if intent.side == Side.BUY else settings.taker_fee_bps
        notional = qty * exec_px
        fee = notional * (fee_bps / 10_000.0)

        await _maybe_sleep(_total_latency_ms())

        fill_pct = settings.partial_fill_pct
        if 0 < fill_pct < 1.0:
            fill_pct = random.uniform(fill_pct, 1.0)
        final_qty = qty * fill_pct

        now = datetime.now(timezone.utc)
        fill = Fill(
            fill_id=new_id("fill"),
            order_id=order.order_id,
            asset_class=intent.asset_class,
            symbol=intent.symbol,
            side=intent.side,
            qty=final_qty,
            price=exec_px,
            timestamp=now,
            commission=fee,
            slippage_bps=float(slippage_bps),
            executor=self.name,
            external_id=order.order_id,
        )
        order.status = OrderStatus.FILLED
        order.filled_qty = final_qty
        order.avg_fill_price = exec_px
        order.updated_at = now

        logger.info(
            "[paper] %s %.6f %s @ %.4f (fee=%.2f, slip_bps=%.1f)",
            intent.side.value, final_qty, intent.symbol, exec_px, fee, slippage_bps,
        )
        return ExecutionReport(order=order, fills=[fill])

    def _calculate_slippage_bps(self, px: float, qty: float) -> float:
        base = settings.base_slippage_bps
        if px < settings.smallcap_price_threshold_usd:
            base = settings.smallcap_slippage_bps
        notional = qty * px
        if notional > 10_000:
            base *= 1.5
        elif notional < 1_000:
            base *= 0.5
        return float(base)


def _total_latency_ms() -> int:
    base = settings.order_latency_ms
    lo = settings.order_latency_jitter_min_ms
    hi = settings.order_latency_jitter_max_ms
    if hi > 0 and hi >= lo:
        base += random.randint(lo, hi)
    return base


async def _maybe_sleep(ms: int) -> None:
    if ms > 0:
        await asyncio.sleep(ms / 1000.0)
