from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import settings

from .base import Executor, Fill, OrderRequest

logger = logging.getLogger(__name__)


class CoinbaseExecutor(Executor):
    """Live Coinbase Advanced Trade executor.

    Skeleton — the body will be ported from razorBill's coinbase_executor.py
    during the subtree port step. This file exists so `get_executor()` can
    resolve the class today."""

    name = "coinbase"

    def __init__(self) -> None:
        if not (settings.coinbase_api_key_name and settings.coinbase_private_key):
            raise RuntimeError(
                "CoinbaseExecutor requires COINBASE_API_KEY_NAME and "
                "COINBASE_PRIVATE_KEY"
            )
        # Lazy import: avoid pulling SDK on every API boot.
        from coinbase.rest import RESTClient  # type: ignore[import-not-found]

        self._client = RESTClient(
            api_key=settings.coinbase_api_key_name,
            api_secret=settings.coinbase_private_key,
        )

    async def place(self, order: OrderRequest) -> Fill:
        raise NotImplementedError(
            "CoinbaseExecutor.place is a stub; razorBill's coinbase_executor.py "
            "will be ported here in the subtree step."
        )
