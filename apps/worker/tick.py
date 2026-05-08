"""Worker tick — one full trading cycle for an asset class.

Pipeline (per symbol):
  1. fetch candles via MarketAdapter
  2. compute features via FeatureEngineer (razorBill columns)
  3. strategy combiner -> Signal
  4. translate to SignalResult, persist signal_history row
  5. confidence + strength gate (settings.min_signal_confidence)
  6. position sizing via PositionSizer (Kelly cap)
  7. executor.place(order) -> Fill
  8. persist Order + create/update Position via sigma's ORM

Exit evaluation runs first against existing positions and emits SELL fills
before any new entries. Persistence is owned here (not in apps/api/risk/);
the risk module exposes pure decision functions that this tick consumes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.connection import AsyncSessionLocal
from db.models import Order, Position, SignalHistory
from execution import get_executor
from execution.base import OrderRequest
from markets import get_market_adapter
from ml.sequences import FeatureEngineer
from ml.strategies import build_default_combiner, combine_to_result
from risk.exits import compute_exit_orders
from risk.sizing import PositionSizer
from universe import get_universe_selector

logger = logging.getLogger(__name__)


async def tick_once(asset_class: str, equity: float = 10_000.0) -> None:
    """Run one cycle for `asset_class`. Logs each symbol's outcome."""
    adapter = get_market_adapter(asset_class)
    if not adapter.is_market_open():
        logger.info("[%s] market closed — skipping tick", asset_class)
        return

    selector = get_universe_selector(asset_class)
    symbols = selector.select()
    logger.info("[%s] tick: %d symbols", asset_class, len(symbols))

    executor = get_executor()
    combiner = build_default_combiner()
    fe = FeatureEngineer()
    sizer = PositionSizer(equity)

    async with AsyncSessionLocal() as session:
        positions = await _load_open_positions(session, asset_class)

        for symbol in symbols:
            try:
                await _process_symbol(
                    session=session,
                    asset_class=asset_class,
                    symbol=symbol,
                    adapter=adapter,
                    fe=fe,
                    combiner=combiner,
                    sizer=sizer,
                    executor=executor,
                    open_position=positions.get(symbol),
                )
            except Exception:
                logger.exception("[%s] %s tick failed", asset_class, symbol)
        await session.commit()


# ---------------------------------------------------------------------------
# per-symbol logic
# ---------------------------------------------------------------------------

async def _process_symbol(
    *,
    session: AsyncSession,
    asset_class: str,
    symbol: str,
    adapter,
    fe: FeatureEngineer,
    combiner,
    sizer: PositionSizer,
    executor,
    open_position: Optional[Position],
) -> None:
    df = adapter.fetch_ohlcv(symbol, _default_timeframe(asset_class))
    if df.empty:
        return

    feats = fe.compute(df)
    px_now = float(feats["c"].iloc[-1])

    # 1. Exit check on any existing position before new entries.
    if open_position is not None:
        await _maybe_exit(
            session=session,
            position=open_position,
            features=feats,
            px_now=px_now,
            executor=executor,
        )

    # 2. Combiner -> SignalResult, persist signal_history row.
    combined = combiner.combine_signals(symbol, feats, px_now)
    result = combine_to_result(combined)
    session.add(SignalHistory(
        user_id=settings.system_user_id,  # cast handled by SQLAlchemy
        ticker=symbol,
        timeframe=_default_timeframe(asset_class),
        asset_class=asset_class,
        signal=result.signal,
        confidence=result.confidence,
        predicted_return=result.predicted_return,
        model_version=result.model_version,
        component_weights=result.component_weights,
    ))

    # 3. Entry gate: confidence + already-positioned skip.
    if result.signal == "HOLD" or result.confidence < settings.min_signal_confidence:
        logger.info(
            "[%s] %s no-trade signal=%s conf=%.2f", asset_class, symbol, result.signal, result.confidence,
        )
        return
    if open_position is not None and open_position.qty > 0 and result.signal == "BUY":
        return  # already long; skip until exit

    # 4. Size + place order.
    sized = sizer.kelly_optimal(
        price=px_now,
        signal=combined.strength,
    )
    if sized.qty <= 0 or sized.notional <= 0:
        logger.info("[%s] %s sizer returned zero qty", asset_class, symbol)
        return

    side = "buy" if result.signal == "BUY" else "sell"
    order_req = OrderRequest(
        asset_class=asset_class,
        symbol=symbol,
        side=side,
        qty=sized.qty,
        limit_px=px_now,
    )
    fill = await executor.place(order_req)
    if fill.qty <= 0:
        logger.info("[%s] %s zero-fill", asset_class, symbol)
        return

    session.add(Order(
        asset_class=fill.asset_class,
        symbol=fill.symbol,
        ts=fill.ts,
        side=fill.side,
        qty=fill.qty,
        px=fill.px,
        fee=fill.fee,
        slippage_bps=fill.slippage_bps,
        executor=fill.executor,
        external_id=fill.external_id,
        status="filled",
        raw=fill.raw,
    ))
    await _apply_fill_to_position(session, fill, open_position)


