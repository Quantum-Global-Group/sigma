from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from config import settings

from .base import Executor, Fill, OrderRequest


class PaperExecutor(Executor):
    """Simulated executor with configurable slippage + fee model.

    Mirrors razorBill's PaperExecutor: maker/taker bps from config, additional
    bps for small caps, optional latency jitter, partial fill probability.
    Implementation will be filled in during the razorBill port; this skeleton
    keeps the worker importable today."""

    name = "paper"

    async def place(self, order: OrderRequest) -> Fill:
        # Placeholder: assume market fill at the limit/notional reference price
        # with taker fee. Real model lands when razorBill code is ported.
        ref_px = order.limit_px or 0.0
        if ref_px == 0.0:
            raise NotImplementedError(
                "PaperExecutor needs a reference price; razorBill port will wire "
                "this to the latest candle close."
            )

        slippage_bps = float(getattr(settings, "smallcap_slippage_bps", 0)) or 5.0
        slippage = ref_px * slippage_bps / 10_000
        fill_px = ref_px + slippage if order.side == "buy" else ref_px - slippage
        taker_bps = float(getattr(settings, "taker_fee_bps", 6))
        fee = abs(fill_px * order.qty) * taker_bps / 10_000

        # Simulate latency
        latency_ms = float(getattr(settings, "order_latency_ms", 0))
        if latency_ms:
            import asyncio
            await asyncio.sleep(latency_ms / 1000.0 * random.uniform(0.5, 1.5))

        return Fill(
            asset_class=order.asset_class,
            symbol=order.symbol,
            ts=datetime.now(timezone.utc),
            side=order.side,
            qty=order.qty,
            px=fill_px,
            fee=fee,
            slippage_bps=slippage_bps,
            executor=self.name,
            external_id=f"paper-{uuid.uuid4().hex[:12]}",
        )
