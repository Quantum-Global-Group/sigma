"""Alpaca equity executor — built on the modern `alpaca-py` SDK.

Ported in spirit from tradeFlux `adapters/alpaca_broker.py`, which used the
deprecated `alpaca-trade-api`. This rewrite targets `alpaca-py`
(`alpaca.trading.*`), keeps the guardrails (live-trading opt-in, order caps,
fractional/notional buys), and conforms to sigma's OrderIntent ->
ExecutionReport contract.

Submission is synchronous in the SDK, so calls run in a thread executor to
keep the worker's event loop free. Alpaca fills asynchronously; `place`
submits then polls up to `alpaca_order_timeout_seconds` for a fill, returning
whatever filled in that window (mirrors the Coinbase executor)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from config import settings

from .base import (
    Executor,
    ExecutionReport,
    Fill,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
    new_id,
)

logger = logging.getLogger(__name__)


class AlpacaExecutor(Executor):
    name = "alpaca"

    def __init__(self) -> None:
        if not (settings.alpaca_api_key and settings.alpaca_secret):
            raise ValueError(
                "Alpaca credentials missing — set ALPACA_API_KEY and ALPACA_SECRET."
            )
        # Hard live-trading guardrail (mirrors tradeFlux TRADEFLUX_ALLOW_LIVE).
        if not settings.alpaca_paper and not settings.alpaca_allow_live:
            raise ValueError(
                "Live Alpaca trading is disabled. Set ALPACA_ALLOW_LIVE=true to enable "
                "(ALPACA_PAPER=false)."
            )

        # Lazy import keeps the SDK out of the api boot path.
        from alpaca.trading.client import TradingClient  # type: ignore[import-not-found]

        self._client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret,
            paper=settings.alpaca_paper,
        )
        logger.info("Alpaca client ready (paper=%s)", settings.alpaca_paper)

    async def place(self, intent: OrderIntent) -> ExecutionReport:
        order = Order(order_id=new_id("alp"), intent=intent, submitted_at=datetime.now(timezone.utc))

        rejection = self._precheck(intent)
        if rejection is not None:
            order.status = OrderStatus.REJECTED
            order.rejected_reason = rejection
            return ExecutionReport(order=order, fills=[])

        client_order_id = intent.normalized_client_order_id()
        loop = asyncio.get_event_loop()

        try:
            request = self._build_request(intent, client_order_id)
            submitted = await loop.run_in_executor(None, lambda: self._client.submit_order(order_data=request))
            broker_id = str(getattr(submitted, "id", "") or client_order_id)
            order.order_id = broker_id
            order.status = OrderStatus.SUBMITTED

            filled = await self._poll_fill(broker_id)
            if filled is None:
                logger.info("[alpaca] %s submitted, no fill within timeout", intent.symbol)
                return ExecutionReport(order=order, fills=[])

            filled_qty = float(getattr(filled, "filled_qty", 0) or 0)
            avg_px = float(getattr(filled, "filled_avg_price", 0) or 0)
            now = datetime.now(timezone.utc)
            order.filled_qty = filled_qty
            order.avg_fill_price = avg_px or None
            order.status = OrderStatus.FILLED if filled_qty > 0 else OrderStatus.SUBMITTED
            order.updated_at = now

            fills = []
            if filled_qty > 0 and avg_px > 0:
                ref = intent.limit_px
                slippage_bps = abs(avg_px - ref) / ref * 10_000.0 if ref else None
                fills.append(Fill(
                    fill_id=new_id("fill"),
                    order_id=broker_id,
                    asset_class=intent.asset_class,
                    symbol=intent.symbol,
                    side=intent.side,
                    qty=filled_qty,
                    price=avg_px,
                    timestamp=now,
                    commission=0.0,  # Alpaca is commission-free for equities
                    slippage_bps=round(slippage_bps, 4) if slippage_bps is not None else None,
                    executor=self.name,
                    external_id=broker_id,
                ))
            return ExecutionReport(order=order, fills=fills)
        except Exception as exc:
            logger.exception("[alpaca] order failed for %s", intent.symbol)
            order.status = OrderStatus.REJECTED
            order.rejected_reason = str(exc)
            return ExecutionReport(order=order, fills=[])

    # ---- internal -------------------------------------------------------

    def _precheck(self, intent: OrderIntent) -> Optional[str]:
        if intent.side == Side.BUY:
            if intent.qty is None and intent.notional is None:
                return "qty or notional required for buy"
            cap_shares = settings.alpaca_max_order_shares
            if cap_shares and intent.qty and intent.qty > cap_shares + 1e-12:
                return "order exceeds alpaca_max_order_shares"
            cap_notional = settings.alpaca_max_order_notional
            if cap_notional and intent.limit_px and intent.qty and intent.qty * intent.limit_px > cap_notional + 1e-9:
                return "order exceeds alpaca_max_order_notional"
        elif (intent.qty is None or intent.qty <= 0):
            return "qty required for sell"
        return None

    def _build_request(self, intent: OrderIntent, client_order_id: str):
        from alpaca.trading.enums import OrderSide, TimeInForce as ATIF  # type: ignore[import-not-found]
        from alpaca.trading.requests import (  # type: ignore[import-not-found]
            LimitOrderRequest,
            MarketOrderRequest,
        )

        side = OrderSide.BUY if intent.side == Side.BUY else OrderSide.SELL
        tif = _map_tif(intent.time_in_force)

        # Fractional/notional buys must be market + day per Alpaca.
        fractional_buy = (
            settings.alpaca_allow_fractional
            and intent.side == Side.BUY
            and (intent.notional is not None or (intent.qty is not None and intent.qty != int(intent.qty)))
        )

        if intent.order_type == OrderType.LIMIT and intent.limit_px:
            return LimitOrderRequest(
                symbol=intent.symbol,
                qty=intent.qty,
                side=side,
                time_in_force=tif,
                limit_price=intent.limit_px,
                client_order_id=client_order_id,
            )

        if fractional_buy:
            kwargs = {"symbol": intent.symbol, "side": side, "time_in_force": ATIF.DAY,
                      "client_order_id": client_order_id}
            if intent.notional is not None:
                kwargs["notional"] = round(float(intent.notional), 2)
            else:
                kwargs["qty"] = float(intent.qty)
            return MarketOrderRequest(**kwargs)

        # Whole-share (or fractional sell) market order
        qty = float(intent.qty) if (settings.alpaca_allow_fractional and intent.side == Side.SELL) else int(intent.qty)
        return MarketOrderRequest(
            symbol=intent.symbol,
            qty=qty,
            side=side,
            time_in_force=tif,
            client_order_id=client_order_id,
        )

    async def _poll_fill(self, order_id: str):
        timeout = settings.alpaca_order_timeout_seconds
        deadline = datetime.now(timezone.utc).timestamp() + timeout
        loop = asyncio.get_event_loop()
        while datetime.now(timezone.utc).timestamp() < deadline:
            try:
                o = await loop.run_in_executor(None, lambda: self._client.get_order_by_id(order_id))
            except Exception:
                logger.exception("[alpaca] poll error for %s", order_id)
                await asyncio.sleep(1.0)
                continue
            status = str(getattr(o, "status", "")).lower()
            if "filled" in status and "partially" not in status:
                return o
            if status in ("canceled", "cancelled", "expired", "rejected"):
                return o
            await asyncio.sleep(1.0)
        # Final read after timeout — may be partially filled
        try:
            return await loop.run_in_executor(None, lambda: self._client.get_order_by_id(order_id))
        except Exception:
            return None


def _map_tif(tif: TimeInForce):
    from alpaca.trading.enums import TimeInForce as ATIF  # type: ignore[import-not-found]
    return {
        TimeInForce.DAY: ATIF.DAY,
        TimeInForce.GTC: ATIF.GTC,
        TimeInForce.IOC: ATIF.IOC,
        TimeInForce.FOK: ATIF.FOK,
        TimeInForce.OPG: ATIF.OPG,
    }.get(tif, ATIF.DAY)
