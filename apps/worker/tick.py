"""Worker tick — one full trading cycle for an asset class.

Pipeline (per symbol):
  1. fetch candles via MarketAdapter
  2. compute features via FeatureEngineer (razorBill columns)
  3. exit-check existing positions (advanced or basic, configurable)
  4. strategy combiner -> Signal
  5. translate to SignalResult, persist signal_history row
  6. rebuy cooldown gate (skip BUY if recent SELL on same symbol)
  7. confidence + strength gate (min_signal_confidence / min_signal_confidence_forex)
  8. position sizing via PositionSizer (Kelly cap)
  9. executor.place(order) -> Fill
 10. persist Order + create/update Position + ExitState via sigma's ORM

Exit evaluation runs first against existing positions and emits SELL fills
before any new entries. Persistence is owned here (not in apps/api/risk/);
the risk module exposes pure decision functions that this tick consumes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.connection import AsyncSessionLocal
from db.models import ExitState, Order, Position, SignalHistory
from execution import get_executor
from execution.base import ExecutionReport, OrderIntent, OrderStatus, OrderType, Side, TimeInForce
from execution.idempotency import already_submitted
from markets import get_market_adapter
from ml.sequences import FeatureEngineer
from ml.strategies import build_default_combiner, combine_to_result
from risk.audit_log import AuditLog
from risk.exits import compute_exit_orders, compute_exit_orders_advanced
from risk.kill_switch import KillSwitch
from risk.sizing import PositionSizer
from universe import get_universe_selector

logger = logging.getLogger(__name__)

# Process-wide kill switch for the standard (equity/crypto/forex) tick — halts
# new BUY entries when tripped (exits still flow). Mirrors the options worker's
# switch. Tripped by ops/preflight or future risk-anomaly wiring; reset to resume.
_kill_switch = KillSwitch()


# ---------------------------------------------------------------------------
# ExitState ↔ razorBill state-dict mapping
# ---------------------------------------------------------------------------
#
# razorBill exit_state[symbol] = {
#     "took_partial": bool,
#     "breakeven_px": float | None,
#     "tight_trailing": float | None,
# }
# sigma ExitState row has the same three (under different names) plus
# high_water_px (sigma-only, used to ratchet trailing stops upward).

def _exit_state_to_dict(es: ExitState | None, high_water_seed: float | None = None) -> dict:
    if es is None:
        return {
            "took_partial": False,
            "breakeven_px": None,
            "tight_trailing": None,
            "high_water_px": high_water_seed,
        }
    return {
        "took_partial": bool(es.partial_tp_done),
        "breakeven_px": float(es.breakeven_px) if es.breakeven_px is not None else None,
        "tight_trailing": float(es.trailing_stop_px) if es.trailing_stop_px is not None else None,
        "high_water_px": float(es.high_water_px) if es.high_water_px is not None else None,
    }


def _apply_state_to_es(es: ExitState, state: dict) -> None:
    es.partial_tp_done = bool(state.get("took_partial", False))
    be = state.get("breakeven_px")
    es.breakeven_px = float(be) if be is not None else None
    tt = state.get("tight_trailing")
    es.trailing_stop_px = float(tt) if tt is not None else None
    hw = state.get("high_water_px")
    es.high_water_px = float(hw) if hw is not None else None
    es.last_evaluated_at = datetime.now(timezone.utc)


async def tick_once(asset_class: str, equity: Optional[float] = None) -> None:
    """Run one cycle for `asset_class`. Logs each symbol's outcome.

    `equity` for position sizing is resolved in priority order:
      explicit arg → executor's live account balance → settings.default_equity."""
    adapter = get_market_adapter(asset_class)
    if not adapter.is_market_open():
        logger.info("[%s] market closed — skipping tick", asset_class)
        return

    selector = get_universe_selector(asset_class)
    symbols = selector.select()
    if asset_class == "forex" and not await _supervise_mt5_bridge(symbols):
        from markets.forex_routing import is_mt5_symbol
        symbols = [s for s in symbols if not is_mt5_symbol(s)]
    logger.info("[%s] tick: %d symbols", asset_class, len(symbols))
    if not symbols:
        return

    executor = get_executor(asset_class)
    from sim.synthetic import demo_combiner_if_enabled
    combiner = demo_combiner_if_enabled(asset_class, build_default_combiner)
    fe = FeatureEngineer()
    equity_by_executor: dict[str, float] = {}

    audit_log = AuditLog()

    async with AsyncSessionLocal() as session:
        # Resolve the active (human-approved champion) model + its version so
        # signal_history is tagged with the version that produced it — the join
        # the self-evolution loop later evaluates.
        model, model_version = await _resolve_champion_model(session, asset_class)
        positions = await _load_open_positions(session, asset_class)
        exit_states = await _load_exit_states(session, list(positions.values()))
        recent_sells = await _load_recent_sells(session, asset_class)

        for symbol in symbols:
            try:
                symbol_adapter = _adapter_for_symbol(asset_class, symbol, adapter)
                symbol_executor = _executor_for_symbol(asset_class, symbol)
                executor_key = getattr(symbol_executor, "name", "unknown")
                if executor_key not in equity_by_executor:
                    equity_by_executor[executor_key] = await _resolve_equity(symbol_executor, equity)
                    logger.info(
                        "[%s] sizing equity via %s = %.2f",
                        asset_class, executor_key, equity_by_executor[executor_key],
                    )
                sizer = PositionSizer(equity_by_executor[executor_key])
                await _process_symbol(
                    session=session,
                    asset_class=asset_class,
                    symbol=symbol,
                    adapter=symbol_adapter,
                    fe=fe,
                    combiner=combiner,
                    model=model,
                    model_version=model_version,
                    sizer=sizer,
                    executor=symbol_executor,
                    open_position=positions.get(symbol),
                    exit_state=exit_states.get(symbol, {}),
                    recent_sells=recent_sells,
                    audit_log=audit_log,
                )
            except Exception:
                logger.exception("[%s] %s tick failed", asset_class, symbol)

        # Persist decision provenance (best-effort — never break the tick).
        try:
            from db.audit_store import persist_audit_log
            n = await persist_audit_log(session, audit_log)
            logger.info("[%s] persisted %d audit records", asset_class, n)
        except Exception:
            logger.exception("[%s] audit persist failed", asset_class)

        await session.commit()


