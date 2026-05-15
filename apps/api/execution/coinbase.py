"""Live Coinbase Advanced Trade executor.

Body ported from razorBill `coinbase_executor.py`. Adapted to sigma's
`Executor.place(OrderRequest) -> Fill` interface.

Coinbase Advanced Trade API uses EC private key authentication. The new
key format (`api_key_name` + `private_key`) is preferred; the legacy HMAC
format (`api_key` + `api_secret` + `passphrase`) is accepted for
back-compat with older razorBill deployments."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from config import settings

from .base import Executor, Fill, OrderRequest

logger = logging.getLogger(__name__)


class CoinbaseExecutor(Executor):
    name = "coinbase"

    def __init__(self) -> None:
        api_key_name, private_key = self._resolve_credentials()

        # Lazy import: keeps the api process from pulling the SDK on boot.
        from coinbase.rest import RESTClient  # type: ignore[import-not-found]

        base_url = "api-sandbox.coinbase.com" if settings.coinbase_sandbox else "api.coinbase.com"
        self._client = RESTClient(
            api_key=api_key_name,
            api_secret=private_key,
            base_url=base_url,
        )
        logger.info("Coinbase Advanced Trade client ready (sandbox=%s)", settings.coinbase_sandbox)

    @staticmethod
    def _resolve_credentials() -> tuple[str, str]:
        if settings.coinbase_api_key_name and settings.coinbase_private_key:
            pk = settings.coinbase_private_key
            if "\\n" in pk:
                pk = pk.replace("\\n", "\n")
            return settings.coinbase_api_key_name, pk
        if settings.coinbase_api_key and settings.coinbase_api_secret:
            logger.warning("Using legacy Coinbase HMAC keys — consider migrating to api_key_name + private_key")
            return settings.coinbase_api_key, settings.coinbase_api_secret
        raise ValueError(
            "Coinbase credentials missing — set COINBASE_API_KEY_NAME + COINBASE_PRIVATE_KEY "
            "(preferred) or the legacy COINBASE_API_KEY + COINBASE_API_SECRET pair."
        )

    async def place(self, order: OrderRequest) -> Fill:
        ref_px = order.limit_px
        if ref_px is None or ref_px <= 0:
            raise ValueError("CoinbaseExecutor requires a reference price via OrderRequest.limit_px")
        if order.qty <= 0:
            return _zero_fill(order, ref_px, self.name)

        client_order_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()

        try:
            if order.side == "buy":
                quote_size = str(order.qty * ref_px)
                logger.info("[coinbase] BUY %s qty=%.6f quote=%s", order.symbol, order.qty, quote_size)
                response = await loop.run_in_executor(
                    None,
                    lambda: self._client.market_order_buy(
                        client_order_id=client_order_id,
                        product_id=order.symbol,
                        quote_size=quote_size,
                    ),
                )
            else:
                base_size = str(order.qty)
                logger.info("[coinbase] SELL %s base=%s", order.symbol, base_size)
                response = await loop.run_in_executor(
                    None,
                    lambda: self._client.market_order_sell(
                        client_order_id=client_order_id,
                        product_id=order.symbol,
                        base_size=base_size,
                    ),
                )

            order_id = _extract_order_id(response) or client_order_id
            logger.info("[coinbase] order placed: %s for %s", order_id, order.symbol)

            details = await self._poll_order_status(order_id)
            if not details:
                logger.error("[coinbase] no fill details for %s", order_id)
                return _zero_fill(order, ref_px, self.name)

            filled_size = float(_get_nested(details, "filled_size", "filledSize", "filled", "size", default=0))
            avg_px = float(_get_nested(details, "average_filled_price", "averageFilledPrice",
                                       "average_price", "averagePrice", "price", default=ref_px))
            fee = float(_get_nested(details, "total_fees", "totalFees", "fees", "fee", default=0))

            slippage_bps = abs(avg_px - ref_px) / ref_px * 10_000.0 if ref_px else 0.0

            fill = Fill(
                asset_class=order.asset_class,
                symbol=order.symbol,
                ts=datetime.now(timezone.utc),
                side=order.side,
                qty=filled_size,
                px=avg_px,
                fee=fee,
                slippage_bps=round(slippage_bps, 4),
                executor=self.name,
                external_id=str(order_id),
                raw=_to_dict(details),
            )
            logger.info(
                "[coinbase] filled %s %.6f %s @ %.4f (fee=%.4f, slip=%.1fbps)",
                order.side, filled_size, order.symbol, avg_px, fee, slippage_bps,
            )
            return fill
        except Exception:
            logger.exception("[coinbase] order failed for %s", order.symbol)
            return _zero_fill(order, ref_px, self.name)

    async def _poll_order_status(self, order_id: str) -> Optional[dict]:
        timeout = settings.coinbase_order_timeout_seconds
        deadline = datetime.now(timezone.utc).timestamp() + timeout
        loop = asyncio.get_event_loop()

        while datetime.now(timezone.utc).timestamp() < deadline:
            try:
                details = await loop.run_in_executor(
                    None, lambda: self._client.get_order(order_id=order_id)
                )
            except Exception:
                logger.exception("[coinbase] poll error for %s", order_id)
                await asyncio.sleep(1.0)
                continue

            if not details:
                await asyncio.sleep(1.0)
                continue

            status = _extract_status(details)
            if not status:
                await asyncio.sleep(1.0)
                continue

            status = status.upper()
            if status in ("FILLED", "SETTLED"):
                return details
            if status in ("CANCELLED", "EXPIRED", "REJECTED", "FAILED"):
                logger.warning("[coinbase] order %s status=%s", order_id, status)
                return details
            await asyncio.sleep(1.0)

        logger.warning("[coinbase] poll timeout for %s after %ss", order_id, timeout)
        return None


# ---------------------------------------------------------------------------
# helpers — Coinbase SDK responses can be objects, dicts, or nested envelopes
# ---------------------------------------------------------------------------

def _zero_fill(order: OrderRequest, ref_px: float, name: str) -> Fill:
    return Fill(
        asset_class=order.asset_class,
        symbol=order.symbol,
        ts=datetime.now(timezone.utc),
        side=order.side,
        qty=0.0,
        px=ref_px,
        fee=0.0,
        slippage_bps=0.0,
        executor=name,
    )


def _to_dict(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            return None
    return None


def _extract_order_id(response):
    for attr in ("order_id", "id"):
        if hasattr(response, attr) and getattr(response, attr):
            return getattr(response, attr)
    if hasattr(response, "order") and hasattr(response.order, "order_id"):
        return response.order.order_id
    if isinstance(response, dict):
        for key in ("order_id", "orderId", "id"):
            if response.get(key):
                return response[key]
        nested = response.get("order")
        if isinstance(nested, dict):
            for key in ("order_id", "orderId", "id"):
                if nested.get(key):
                    return nested[key]
    if hasattr(response, "client_order_id"):
        return response.client_order_id
    return None


def _extract_status(details):
    if hasattr(details, "order") and hasattr(details.order, "status"):
        return str(details.order.status)
    if hasattr(details, "status"):
        return str(details.status)
    if isinstance(details, dict):
        if details.get("status"):
            return str(details["status"])
        nested = details.get("order")
        if isinstance(nested, dict) and nested.get("status"):
            return str(nested["status"])
    return None


def _get_nested(data, *keys, default=0):
    if data is None:
        return default
    if hasattr(data, "to_dict"):
        try:
            data = data.to_dict()
        except Exception:
            pass
    if isinstance(data, dict):
        for k in keys:
            if k in data and data[k] is not None:
                return data[k]
        nested = data.get("order")
        if isinstance(nested, dict):
            for k in keys:
                if k in nested and nested[k] is not None:
                    return nested[k]
    else:
        for k in keys:
            v = getattr(data, k, None)
            if v is not None:
                return v
        nested = getattr(data, "order", None)
        if nested is not None:
            for k in keys:
                v = getattr(nested, k, None)
                if v is not None:
                    return v
    return default
