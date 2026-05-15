"""Paper executor — simulated fills with size-aware slippage, fees, latency,
and partial-fill modeling.

Body ported from razorBill `execution.py::PaperExecutor`. Adapted to sigma's
`Executor.place(OrderRequest) -> Fill` interface — razorBill's
`market_order(symbol, side, qty, px)` becomes `place(OrderRequest)` where
`limit_px` carries the market reference price."""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone

from config import settings

from .base import Executor, Fill, OrderRequest

logger = logging.getLogger(__name__)


class PaperExecutor(Executor):
    name = "paper"

    async def place(self, order: OrderRequest) -> Fill:
        ref_px = order.limit_px
        if ref_px is None or ref_px <= 0:
            raise ValueError(
                "PaperExecutor requires a reference price via OrderRequest.limit_px "
                "(use the latest candle close)."
            )
        if order.qty <= 0:
            return _zero_fill(order, ref_px, self.name)

        slippage_bps = self._calculate_slippage_bps(ref_px, order.qty)
        slip_px = ref_px * (slippage_bps / 10_000.0)
        exec_px = ref_px + slip_px if order.side == "buy" else ref_px - slip_px

        notional = order.qty * exec_px
        fee_bps = settings.maker_fee_bps if order.side == "buy" else settings.taker_fee_bps
        fee = notional * (fee_bps / 10_000.0)

        await _maybe_sleep(_total_latency_ms())

        fill_pct = settings.partial_fill_pct
        if 0 < fill_pct < 1.0:
            fill_pct = random.uniform(fill_pct, 1.0)
        final_qty = order.qty * fill_pct

        fill = Fill(
            asset_class=order.asset_class,
            symbol=order.symbol,
            ts=datetime.now(timezone.utc),
            side=order.side,
            qty=final_qty,
            px=exec_px,
            fee=fee,
            slippage_bps=float(slippage_bps),
            executor=self.name,
            external_id=f"paper-{uuid.uuid4().hex[:12]}",
        )
        logger.info(
            "[paper] %s %.6f %s @ %.4f (fee=%.2f, slip_bps=%.1f)",
            order.side, final_qty, order.symbol, exec_px, fee, slippage_bps,
        )
        return fill

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


def _zero_fill(order: OrderRequest, ref_px: float, executor_name: str) -> Fill:
    return Fill(
        asset_class=order.asset_class,
        symbol=order.symbol,
        ts=datetime.now(timezone.utc),
        side=order.side,
        qty=0.0,
        px=ref_px,
        fee=0.0,
        slippage_bps=0.0,
        executor=executor_name,
    )