def _adapter_for_symbol(asset_class: str, symbol: str, default_adapter):
    if asset_class == "forex":
        from markets.forex_routing import get_forex_adapter
        return get_forex_adapter(symbol)
    return default_adapter


def _executor_for_symbol(asset_class: str, symbol: str):
    if asset_class == "forex":
        from markets.forex_routing import get_forex_executor
        return get_forex_executor(symbol)
    return get_executor(asset_class)


async def _supervise_mt5_bridge(symbols: list[str]) -> bool:
    """Probe MT5 bridge when the forex universe contains MT5-routed symbols."""
    from markets.forex_routing import is_mt5_symbol

    if not any(is_mt5_symbol(s) for s in symbols):
        return True
    from cache.worker_status import write_mt5_bridge_status
    from markets.mt5_bridge_health import check_mt5_bridge

    reachable, detail = await check_mt5_bridge(
        settings.mt5_bridge_url,
        secret=settings.mt5_bridge_secret,
        timeout=min(float(settings.mt5_bridge_timeout_seconds), 5.0),
    )
    await write_mt5_bridge_status(reachable, detail)
    if not reachable:
        logger.error("[forex] MT5 bridge unreachable (%s) — skipping MT5 symbols", detail)
    return reachable


# ---------------------------------------------------------------------------
# per-symbol logic
# ---------------------------------------------------------------------------

def _snapshot_audit_features(feats: pd.DataFrame) -> dict:
    """Last-bar feature snapshot for audit persistence (pure, testable)."""
    if feats.empty:
        return {}
    row = feats.iloc[-1]
    out: dict = {"px": float(row["c"]) if "c" in row.index else None}
    for key in ("rsi", "atr", "mom_1", "mom_3", "vol_realized", "breakout_20"):
        if key in row.index:
            try:
                out[key] = float(row[key])
            except (TypeError, ValueError):
                pass
    return out


