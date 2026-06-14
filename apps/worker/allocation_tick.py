"""Monthly trend-filtered rebalance — the worker path for the deployable strategy.

Replaces the directional equity signals (measured edgeless) with the one strategy
that cleared the cross-regime, cost-aware bar: hold diversified ETF sleeves only
while each is above its N-month moving average, else cash (see docs/MODELS.md,
ml/allocation.py). Runs on the worker's cadence but ACTS only when a new calendar
month begins — faithful to the monthly backtest, idempotent within a month.

Enable: set `allocation_enabled=true` and put `allocation` in WORKER_ASSET_CLASSES
*instead of* `equity` (both managing the equity book would fight). Trades the
equity executor (Alpaca paper); positions live in the house book.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from cache.redis import cache_get, cache_set
from config import settings
from db.connection import AsyncSessionLocal
from execution import get_executor
from execution.base import OrderIntent, OrderType, Side, TimeInForce
from markets import get_market_adapter
from ml.allocation import parse_weights, rebalance_orders, target_weights

logger = logging.getLogger(__name__)

_REBAL_KEY = "allocation:last_rebalance"


async def allocation_rebalance() -> None:
    if not settings.allocation_enabled:
        logger.info("[allocation] disabled (allocation_enabled=false)")
        return
    base = parse_weights(settings.allocation_weights)
    if not base:
        logger.warning("[allocation] no weights configured — nothing to do")
        return

    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    if not settings.allocation_force and (await cache_get(_REBAL_KEY)) == ym:
        logger.info("[allocation] already rebalanced %s — skipping", ym)
        return

    adapter = get_market_adapter("equity")
    if not adapter.is_market_open():
        logger.info("[allocation] market closed — deferring rebalance")
        return

    # Prices for the trend filter + last price for sizing.
    prices: dict[str, pd.Series] = {}
    last_price: dict[str, float] = {}
    for sym in base:
        try:
            df = adapter.fetch_ohlcv(sym, "daily")
            if df is not None and len(df):
                prices[sym] = df["close"].astype(float)
                last_price[sym] = float(df["close"].iloc[-1])
        except Exception:
            logger.warning("[allocation] price fetch failed for %s", sym, exc_info=True)
    if not prices:
        logger.warning("[allocation] no prices fetched — aborting rebalance")
        return

    targets = target_weights(prices, base, settings.allocation_ma_months)
    executor = get_executor("equity")

    # Imported here to avoid a circular import at module load.
    from worker.tick import (
        _client_order_id,
        _load_open_positions,
        _resolve_equity,
        _submit_and_persist,
    )

    async with AsyncSessionLocal() as session:
        positions = await _load_open_positions(session, "equity")
        current_qty = {s: float(p.qty) for s, p in positions.items()}
        equity = await _resolve_equity(executor, None)
        orders = rebalance_orders(
            targets, equity, current_qty, last_price,
            min_trade_usd=settings.allocation_min_trade_usd,
        )
        held = {k: round(v, 3) for k, v in targets.items() if v > 0}
        logger.info("[allocation] %s equity=%.0f in-trend=%s cash=%.0f%% orders=%d",
                    ym, equity, held, (1 - sum(targets.values())) * 100, len(orders))

        signal_ts = pd.Timestamp(f"{ym}-01", tz="UTC")   # monthly bucket → idempotent
        placed = 0
        for o in orders:
            intent = OrderIntent(
                asset_class="equity", symbol=o.symbol,
                side=Side.BUY if o.side == "buy" else Side.SELL,
                order_type=OrderType.MARKET, qty=o.qty,
                limit_px=last_price[o.symbol], time_in_force=TimeInForce.DAY,
                signal_time=signal_ts,
                client_order_id=_client_order_id("equity", o.symbol, "rebal", signal_ts),
            )
            report, _affected, skip = await _submit_and_persist(session, executor, intent, positions.get(o.symbol))
            if report is not None and skip is None:
                placed += 1
        await session.commit()

    await cache_set(_REBAL_KEY, ym, ttl=60 * 60 * 24 * 40)
    logger.info("[allocation] %s rebalance complete — %d/%d orders placed", ym, placed, len(orders))
