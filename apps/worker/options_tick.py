"""Options worker tick — one full chain-based cycle for the option asset class.

Pipeline (per underlying):
  1. Fetch underlying OHLCV (MoomooAdapter) and compute features
  2. RegimeDetector.fit → detect regime
  3. Signal combiner → underlying directional strength
  4. Fetch option chain via MoomooOptionData → expiries → nearest expiry chain
  5. select_candidates → ranked OptionStructure list
  6. Five validation gates (G1–G5) on the top candidate
  7. option_position_size → contracts
  8. MoomooExecutor.place (paper) → ExecutionReport
  9. Persist Order (with option metadata) + audit record

This is intentionally parallel to worker.tick (OHLCV-based) rather than
calling it — option chains have a different shape (per-expiry, multi-leg)
that doesn't fit the per-symbol OHLCV loop. Equity/crypto Fly worker is
untouched; this loop runs where OpenD is reachable (local or VPS lab).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.connection import AsyncSessionLocal
from db.models import Order, Position
from execution import get_executor
from execution.base import ExecutionReport, OrderIntent, OrderStatus, OrderType, Side, TimeInForce
from execution.idempotency import already_submitted
from markets import get_market_adapter
from markets.options import MoomooOptionData, OptionContract, OptionQuote
from ml.regime import Regime, RegimeDetector
from ml.sequences import FeatureEngineer
from ml.strategies import build_default_combiner, combine_to_result
from options import select_candidates
from options_math import LiquidityFilters, realized_vol, iv_rank
from risk.audit_log import AuditLog, AuditRecord
from risk.greeks import GreekLimits, GreekExposure, aggregate_greeks, check_greek_limits
from risk.kill_switch import KillSwitch, HaltThresholds, evaluate_halt
from risk.option_sizing import option_position_size
from universe import get_universe_selector

logger = logging.getLogger(__name__)

# Module-level kill switch and audit log survive across ticks in the same process.
_kill_switch = KillSwitch()
_halt_thresholds = HaltThresholds()


async def options_tick_once(equity: Optional[float] = None) -> None:
    """Run one options cycle. Selects underlyings → chains → gates → place."""
    adapter = get_market_adapter("option")
    if not adapter.is_market_open():
        logger.info("[option] market closed — skipping tick")
        return

    selector = get_universe_selector("option")
    underlyings = selector.select()
    logger.info("[option] tick: %d underlyings", len(underlyings))

    executor = get_executor("option")
    fe = FeatureEngineer()
    equity = await _resolve_equity(executor, equity)
    logger.info("[option] sizing equity = %.2f", equity)

    option_data = MoomooOptionData()
    audit_log = AuditLog()

    async with AsyncSessionLocal() as session:
        # Mark-to-market + settle/time-stop held option positions before opening
        # new ones, so the dashboard shows live option P&L and positions close.
        try:
            await _manage_open_positions(session, adapter)
        except Exception:
            logger.exception("[option] position management failed")

        for underlying in underlyings:
            try:
                await _process_underlying(
                    session=session,
                    underlying=underlying,
                    adapter=adapter,
                    fe=fe,
                    option_data=option_data,
                    executor=executor,
                    equity=equity,
                    audit_log=audit_log,
                )
            except Exception:
                logger.exception("[option] %s tick failed", underlying)

        # Persist the full decision provenance (best-effort — never break the tick).
        try:
            from db.audit_store import persist_audit_log
            n = await persist_audit_log(session, audit_log)
            logger.info("[option] persisted %d audit records", n)
        except Exception:
            logger.exception("[option] audit persist failed")

        await session.commit()


async def _manage_open_positions(session: AsyncSession, adapter) -> None:
    """Mark-to-market, then exit (settle/stop/take-profit/trailing/time-stop) each
    open option position.

    Reuses sim/options/lifecycle.manage_position. Theoretical valuation off the
    underlying spot + entry IV avoids needing the broker-native contract code
    (which isn't persisted). Closes book realized P&L + a settlement Order; the
    trailing high-water mark persists in Position.meta between ticks."""
    from sim.options.lifecycle import manage_position

    res = await session.execute(
        select(Position).where(Position.asset_class == "option").where(Position.closed.is_(False))
    )
    positions = list(res.scalars().all())
    if not positions:
        return

    now = datetime.now(timezone.utc)
    bars_cache: dict[str, Optional[pd.DataFrame]] = {}

    for pos in positions:
        if not pos.underlying or pos.expiry is None or pos.strike is None or not pos.right:
            continue
        df = _underlying_bars(adapter, pos.underlying, bars_cache)
        if df is None or df.empty:
            continue
        spot = float(df["close"].iloc[-1])

        T = max(0.0, (pos.expiry - now.date()).days / 365.0)
        sigma = _entry_iv(pos)
        hold_days = max(0, (now - _aware(pos.entry_ts)).days)
        meta = dict(pos.meta or {})
        external = _external_exit_reason(df, pos.right)

        action = manage_position(
            entry_price=float(pos.entry_px), qty=float(pos.qty), right=pos.right,
            strike=float(pos.strike), spot=spot, T=T, sigma=sigma,
            hold_days=hold_days, max_hold_days=settings.option_max_hold_days,
            multiplier=int(pos.multiplier or 100),
            commission_per_contract=settings.option_commission_per_contract,
            high_water_value=meta.get("hw_value"),
            stop_loss_pct=settings.option_stop_loss_pct,
            take_profit_pct=settings.option_take_profit_pct,
            trailing_pct=settings.option_trailing_pct,
            trailing_activate_pct=settings.option_trailing_activate_pct,
            external_exit=external,
        )

        pos.current_px = round(action.current_px, 6)
        if action.closes:
            pos.realized_pnl = float(pos.realized_pnl) + action.realized_pnl
            pos.unrealized_pnl = 0.0
            pos.qty = 0.0
            pos.closed = True
            pos.closed_at = now
            session.add(Order(
                asset_class="option", symbol=pos.symbol, side="sell",
                qty=0.0, px=round(action.current_px, 6), fee=action.commission,
                executor="lifecycle", status="filled",
                order_type="market", time_in_force="day",
                underlying=pos.underlying, expiry=pos.expiry, strike=pos.strike,
                right=pos.right, multiplier=pos.multiplier,
                meta={"event": "close", "outcome": action.outcome,
                      "realized_pnl": action.realized_pnl},
            ))
            logger.info("[option] %s closed (%s) realized=%.2f",
                        pos.symbol, action.outcome, action.realized_pnl)
        else:
            pos.unrealized_pnl = round(action.unrealized_pnl, 6)
            # Persist the trailing high-water mark for the next tick (reassign a
            # new dict so SQLAlchemy flags the JSONB column dirty).
            meta["hw_value"] = round(action.high_water_value, 6)
            pos.meta = meta


def _underlying_bars(adapter, underlying: str, cache: dict):
    """Underlying OHLCV df (cached per tick). spot = last close; the bars also
    drive the ATR/vol/trend exits."""
    if underlying in cache:
        return cache[underlying]
    df = None
    try:
        out = adapter.fetch_ohlcv(underlying, "daily")
        if out is not None and not out.empty:
            df = out
    except Exception:
        logger.debug("[option] bars fetch failed for %s", underlying, exc_info=True)
    cache[underlying] = df
    return df


def _atr(df: "pd.DataFrame", n: int) -> float:
    """Average true range over the last n bars (Wilder-style simple mean)."""
    h, low, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - low), (h - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.tail(n).mean()
    return float(atr) if atr == atr else 0.0   # NaN-safe


def _external_exit_reason(df: "pd.DataFrame", right: str) -> Optional[str]:
    """Underlying-derived exit reason (ATR-trailing / vol-regime / trend-reversal),
    direction-aware for the option's thesis. Pure. None when no toggle fires.

    A long call's thesis is bullish (exit when the underlying turns down); a long
    put's is bearish (exit when it turns up). vol-regime is symmetric (long vega)."""
    lookback = settings.option_exit_lookback_bars
    closes = df["close"]
    if len(closes) < 2 * lookback + 2:
        return None
    last = float(closes.iloc[-1])
    bullish = right == "call"

    if settings.option_use_atr_trailing:
        atr = _atr(df, lookback)
        if atr > 0:
            if bullish:
                stop = float(df["high"].tail(lookback).max()) - atr * settings.option_atr_multiplier
                if last <= stop:
                    return "atr_stop"
            else:
                stop = float(df["low"].tail(lookback).min()) + atr * settings.option_atr_multiplier
                if last >= stop:
                    return "atr_stop"

    if settings.option_use_vol_regime_exit:
        recent = realized_vol(closes.tail(lookback).tolist())
        base = realized_vol(closes.iloc[-(2 * lookback):-lookback].tolist())
        if base > 0 and recent / base >= settings.option_vol_spike_mult:
            return "vol_regime"

    if settings.option_use_trend_reversal:
        short = float(closes.tail(5).mean())
        prior = float(closes.iloc[-10:-5].mean())
        if bullish and short < prior and last < prior:
            return "trend_reversal"
        if (not bullish) and short > prior and last > prior:
            return "trend_reversal"

    return None


def _entry_iv(pos) -> float:
    """Entry implied vol from the position meta, else a 0.30 fallback."""
    try:
        iv = (pos.meta or {}).get("iv_rank")  # informational; rank ≠ level
        rationale = (pos.meta or {}).get("rationale", {})
        sigma = rationale.get("entry_iv") or pos.meta.get("entry_iv") if pos.meta else None
        if sigma and float(sigma) > 0:
            s = float(sigma)
            return s / 100.0 if s > 3 else s
    except (AttributeError, TypeError, ValueError):
        pass
    return 0.30


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# per-underlying logic
# ---------------------------------------------------------------------------

async def _process_underlying(
    *,
    session: AsyncSession,
    underlying: str,
    adapter,
    fe: FeatureEngineer,
    option_data: MoomooOptionData,
    executor,
    equity: float,
    audit_log: AuditLog,
) -> None:
    rec = audit_log.new(underlying)

    # ── 1. Underlying candles + features ─────────────────────────────────────
    try:
        df = adapter.fetch_ohlcv(underlying, "daily")
    except Exception as exc:
        logger.warning("[option] %s candle fetch failed: %s", underlying, exc)
        rec.gate("G1_data", False, [f"candle fetch failed: {exc}"])
        rec.finalize("skipped")
        return

    if df.empty or len(df) < 30:
        rec.gate("G1_data", False, ["insufficient price history"])
        rec.finalize("skipped")
        return

    feats = fe.compute(df)
    spot = float(feats["c"].iloc[-1]) if "c" in feats.columns else float(df["close"].iloc[-1])
    prices = df["close"].astype(float).tolist()

    rec.data.update({"underlying": underlying, "spot": spot, "bars": len(df)})

    # ── 2. Regime ─────────────────────────────────────────────────────────────
    try:
        regime_result = RegimeDetector().fit(prices).label_latest()
        regime = regime_result.regime
    except Exception:
        regime = Regime.UNKNOWN

    # ── 3. Signal + IV rank ───────────────────────────────────────────────────
    combiner = build_default_combiner("equity")
    combined = combiner.combine_signals(underlying, feats, spot, model_predictions={})
    result = combine_to_result(combined)

    rv = realized_vol(prices[-60:]) if len(prices) >= 60 else realized_vol(prices)
    iv_rank_val = iv_rank(rv, prices[-252:]) if len(prices) >= 252 else 0.5

    rec.features.update({
        "regime": regime.value,
        "signal": result.signal,
        "confidence": result.confidence,
        "strength": combined.strength,
        "iv_rank": iv_rank_val,
        "realized_vol": rv,
    })
    rec.signal.update({
        "direction": result.signal,
        "confidence": result.confidence,
        "strength": combined.strength,
        "model_version": result.model_version,
    })

    # ── 4. Option chain ───────────────────────────────────────────────────────
    expiries = option_data.list_expiries(underlying)
    expiry = _nearest_expiry(expiries)
    if expiry is None:
        rec.gate("G1_data", False, ["no expiries available"])
        rec.finalize("skipped")
        return

    chain_contracts = option_data.get_chain(underlying, expiry)
    if not chain_contracts:
        rec.gate("G1_data", False, ["empty chain"])
        rec.finalize("skipped")
        return

    chain_quotes = option_data.get_quotes(chain_contracts)
    if not chain_quotes:
        rec.gate("G1_data", False, ["no quotes returned"])
        rec.finalize("skipped")
        return

    T = max(0.001, (expiry - date.today()).days / 365.0)

    # G1 — data quality gate
    g1_ok, g1_reasons = _gate_data(chain_quotes, spot)
    rec.gate("G1_data", g1_ok, g1_reasons)
    if not g1_ok:
        rec.finalize("skipped")
        return

    # ── 5. Candidate selection ────────────────────────────────────────────────
    filters = LiquidityFilters(
        max_spread_pct=settings.option_max_spread_pct,
        min_volume=settings.option_min_volume,
        min_open_interest=settings.option_min_open_interest,
    )
    candidates = select_candidates(
        chain=chain_quotes,
        spot=spot,
        strength=combined.strength,
        regime=regime,
        iv_rank=iv_rank_val,
        T=T,
        r=0.05,
        filters=filters,
    )

    if not candidates:
        rec.gate("G2_signal", False, ["no candidates passed liquidity filters"])
        rec.finalize("skipped")
        return

    top = candidates[0]

    # G2 — signal quality gate
    g2_ok, g2_reasons = _gate_signal(result.confidence, regime, top.score)
    rec.gate("G2_signal", g2_ok, g2_reasons)
    if not g2_ok:
        rec.finalize("skipped")
        return

    rec.strategy = top.strategy

    # G3 — risk gate (portfolio Greeks + sizing budget)
    max_loss = top.structure.max_loss
    size = option_position_size(
        equity=equity,
        max_loss_per_contract=max_loss,
        risk_per_trade=settings.option_risk_per_trade,
        max_contracts=settings.option_max_contracts,
    )
    greek_limits = GreekLimits(
        max_abs_net_delta=settings.option_max_net_delta,
        max_abs_net_gamma=settings.option_max_net_gamma,
        max_abs_net_vega=settings.option_max_net_vega,
    )
    net = aggregate_greeks([
        {"greeks": top.structure.net_greeks, "qty": size.contracts, "multiplier": 100}
    ])
    greeks_ok, greek_reasons = check_greek_limits(net, greek_limits)
    g3_ok = size.contracts >= 1 and greeks_ok
    g3_reasons: list[str] = []
    if size.contracts < 1:
        g3_reasons.append(f"size={size.contracts} contracts (binding: {size.binding})")
    g3_reasons.extend(greek_reasons)
    rec.gate("G3_risk", g3_ok, g3_reasons)
    rec.risk.update({
        "contracts": size.contracts,
        "risk_budget": size.risk_budget,
        "max_loss": max_loss,
        "binding": size.binding,
        "net_greeks": net.as_dict(),
    })
    if not g3_ok:
        rec.finalize("skipped")
        return

    # G4 — simulation gate (structural sanity on the selected structure)
    g4_ok, g4_reasons = _gate_simulation(top)
    rec.gate("G4_simulation", g4_ok, g4_reasons)
    if not g4_ok:
        rec.finalize("skipped")
        return

    # G5 — execution gate (kill switch + spread + contract tradable)
    halt, halt_reasons = evaluate_halt(
        equity=equity,
        starting_equity=equity,
        daily_pnl=0.0,
        peak_equity=equity,
        thresholds=_halt_thresholds,
        data_ok=True,
    )
    if halt:
        for r_ in halt_reasons:
            _kill_switch.trip(r_)

    lead_leg = top.structure.legs[0]
    spread_ok = (lead_leg.quote.ask - lead_leg.quote.bid) / max(lead_leg.quote.mid, 1e-6) <= settings.option_max_spread_pct
    g5_ok = _kill_switch.allow_new_entries() and spread_ok
    g5_reasons: list[str] = []
    if not _kill_switch.allow_new_entries():
        g5_reasons.append(f"kill switch: {_kill_switch.reason}")
    if not spread_ok:
        g5_reasons.append("lead leg spread too wide for fill")
    rec.gate("G5_execution", g5_ok, g5_reasons)
    if not g5_ok:
        rec.finalize("skipped")
        return

    # ── 6. Place (paper) order ────────────────────────────────────────────────
    # Use the lead leg's broker code as the order symbol; size = contracts.
    lead_q = lead_leg.quote
    occ = lead_q.contract.occ
    signal_ts = _last_bar_ts(feats)
    client_oid = f"option:{underlying}:{top.strategy}:{_bucket(signal_ts)}"

    existing = await already_submitted(session, client_oid)
    if existing is not None:
        logger.info("[option] %s idempotent skip (client_order_id=%s)", underlying, client_oid)
        rec.finalize("skipped", reason="idempotent")
        return

    intent = OrderIntent(
        asset_class="option",
        symbol=lead_q.contract.code,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=float(size.contracts),
        limit_px=lead_q.mid,
        time_in_force=TimeInForce.DAY,
        signal_time=signal_ts,
        client_order_id=client_oid,
    )

    try:
        report = await executor.place(intent)
    except Exception as exc:
        logger.exception("[option] %s place() raised", underlying)
        rec.finalize("rejected", error=str(exc))
        return

    filled = report.filled_qty
    avg_px = report.avg_fill_price or lead_q.mid
    fee = sum(f.commission for f in report.fills)

    # Persist the order row with option metadata.
    session.add(Order(
        asset_class="option",
        symbol=occ,
        side="buy",
        qty=filled if filled > 0 else float(size.contracts),
        px=avg_px,
        fee=fee,
        slippage_bps=next((f.slippage_bps for f in report.fills if f.slippage_bps is not None), None),
        executor=getattr(executor, "name", "unknown"),
        external_id=report.order.order_id,
        client_order_id=client_oid,
        order_type="limit",
        time_in_force="day",
        limit_px=lead_q.mid,
        status=report.order.status.value,
        underlying=underlying,
        expiry=lead_q.contract.expiry,
        strike=lead_q.contract.strike,
        right=lead_q.contract.right,
        multiplier=lead_q.contract.multiplier,
        meta={
            "strategy": top.strategy,
            "score": top.score,
            "regime": regime.value,
            "iv_rank": iv_rank_val,
            "net_greeks": net.as_dict(),
            "rationale": top.rationale,
            "audit_ts": rec.ts,
        },
    ))

    if filled > 0:
        session.add(Position(
            asset_class="option",
            symbol=occ,
            qty=filled,
            entry_px=avg_px,
            current_px=avg_px,
            underlying=underlying,
            expiry=lead_q.contract.expiry,
            strike=lead_q.contract.strike,
            right=lead_q.contract.right,
            multiplier=lead_q.contract.multiplier,
            meta={"strategy": top.strategy, "legs": len(top.structure.legs)},
        ))

    decision = "placed" if report.order.status == OrderStatus.FILLED else "submitted"
    rec.finalize(
        decision,
        client_order_id=client_oid,
        qty=filled,
        px=avg_px,
        strategy=top.strategy,
        contracts=size.contracts,
    )
    logger.info(
        "[option] %s %s %s x%d @ %.4f (score=%.3f regime=%s)",
        underlying, decision, top.strategy, size.contracts, avg_px, top.score, regime.value,
    )


# ---------------------------------------------------------------------------
# gate helpers (pure — testable without DB or SDK)
# ---------------------------------------------------------------------------

def _gate_data(chain: list[OptionQuote], spot: float) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if spot <= 0:
        reasons.append("spot price unavailable or zero")
    if not chain:
        reasons.append("empty chain")
        return False, reasons
    valid = [q for q in chain if q.bid > 0 and q.ask > 0]
    if len(valid) < 2:
        reasons.append(f"only {len(valid)} quotes with usable bid/ask")
    return (len(reasons) == 0, reasons)


def _gate_signal(confidence: float, regime: Regime, score: float) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if confidence < settings.min_signal_confidence:
        reasons.append(f"confidence {confidence:.2f} < {settings.min_signal_confidence}")
    if regime == Regime.UNKNOWN:
        reasons.append("regime unknown — insufficient price history")
    if score <= 0:
        reasons.append(f"top candidate score {score:.3f} <= 0")
    return (len(reasons) == 0, reasons)


def _gate_simulation(candidate) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    s = candidate.structure
    if s.max_loss <= 0 or s.max_loss == float("inf"):
        reasons.append(f"max_loss={s.max_loss} is not a finite positive number")
    if not s.legs:
        reasons.append("structure has no legs")
    if s.net_debit > s.max_loss * 10:
        reasons.append("net_debit grossly exceeds max_loss — degenerate structure")
    return (len(reasons) == 0, reasons)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _nearest_expiry(expiries: list[date], min_dte: int = 14, max_dte: int = 60) -> Optional[date]:
    """Pick the nearest expiry in [min_dte, max_dte] days from today."""
    today = date.today()
    candidates = [
        e for e in expiries
        if min_dte <= (e - today).days <= max_dte
    ]
    return min(candidates) if candidates else None


def _last_bar_ts(feats: pd.DataFrame):
    try:
        return feats.index[-1]
    except Exception:
        return None


def _bucket(signal_ts) -> int:
    try:
        return int(pd.Timestamp(signal_ts).timestamp())
    except Exception:
        return 0


async def _resolve_equity(executor, equity: Optional[float]) -> float:
    if equity is not None:
        return float(equity)
    try:
        live = await executor.get_account_equity()
    except Exception:
        logger.warning("[option] get_account_equity failed — using default", exc_info=True)
        live = None
    if live is not None and live > 0:
        return float(live)
    return float(settings.default_equity)