async def _process_symbol(
    *,
    session: AsyncSession,
    asset_class: str,
    symbol: str,
    adapter,
    fe: FeatureEngineer,
    combiner,
    model,
    model_version: str,
    sizer: PositionSizer,
    executor,
    open_position: Optional[Position],
    exit_state: dict,
    recent_sells: dict[str, datetime],
    audit_log: AuditLog,
) -> None:
    rec = audit_log.new(symbol, asset_class=asset_class)
    timeframe = _default_timeframe(asset_class)
    df = adapter.fetch_ohlcv(symbol, timeframe)
    if df.empty:
        rec.gate("G1_data", False, ["empty OHLCV"]).finalize("skipped")
        return

    # Harness the bars we just fetched (best-effort — never break the tick).
    if settings.persist_candles:
        try:
            from db.candle_store import upsert_candles
            await upsert_candles(
                session, asset_class=asset_class, symbol=symbol,
                timeframe=timeframe, df=df,
                source=getattr(adapter, "name", asset_class),
                tail=settings.persist_candles_tail,
            )
        except Exception:
            logger.debug("[%s] %s candle persist failed", asset_class, symbol, exc_info=True)

    feats = fe.compute(df)
    px_now = float(feats["c"].iloc[-1])
    signal_ts = _last_bar_ts(feats)

    rec.gate("G1_data", True)
    rec.data.update({
        "source": getattr(adapter, "name", asset_class),
        "timeframe": timeframe,
        "bars": len(df),
        "px": px_now,
    })

    # 1. Exit check on any existing position before new entries.
    if open_position is not None:
        # Mark-to-market: keep current price + unrealized P&L fresh each tick so
        # the dashboard shows live P&L on open positions (long-only house book).
        from risk.pnl import unrealized as _unrealized
        open_position.current_px = px_now
        open_position.unrealized_pnl = _unrealized(
            float(open_position.entry_px), float(open_position.qty), px_now,
        )

        # Track high-water mark for trailing-stop ratcheting
        hw = exit_state.get("high_water_px")
        new_hw = max(hw or 0.0, px_now) if open_position.qty > 0 else hw
        exit_state["high_water_px"] = new_hw

        await _maybe_exit(
            session=session,
            position=open_position,
            features=feats,
            px_now=px_now,
            executor=executor,
            exit_state=exit_state,
            signal_ts=signal_ts,
        )

    # 2. Combiner -> SignalResult, persist signal_history row.
    combined = combiner.combine_signals(
        symbol, feats, px_now,
        model_predictions=_model_pred(model, symbol, df),
    )
    result = combine_to_result(combined, model_version=model_version)
    rec.features.update(_snapshot_audit_features(feats))
    rec.features.update({
        "strength": combined.strength,
        "confidence": result.confidence,
        "component_signals": (result.component_weights or {}).get("component_signals", {}),
    })
    rec.signal.update({
        "direction": result.signal,
        "confidence": result.confidence,
        "strength": combined.strength,
        "predicted_return": result.predicted_return,
        "model_version": model_version,
    })
    rec.strategy = (result.component_weights or {}).get("method", "combined")

    session.add(SignalHistory(
        user_id=settings.system_user_id,
        ticker=symbol,
        timeframe=_default_timeframe(asset_class),
        asset_class=asset_class,
        signal=result.signal,
        confidence=result.confidence,
        predicted_return=result.predicted_return,
        model_version=model_version,
        component_weights=result.component_weights,
    ))

    # 3. Entry gate: HOLD / low confidence / already long.
    conf_floor = (
        settings.min_signal_confidence_forex
        if asset_class == "forex"
        else settings.min_signal_confidence
    )
    if result.signal == "HOLD" or result.confidence < conf_floor:
        reasons: list[str] = []
        if result.signal == "HOLD":
            reasons.append("HOLD signal")
        if result.confidence < conf_floor:
            reasons.append(
                f"confidence {result.confidence:.2f} < {conf_floor}",
            )
        rec.gate("G2_signal", False, reasons)
        rec.finalize("skipped")
        logger.info(
            "[%s] %s no-trade signal=%s conf=%.2f", asset_class, symbol, result.signal, result.confidence,
        )
        return
    rec.gate("G2_signal", True)

    if open_position is not None and not open_position.closed and open_position.qty > 0 and result.signal == "BUY":
        rec.gate("G3_position", False, ["already long"]).finalize("skipped")
        return
    rec.gate("G3_position", True)

    # 4. Rebuy cooldown — skip BUY if a SELL on this symbol fired recently.
    if result.signal == "BUY" and _in_cooldown(symbol, recent_sells):
        rec.gate("G4_cooldown", False, ["rebuy cooldown active"]).finalize("skipped")
        logger.info("[%s] %s in rebuy cooldown — skipping BUY", asset_class, symbol)
        return
    rec.gate("G4_cooldown", True)

    # 4b. Kill switch — halt new BUY entries when tripped (exits still flow).
    if result.signal == "BUY" and not _kill_switch.allow_new_entries():
        rec.gate("G5_kill_switch", False, [f"kill switch: {_kill_switch.reason}"]).finalize("skipped")
        logger.warning("[%s] %s BUY blocked — kill switch: %s", asset_class, symbol, _kill_switch.reason)
        return
    rec.gate("G5_kill_switch", True)

    # 5. Size + place order.
    side = Side.BUY if result.signal == "BUY" else Side.SELL

    if side == Side.SELL:
        # Long-only: only sell a position we actually hold.
        if open_position is None or open_position.closed or float(open_position.qty) <= 0:
            rec.gate("G6_sizer", False, ["SELL signal but no open position to exit"]).finalize("skipped")
            logger.info("[%s] %s SELL signal — no open position, skipping", asset_class, symbol)
            return
        sell_qty = float(open_position.qty)
        rec.risk.update({"qty": sell_qty, "notional": sell_qty * px_now, "equity": sizer.equity})
        rec.gate("G6_sizer", True)
        intent = OrderIntent(
            asset_class=asset_class,
            symbol=symbol,
            side=Side.SELL,
            order_type=OrderType.MARKET,
            qty=sell_qty,
            limit_px=px_now,
            time_in_force=TimeInForce.DAY,
            signal_time=signal_ts,
            client_order_id=_client_order_id(asset_class, symbol, "sell", signal_ts),
        )
    else:
        sized = sizer.kelly_optimal(price=px_now, signal=combined.strength)
        rec.risk.update({
            "qty": sized.qty,
            "notional": sized.notional,
            "kelly_fraction": getattr(sized, "kelly_fraction", None),
            "equity": sizer.equity,
        })
        if sized.qty <= 0 or sized.notional <= 0:
            rec.gate("G6_sizer", False, ["sizer returned zero qty"]).finalize("skipped")
            logger.info("[%s] %s sizer returned zero qty", asset_class, symbol)
            return
        rec.gate("G6_sizer", True)
        intent = OrderIntent(
            asset_class=asset_class,
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            qty=sized.qty,
            limit_px=px_now,
            time_in_force=TimeInForce.DAY,
            signal_time=signal_ts,
            client_order_id=_client_order_id(asset_class, symbol, side.value, signal_ts),
        )

    report, affected, skip_reason = await _submit_and_persist(session, executor, intent, open_position)
    if skip_reason == "idempotent":
        rec.gate("G7_idempotent", False, ["already submitted this bar"]).finalize("skipped")
        return
    if skip_reason == "live_blocked":
        from execution.live_guard import block_reason as _block_reason
        blocked = await _block_reason(intent.asset_class, executor)
        rec.gate("G7_live", False, [blocked or "live trading not approved"]).finalize("rejected")
        return
    if report is None:
        rec.finalize("skipped")
        return
    if report.filled_qty <= 0:
        rec.gate("G8_fill", False, ["zero fill"]).finalize("submitted", client_order_id=intent.client_order_id)
        logger.info("[%s] %s zero-fill", asset_class, symbol)
        return

    rec.gate("G8_fill", True)
    rec.finalize(
        "placed",
        client_order_id=intent.client_order_id,
        side=side.value,
        qty=report.filled_qty,
        px=report.avg_fill_price or px_now,
        status=report.order.status.value,
    )

    if side == Side.BUY and affected is not None and not affected.closed:
        await _ensure_exit_state(session, affected.id, seed_high_water=float(affected.entry_px))
    if side == Side.SELL:
        recent_sells[symbol] = datetime.now(timezone.utc)