async def _maybe_exit(
    *,
    session: AsyncSession,
    position: Position,
    features: pd.DataFrame,
    px_now: float,
    executor,
) -> None:
    """Run razorBill's compute_exit_orders. If it emits SELL orders, place
    them through the executor and close the position."""
    qty = float(position.qty)
    if qty <= 0:
        return

    orders, _, _ = compute_exit_orders(
        symbol=position.symbol,
        g=features,
        px_now=px_now,
        pos_qty=qty,
        entry_px=float(position.entry_px),
        entry_time=position.entry_ts,
        current_signal=0.0,  # neutral — exits driven by stop/TP geometry
        exit_state={},
    )
    for raw in orders:
        side = raw.get("side", "sell")
        sell_qty = float(raw.get("qty", qty))
        if sell_qty <= 0:
            continue
        order_req = OrderRequest(
            asset_class=position.asset_class,
            symbol=position.symbol,
            side=side,
            qty=sell_qty,
            limit_px=px_now,
        )
        fill = await executor.place(order_req)
        if fill.qty <= 0:
            continue
        session.add(Order(
            asset_class=fill.asset_class,
            symbol=fill.symbol,
            ts=fill.ts,
            side=fill.side,
            qty=fill.qty,
            px=fill.px,
            fee=fill.fee,
            slippage_bps=fill.slippage_bps,
            executor=fill.executor,
            external_id=fill.external_id,
            status="filled",
            raw=fill.raw,
        ))
        await _apply_fill_to_position(session, fill, position)


# ---------------------------------------------------------------------------
# persistence helpers
# ---------------------------------------------------------------------------

async def _load_open_positions(session: AsyncSession, asset_class: str) -> dict[str, Position]:
    res = await session.execute(
        select(Position).where(Position.asset_class == asset_class).where(Position.closed.is_(False))
    )
    return {row.symbol: row for row in res.scalars().all()}


async def _apply_fill_to_position(
    session: AsyncSession,
    fill,
    existing: Optional[Position],
) -> None:
    """Naive position mutation: buy opens/adds; sell closes (full or partial)."""
    if fill.side == "buy":
        if existing is None or existing.closed:
            session.add(Position(
                asset_class=fill.asset_class,
                symbol=fill.symbol,
                qty=fill.qty,
                entry_px=fill.px,
                entry_ts=fill.ts,
                current_px=fill.px,
            ))
            return
        # add to existing — weighted average entry
        new_qty = float(existing.qty) + fill.qty
        existing.entry_px = (
            float(existing.entry_px) * float(existing.qty) + fill.px * fill.qty
        ) / max(new_qty, 1e-12)
        existing.qty = new_qty
        existing.current_px = fill.px
        existing.updated_at = datetime.now(timezone.utc)
        return

    # sell
    if existing is None:
        return
    remaining = float(existing.qty) - fill.qty
    if remaining <= 1e-9:
        existing.qty = 0.0
        existing.closed = True
        existing.closed_at = datetime.now(timezone.utc)
        existing.realized_pnl = float(existing.realized_pnl) + (fill.px - float(existing.entry_px)) * fill.qty
    else:
        existing.qty = remaining
        existing.realized_pnl = float(existing.realized_pnl) + (fill.px - float(existing.entry_px)) * fill.qty
        existing.current_px = fill.px


def _default_timeframe(asset_class: str) -> str:
    return "5m" if asset_class == "crypto" else "daily"