async def _maybe_exit(
    *,
    session: AsyncSession,
    position: Position,
    features: pd.DataFrame,
    px_now: float,
    executor,
    exit_state: dict,
    signal_ts,
) -> None:
    """Run advanced (or basic) exit logic. Place SELLs, update state."""
    qty = float(position.qty)
    if qty <= 0:
        return

    if settings.use_advanced_exits:
        orders, updated_state, _ = await compute_exit_orders_advanced(
            symbol=position.symbol,
            g=features,
            px_now=px_now,
            pos_qty=qty,
            entry_px=float(position.entry_px),
            entry_time=position.entry_ts,
            current_signal=0.0,
            exit_state={position.symbol: exit_state},
            stop_loss_pct=settings.stop_loss_pct,
            take_profit_pct=settings.take_profit_pct,
            move_stop_to_breakeven=settings.move_stop_to_breakeven,
            trailing_stop_pct=settings.trailing_stop_pct,
            trailing_stop_pct_after_tp=settings.trailing_stop_pct_after_tp,
            trailing_lookback_bars=settings.trailing_lookback_bars,
            max_hold_hours=settings.max_hold_hours,
            exit_on_negative_signal=settings.exit_on_negative_signal,
            signal_exit_threshold=settings.signal_exit_threshold,
        )
        merged_state = updated_state.get(position.symbol, exit_state)
        # preserve the high-water mark we computed above
        merged_state["high_water_px"] = exit_state.get("high_water_px")
    else:
        orders, _, _ = compute_exit_orders(
            symbol=position.symbol,
            g=features,
            px_now=px_now,
            pos_qty=qty,
            entry_px=float(position.entry_px),
            entry_time=position.entry_ts,
            current_signal=0.0,
            exit_state={},
        )
        merged_state = exit_state

    # razorBill exits emit ("sell", qty) tuples
    for i, raw in enumerate(orders):
        if isinstance(raw, tuple) and len(raw) >= 2:
            _side, sell_qty = str(raw[0]), float(raw[1])
        elif isinstance(raw, dict):
            _side = str(raw.get("side", "sell"))
            sell_qty = float(raw.get("qty", qty))
        else:
            continue
        if sell_qty <= 0:
            continue
        intent = OrderIntent(
            asset_class=position.asset_class,
            symbol=position.symbol,
            side=Side.SELL,
            order_type=OrderType.MARKET,
            qty=sell_qty,
            limit_px=px_now,
            time_in_force=TimeInForce.DAY,
            signal_time=signal_ts,
            client_order_id=_client_order_id(position.asset_class, position.symbol, f"exit{i}", signal_ts),
        )
        await _submit_and_persist(session, executor, intent, position)  # exits: no audit record

    # Persist the (possibly updated) ExitState row.
    await _persist_exit_state(session, position.id, merged_state)


# ---------------------------------------------------------------------------
# persistence helpers
# ---------------------------------------------------------------------------

async def _load_open_positions(session: AsyncSession, asset_class: str) -> dict[str, Position]:
    res = await session.execute(
        select(Position).where(Position.asset_class == asset_class).where(Position.closed.is_(False))
    )
    return {row.symbol: row for row in res.scalars().all()}


async def _load_exit_states(
    session: AsyncSession,
    positions: list[Position],
) -> dict[str, dict]:
    """Load ExitState rows for the given positions, keyed by symbol."""
    if not positions:
        return {}
    pos_ids = [p.id for p in positions]
    res = await session.execute(select(ExitState).where(ExitState.position_id.in_(pos_ids)))
    by_pid = {row.position_id: row for row in res.scalars().all()}
    out: dict[str, dict] = {}
    for p in positions:
        out[p.symbol] = _exit_state_to_dict(by_pid.get(p.id), high_water_seed=float(p.entry_px))
    return out


async def _ensure_exit_state(session: AsyncSession, position_id, seed_high_water: float) -> None:
    res = await session.execute(select(ExitState).where(ExitState.position_id == position_id))
    if res.scalar_one_or_none() is not None:
        return
    session.add(ExitState(position_id=position_id, high_water_px=seed_high_water))


async def _persist_exit_state(session: AsyncSession, position_id, state: dict) -> None:
    res = await session.execute(select(ExitState).where(ExitState.position_id == position_id))
    es = res.scalar_one_or_none()
    if es is None:
        es = ExitState(position_id=position_id)
        session.add(es)
    _apply_state_to_es(es, state)


async def _load_recent_sells(session: AsyncSession, asset_class: str) -> dict[str, datetime]:
    """Most-recent SELL ts per symbol within the rebuy cooldown window."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.rebuy_cooldown_min)
    res = await session.execute(
        select(Order.symbol, Order.ts)
        .where(Order.asset_class == asset_class)
        .where(Order.side == "sell")
        .where(Order.ts >= cutoff)
        .order_by(Order.ts.desc())
    )
    out: dict[str, datetime] = {}
    for sym, ts in res.all():
        if sym not in out:
            out[sym] = ts
    return out


def _in_cooldown(symbol: str, recent_sells: dict[str, datetime]) -> bool:
    last = recent_sells.get(symbol)
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last).total_seconds() / 60.0
    return age < settings.rebuy_cooldown_min


def _resolve_model(asset_class: str, version: Optional[str] = None):
    """Load the best trained model for *asset_class* from the registry, or None.

    Wraps the import so a missing / corrupt artifact degrades gracefully to
    pure technical-strategy signals rather than crashing the tick."""
    try:
        from ml.models.registry import resolve
        return resolve(asset_class, version)
    except Exception:
        logger.warning("model registry unavailable for %s", asset_class, exc_info=True)
        return None


async def _resolve_champion_model(session: AsyncSession, asset_class: str):
    """Resolve (model, version) for the human-approved champion, if any.

    Reads the active version from model_champions (DB-backed so it's shared
    across the Fly worker and the local options worker); falls back to
    settings.model_version when no champion has been promoted. The returned
    version tags signal_history so outcomes can later be attributed per version."""
    version = settings.model_version
    try:
        from ml.promotion import get_champion_version
        champ = await get_champion_version(session, asset_class)
        if champ:
            version = champ
    except Exception:
        logger.debug("champion lookup failed for %s — using default version", asset_class, exc_info=True)

    model = _resolve_model(asset_class, version)
    # A model object carries its own version label; prefer it when present.
    resolved_version = getattr(model, "model_version", None) or version
    return model, resolved_version


_TRANSIENT_MARKERS = (
    "timeout", "timed out", "connection", "temporarily", "rate limit",
    "429", "500", "502", "503", "504", "unavailable", "reset", "try again",
)


def _is_transient(reason: Optional[str]) -> bool:
    if not reason:
        return False
    low = reason.lower()
    return any(m in low for m in _TRANSIENT_MARKERS)


async def _place_with_retry(executor, intent: OrderIntent) -> ExecutionReport:
    """Place an order with bounded exponential backoff on transient failures.

    Safe to retry: OrderIntent's deterministic client_order_id makes
    re-submission idempotent at the broker. Only transient errors (network /
    timeout / 5xx / rate-limit) are retried — hard rejections return immediately.
    Executors return a REJECTED report rather than raising, so we inspect both
    the report and any raised exception."""
    attempts = max(0, settings.executor_max_retries) + 1
    base = settings.executor_retry_base_delay
    report: Optional[ExecutionReport] = None
    for i in range(attempts):
        try:
            report = await executor.place(intent)
        except Exception as exc:
            if i + 1 < attempts:
                delay = base * (2 ** i)
                logger.warning("[%s] %s place() raised %s — retry %d/%d in %.1fs",
                               intent.asset_class, intent.symbol, exc, i + 1, attempts - 1, delay)
                await asyncio.sleep(delay)
                continue
            raise
        rejected = report.order.status == OrderStatus.REJECTED
        if rejected and _is_transient(report.order.rejected_reason) and i + 1 < attempts:
            delay = base * (2 ** i)
            logger.warning("[%s] %s transient reject (%s) — retry %d/%d in %.1fs",
                           intent.asset_class, intent.symbol, report.order.rejected_reason,
                           i + 1, attempts - 1, delay)
            await asyncio.sleep(delay)
            continue
        return report
    return report  # type: ignore[return-value]


async def _resolve_equity(executor, equity: Optional[float]) -> float:
    """Resolve sizing equity: explicit arg → live account balance → default."""
    if equity is not None:
        return float(equity)
    try:
        live = await executor.get_account_equity()
    except Exception:
        logger.warning("get_account_equity failed — using default", exc_info=True)
        live = None
    if live is not None and live > 0:
        return float(live)
    return float(settings.default_equity)


def _model_pred(model, symbol: str, df: pd.DataFrame) -> dict[str, float]:
    """Return {symbol: predicted_return} for MLStrategy; {} when no model.

    Registry models (e.g. EnsembleSignalModel) are trained on
    ml.features.build_features columns, which differ from FeatureEngineer's
    output — so build the model's own feature frame from the raw OHLCV df
    (the same path ml.pipeline / ml.inference use). Empty dict is the no-op:
    combine_signals then skips MLStrategy's model_predictions path and the
    blend is technical-only."""
    if model is None or df.empty:
        return {}
    try:
        from ml.features import build_features
        model_feats = build_features(df)
        if model_feats.empty:
            return {}
        result = model.predict(model_feats)
        return {symbol: float(result.predicted_return)}
    except Exception:
        logger.debug("model.predict failed for %s", symbol, exc_info=True)
        return {}


async def _submit_and_persist(
    session: AsyncSession,
    executor,
    intent: OrderIntent,
    position: Optional[Position],
) -> tuple[Optional[ExecutionReport], Optional[Position], Optional[str]]:
    """Idempotency-check, submit, persist one Order row per intent, and apply
    the aggregate fill to the position. Returns (report, affected_position, skip_reason).
    skip_reason is set when the order was not submitted (idempotent | live_blocked)."""
    if intent.client_order_id:
        existing = await already_submitted(session, intent.client_order_id)
        if existing is not None:
            logger.info(
                "[%s] %s idempotent skip (client_order_id=%s)",
                intent.asset_class, intent.symbol, intent.client_order_id,
            )
            return None, position, "idempotent"

    # Live-trading approval gate: a real-money order is blocked until a human
    # approves the session (POST /execution/approve_live). Paper is never gated.
    from execution.live_guard import block_reason
    blocked = await block_reason(intent.asset_class, executor)
    if blocked is not None:
        logger.error("[%s] %s %s", intent.asset_class, intent.symbol, blocked)
        return None, position, "live_blocked"

    report = await _place_with_retry(executor, intent)
    filled_qty = report.filled_qty
    avg_px = report.avg_fill_price or intent.limit_px or 0.0
    fee = sum(f.commission for f in report.fills)
    slippage_bps = next((f.slippage_bps for f in report.fills if f.slippage_bps is not None), None)

    session.add(Order(
        asset_class=intent.asset_class,
        symbol=intent.symbol,
        ts=datetime.now(timezone.utc),
        side=intent.side.value,
        qty=filled_qty,
        px=avg_px,
        fee=fee,
        slippage_bps=slippage_bps,
        executor=getattr(executor, "name", "unknown"),
        external_id=report.order.order_id,
        client_order_id=intent.client_order_id,
        order_type=intent.order_type.value,
        time_in_force=intent.time_in_force.value,
        limit_px=intent.limit_px,
        stop_px=intent.stop_px,
        status=report.order.status.value,
        raw=(report.fills[0].metadata if report.fills else None),
        meta={"intent_qty": float(intent.qty) if intent.qty else None,
              "rejected_reason": getattr(report.order, "rejected_reason", None)},
    ))

    if filled_qty <= 0:
        return report, position, None

    affected = await _apply_fill_to_position(
        session,
        asset_class=intent.asset_class,
        symbol=intent.symbol,
        side=intent.side,
        qty=filled_qty,
        price=avg_px,
        existing=position,
    )
    return report, affected, None


async def _apply_fill_to_position(
    session: AsyncSession,
    *,
    asset_class: str,
    symbol: str,
    side: Side,
    qty: float,
    price: float,
    existing: Optional[Position],
) -> Optional[Position]:
    """Mutate Position to reflect an aggregate fill. Returns the affected
    Position (newly opened or existing) so callers can seed dependent rows."""
    now = datetime.now(timezone.utc)
    if side == Side.BUY:
        if existing is None or existing.closed:
            new_pos = Position(
                asset_class=asset_class,
                symbol=symbol,
                qty=qty,
                entry_px=price,
                entry_ts=now,
                current_px=price,
            )
            session.add(new_pos)
            await session.flush()  # populates new_pos.id for ExitState seeding
            return new_pos
        new_qty = float(existing.qty) + qty
        existing.entry_px = (
            float(existing.entry_px) * float(existing.qty) + price * qty
        ) / max(new_qty, 1e-12)
        existing.qty = new_qty
        existing.current_px = price
        existing.updated_at = now
        return existing

    # sell
    if existing is None:
        return None
    remaining = float(existing.qty) - qty
    existing.realized_pnl = float(existing.realized_pnl) + (price - float(existing.entry_px)) * qty
    if remaining <= 1e-9:
        existing.qty = 0.0
        existing.closed = True
        existing.closed_at = now
    else:
        existing.qty = remaining
        existing.current_px = price
    return existing


def _client_order_id(asset_class: str, symbol: str, tag: str, signal_ts) -> str:
    """Deterministic idempotency key: collapses retries within the same bar to
    one order, but a new bar (new signal_ts) yields a new key."""
    bucket = int(pd.Timestamp(signal_ts).timestamp()) if signal_ts is not None else 0
    return f"{asset_class}:{symbol}:{tag}:{bucket}"


def _last_bar_ts(feats: pd.DataFrame):
    try:
        return feats.index[-1]
    except Exception:
        return None


def _default_timeframe(asset_class: str) -> str:
    if asset_class == "crypto":
        return "5m"
    if asset_class == "forex":
        return "4h"
    return "daily"


async def reconcile_alpaca_positions() -> int:
    """Sync Alpaca broker positions into the DB.

    Catches the case where an order filled at Alpaca but our _poll_fill timed
    out before the fill landed, leaving status=submitted / qty=0 in the DB
    with no Position row. Returns the number of positions created or updated.
    """
    try:
        from execution.alpaca import AlpacaExecutor
        executor = AlpacaExecutor()
    except Exception:
        logger.warning("[reconcile] AlpacaExecutor unavailable — skipping", exc_info=True)
        return 0

    loop = asyncio.get_event_loop()
    try:
        broker_positions = await loop.run_in_executor(None, executor._client.get_all_positions)
    except Exception:
        logger.exception("[reconcile] get_all_positions failed")
        return 0

    patched = 0
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        for bp in broker_positions:
            symbol = str(bp.symbol)
            broker_qty = float(getattr(bp, "qty", 0) or 0)
            broker_px = float(getattr(bp, "avg_entry_price", 0) or 0)
            broker_cur = float(getattr(bp, "current_price", broker_px) or broker_px)
            if broker_qty <= 0:
                continue

            res = await session.execute(
                select(Position)
                .where(Position.asset_class == "equity")
                .where(Position.symbol == symbol)
                .where(Position.closed.is_(False))
            )
            db_pos = res.scalar_one_or_none()

            if db_pos is None:
                logger.info("[reconcile] creating missing position %s qty=%.4f px=%.4f",
                            symbol, broker_qty, broker_px)
                session.add(Position(
                    asset_class="equity",
                    symbol=symbol,
                    qty=broker_qty,
                    entry_px=broker_px,
                    entry_ts=now,
                    current_px=broker_cur,
                    unrealized_pnl=(broker_cur - broker_px) * broker_qty,
                ))
                patched += 1
            elif abs(float(db_pos.qty) - broker_qty) > 1e-4:
                logger.info("[reconcile] correcting %s qty %.4f → %.4f",
                            symbol, float(db_pos.qty), broker_qty)
                db_pos.qty = broker_qty
                db_pos.current_px = broker_cur
                db_pos.updated_at = now
                patched += 1

        # Mark submitted equity orders as filled when Alpaca confirms them.
        res = await session.execute(
            select(Order)
            .where(Order.asset_class == "equity")
            .where(Order.status == "submitted")
            .where(Order.executor == "alpaca")
        )
        stuck_orders = res.scalars().all()
        for o in stuck_orders:
            if not o.external_id:
                continue
            try:
                filled = await loop.run_in_executor(
                    None, lambda oid=o.external_id: executor._client.get_order_by_id(oid)
                )
                status = str(getattr(filled, "status", "")).lower()
                fqty = float(getattr(filled, "filled_qty", 0) or 0)
                fpx = float(getattr(filled, "filled_avg_price", 0) or 0)
                if "filled" in status and fqty > 0:
                    logger.info("[reconcile] updating stuck order %s %s qty=%.4f px=%.4f",
                                o.symbol, o.external_id, fqty, fpx)
                    o.qty = fqty
                    o.px = fpx
                    o.status = "filled"
                    patched += 1
            except Exception:
                logger.debug("[reconcile] order lookup failed %s", o.external_id, exc_info=True)

        await session.commit()

    logger.info("[reconcile] done — %d positions/orders patched", patched)
    return patched
