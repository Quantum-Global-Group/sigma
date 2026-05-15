from __future__ import annotations

from typing import Dict, List, Tuple
from datetime import datetime, timezone

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def compute_exit_orders(
    symbol: str,
    g: pd.DataFrame,
    px_now: float,
    pos_qty: float,
    entry_px: float,
    exit_state: Dict[str, dict],
    *,
    stop_loss_pct: float,
    take_profit_pct: float,
    move_stop_to_breakeven: bool,
    trailing_stop_pct: float,
    trailing_stop_pct_after_tp: float,
    trailing_lookback_bars: int,
) -> Tuple[List[Tuple[str, float]], Dict[str, dict], bool]:
    """
    Return a list of (side, qty) exit orders for the symbol, the updated exit_state, and a flag
    indicating that a full exit happened (consume symbol this cycle).
    """
    orders: List[Tuple[str, float]] = []
    state = dict(exit_state.get(symbol, {}))
    consumed = False

    # ADD DEBUG LOGGING HERE
    logger.info(f"🔍 Exit check for {symbol}: pos_qty={pos_qty}, entry_px={entry_px}, px_now={px_now}")

    if abs(pos_qty) <= 1e-9 or entry_px <= 0:
        logger.warning(f"❌ Invalid position data for {symbol}: qty={pos_qty}, entry_px={entry_px}")
        return orders, exit_state, False

    # Trailing context
    look = max(10, int(trailing_lookback_bars))
    g_tail = g.tail(look)
    high_n = float(g_tail["h"].max()) if not g_tail.empty else px_now
    # Long-only logic (shorts not used in spot)
    if pos_qty > 0:
        long_stop = entry_px * (1.0 - float(stop_loss_pct))
        long_tp = entry_px * (1.0 + float(take_profit_pct))

        # ADD MORE DEBUG LOGGING
        logger.info(f"📊 {symbol} levels: Stop={long_stop:.4f}, TP={long_tp:.4f}, Current={px_now:.4f}")
        logger.info(f"🎯 {symbol} triggers: Stop={px_now <= long_stop}, TP={px_now >= long_tp}")

        # Partial TP
        took_partial = bool(state.get("took_partial", False))
        if px_now >= long_tp and not took_partial:
            logger.info(f"💰 TAKE PROFIT TRIGGERED for {symbol}: {px_now:.4f} >= {long_tp:.4f}")
            # Caller decides fraction; we record tighter trailing and breakeven intent here
            state["took_partial"] = True
            if move_stop_to_breakeven:
                state["breakeven_px"] = entry_px
            state["tight_trailing"] = float(trailing_stop_pct_after_tp)

        # Stop floor = max(SL, breakeven if set after partial)
        stop_floor = long_stop
        if "breakeven_px" in state and state["breakeven_px"] is not None:
            try:
                stop_floor = max(stop_floor, float(state["breakeven_px"]))
            except Exception:
                pass
        if px_now <= stop_floor:
            # Full exit
            logger.warning(f"🛑 STOP LOSS TRIGGERED for {symbol}: {px_now:.4f} <= {stop_floor:.4f}")
            orders.append(("sell", float(abs(pos_qty))))
            consumed = True
            state = {}
    # Return
    exit_state = dict(exit_state)
    if state:
        exit_state[symbol] = state
    elif symbol in exit_state:
        exit_state.pop(symbol, None)
    
    logger.info(f"✅ {symbol} exit result: orders={len(orders)}, consumed={consumed}")
    return orders, exit_state, consumed


# NOTE: razorBill's load_exit_state / save_exit_state used its own ORM
# (ExitStateRow with took_partial/tight_trailing columns). sigma's ExitState
# ORM has a different shape (partial_tp_done/trailing_stop_px/high_water_px).
# Persistence is owned by the worker tick using sigma's ORM directly — these
# helpers are intentionally absent. Pass `exit_state` dict in/out of the
# pure logic functions above; the worker handles load/save.

async def load_exit_state() -> Dict[str, dict]:
    """Stub — worker tick reads from sigma's ExitState ORM."""
    return {}


async def save_exit_state(state: Dict[str, dict]) -> None:
    """Stub — worker tick writes to sigma's ExitState ORM."""
    return None


async def compute_exit_orders_advanced(
    symbol: str,
    g: pd.DataFrame,
    px_now: float,
    pos_qty: float,
    entry_px: float,
    entry_time: datetime,
    current_signal: float,
    exit_state: Dict[str, dict],
    *,
    stop_loss_pct: float,
    take_profit_pct: float,
    move_stop_to_breakeven: bool,
    trailing_stop_pct: float,
    trailing_stop_pct_after_tp: float,
    trailing_lookback_bars: int,
    max_hold_hours: int = 24,
    exit_on_negative_signal: bool = True,
    signal_exit_threshold: float = -0.5,
) -> Tuple[List[Tuple[str, float]], Dict[str, dict], bool]:
    """
    Enhanced exit logic with multiple exit strategies
    """
    from datetime import datetime, timezone
    
    orders: List[Tuple[str, float]] = []
    state = dict(exit_state.get(symbol, {}))
    consumed = False
    exit_reasons = []

    if abs(pos_qty) <= 1e-9 or entry_px <= 0:
        return orders, exit_state, False

    # Calculate time held
    # Handle timezone-aware vs timezone-naive datetime comparison
    if entry_time.tzinfo is None:
        # entry_time is naive, assume it's UTC
        entry_time_utc = entry_time.replace(tzinfo=timezone.utc)
    else:
        # entry_time is already timezone-aware
        entry_time_utc = entry_time

    time_held = (datetime.now(timezone.utc) - entry_time_utc).total_seconds() / 3600.0
    
    logger.info(f"🔍 Advanced exit check for {symbol}:")
    logger.info(f"   📊 Position: {pos_qty} @ ${entry_px:.4f}")
    logger.info(f"   💰 Current: ${px_now:.4f}")
    logger.info(f"   ⏰ Time held: {time_held:.1f} hours")
    logger.info(f"   📈 Signal: {current_signal:.3f}")

    if pos_qty > 0:
        # 1. Stop Loss
        long_stop = entry_px * (1.0 - float(stop_loss_pct))
        if px_now <= long_stop:
            orders.append(("sell", float(abs(pos_qty))))
            exit_reasons.append("stop_loss")
            consumed = True
            logger.warning(f"🛑 STOP LOSS: {px_now:.4f} <= {long_stop:.4f}")

        # 2. Take Profit
        long_tp = entry_px * (1.0 + float(take_profit_pct))
        if px_now >= long_tp:
            orders.append(("sell", float(abs(pos_qty))))
            exit_reasons.append("take_profit")
            consumed = True
            logger.info(f"💰 TAKE PROFIT: {px_now:.4f} >= {long_tp:.4f}")

        # 3. Time-based Exit
        if time_held >= max_hold_hours:
            orders.append(("sell", float(abs(pos_qty))))
            exit_reasons.append("time_exit")
            consumed = True
            logger.warning(f"⏰ TIME EXIT: Held {time_held:.1f}h >= {max_hold_hours}h")

        # 4. Signal-based Exit
        if exit_on_negative_signal and current_signal <= signal_exit_threshold:
            orders.append(("sell", float(abs(pos_qty))))
            exit_reasons.append("signal_exit")
            consumed = True
            logger.warning(f"📉 SIGNAL EXIT: {current_signal:.3f} <= {signal_exit_threshold}")

    if exit_reasons:
        logger.info(f"✅ {symbol} exit reasons: {', '.join(exit_reasons)}")

    # Update exit state
    exit_state = dict(exit_state)
    if state:
        exit_state[symbol] = state
    elif symbol in exit_state:
        exit_state.pop(symbol, None)
    
    return orders, exit_state, consumed


def trailing_stop_atr(
    symbol: str,
    g: pd.DataFrame,
    px_now: float,
    pos_qty: float,
    entry_px: float,
    atr: float,
    atr_multiplier: float = 2.0,
    lookback_bars: int = 20
) -> Tuple[float, bool]:
    """
    ATR-based trailing stop
    
    Returns: (trailing_stop_price, should_exit)
    """
    if abs(pos_qty) <= 1e-9 or entry_px <= 0 or atr <= 0:
        return entry_px * 0.99, False
    
    if len(g) < lookback_bars:
        lookback_bars = len(g)
    
    # Calculate highest high since entry
    lookback_data = g.tail(lookback_bars)
    highest_high = float(lookback_data["h"].max())
    
    # Trailing stop = highest_high - (ATR * multiplier)
    trailing_stop = highest_high - (atr * atr_multiplier)
    
    # Don't let trailing stop go below entry (for long positions)
    if pos_qty > 0:
        trailing_stop = max(trailing_stop, entry_px * 0.99)
    
    should_exit = px_now <= trailing_stop
    
    return trailing_stop, should_exit


def volatility_exit(
    symbol: str,
    g: pd.DataFrame,
    entry_volatility: float,
    current_volatility: float,
    volatility_threshold: float = 1.5
) -> bool:
    """
    Exit when volatility regime changes significantly
    
    Returns: should_exit
    """
    if entry_volatility <= 0:
        return False
    
    volatility_ratio = current_volatility / entry_volatility
    
    # Exit if volatility increased significantly (risk increased)
    return volatility_ratio >= volatility_threshold


def trend_reversal_exit(
    symbol: str,
    g: pd.DataFrame,
    entry_px: float,
    px_now: float,
    lookback_bars: int = 20
) -> bool:
    """
    Detect trend reversal and exit
    
    Returns: should_exit
    """
    if len(g) < lookback_bars:
        return False
    
    lookback_data = g.tail(lookback_bars)
    
    # Check for bearish reversal patterns
    # 1. Price below entry and declining
    if px_now < entry_px:
        recent_trend = lookback_data["c"].iloc[-5:].mean() - lookback_data["c"].iloc[-10:-5].mean()
        if recent_trend < 0:
            return True
    
    # 2. Lower highs pattern
    if len(lookback_data) >= 10:
        recent_highs = lookback_data["h"].tail(10)
        if len(recent_highs) >= 3:
            # Check if recent highs are declining
            high_trend = recent_highs.iloc[-1] - recent_highs.iloc[-3]
            if high_trend < 0 and px_now < entry_px * 1.02:  # Only if not much profit
                return True
    
    return False


def partial_profit_scaling(
    symbol: str,
    px_now: float,
    entry_px: float,
    pos_qty: float,
    exit_state: Dict[str, dict],
    profit_targets: List[float] = None,  # e.g., [0.02, 0.05, 0.10] for 2%, 5%, 10%
    partial_fractions: List[float] = None  # e.g., [0.25, 0.25, 0.25] for 25% each
) -> Tuple[List[Tuple[str, float]], Dict[str, dict]]:
    """
    Scale out of position at multiple profit targets
    
    Returns: (orders, updated_exit_state)
    """
    import numpy as np
    
    if profit_targets is None:
        profit_targets = [0.02, 0.05, 0.10]  # 2%, 5%, 10%
    if partial_fractions is None:
        partial_fractions = [0.25, 0.25, 0.25]  # 25% each
    
    orders: List[Tuple[str, float]] = []
    state = dict(exit_state.get(symbol, {}))
    
    if abs(pos_qty) <= 1e-9 or entry_px <= 0:
        return orders, exit_state
    
    # Track which targets have been hit
    targets_hit = state.get("profit_targets_hit", [])
    
    remaining_qty = pos_qty
    
    for i, (target_pct, fraction) in enumerate(zip(profit_targets, partial_fractions)):
        if i in targets_hit:
            continue
        
        target_price = entry_px * (1.0 + target_pct)
        
        if px_now >= target_price:
            # Hit this target, sell partial
            sell_qty = pos_qty * fraction
            if sell_qty > 0 and remaining_qty >= sell_qty:
                orders.append(("sell", float(sell_qty)))
                remaining_qty -= sell_qty
                targets_hit.append(i)
    
    state["profit_targets_hit"] = targets_hit
    state["remaining_qty"] = float(remaining_qty)
    
    exit_state = dict(exit_state)
    if state:
        exit_state[symbol] = state
    
    return orders, exit_state


def time_decay_exit(
    symbol: str,
    entry_time: datetime,
    px_now: float,
    entry_px: float,
    max_hold_hours: int,
    decay_factor: float = 0.5
) -> Tuple[bool, float]:
    """
    Exponential decay exit based on holding time
    
    Returns: (should_exit, urgency_factor)
    """
    from datetime import timezone
    import numpy as np
    
    if entry_time.tzinfo is None:
        entry_time_utc = entry_time.replace(tzinfo=timezone.utc)
    else:
        entry_time_utc = entry_time
    
    time_held_hours = (datetime.now(timezone.utc) - entry_time_utc).total_seconds() / 3600.0
    
    # Exponential decay: urgency increases as we approach max_hold_hours
    if time_held_hours >= max_hold_hours:
        return True, 1.0
    
    # Calculate urgency factor (0 to 1)
    urgency = 1.0 - np.exp(-decay_factor * time_held_hours / max_hold_hours)
    
    # Exit if urgency is high AND position is not profitable
    pnl_pct = (px_now - entry_px) / entry_px
    should_exit = urgency > 0.8 and pnl_pct < 0.01  # Less than 1% profit
    
    return should_exit, urgency


def compute_advanced_exit_orders(
    symbol: str,
    g: pd.DataFrame,
    px_now: float,
    pos_qty: float,
    entry_px: float,
    entry_time: datetime,
    current_signal: float,
    exit_state: Dict[str, dict],
    atr: float,
    volatility: float,
    entry_volatility: float,
    *,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float,
    trailing_stop_atr_multiplier: float = 2.0,
    use_atr_trailing: bool = False,
    use_volatility_exit: bool = False,
    use_trend_reversal: bool = False,
    use_partial_profits: bool = False,
    use_time_decay: bool = False,
    max_hold_hours: int = 24,
    exit_on_negative_signal: bool = True,
    signal_exit_threshold: float = -0.5,
) -> Tuple[List[Tuple[str, float]], Dict[str, dict], bool, str]:
    """
    Comprehensive exit logic with all advanced strategies
    
    Returns: (orders, updated_exit_state, consumed, exit_reason)
    """
    from datetime import timezone
    
    orders: List[Tuple[str, float]] = []
    state = dict(exit_state.get(symbol, {}))
    consumed = False
    exit_reason = ""
    
    if abs(pos_qty) <= 1e-9 or entry_px <= 0:
        return orders, exit_state, False, ""
    
    if pos_qty > 0:  # Long positions only
        # Priority 1: Stop Loss
        long_stop = entry_px * (1.0 - float(stop_loss_pct))
        if px_now <= long_stop:
            orders.append(("sell", float(abs(pos_qty))))
            consumed = True
            exit_reason = "stop_loss"
            logger.warning(f"🛑 STOP LOSS: {symbol} @ ${px_now:.4f}")
            state = {}
            return orders, {symbol: state} if state else {}, consumed, exit_reason
        
        # Priority 2: ATR-based trailing stop
        if use_atr_trailing and atr > 0:
            trailing_stop, should_exit = trailing_stop_atr(
                symbol, g, px_now, pos_qty, entry_px, atr, trailing_stop_atr_multiplier
            )
            if should_exit:
                orders.append(("sell", float(abs(pos_qty))))
                consumed = True
                exit_reason = "trailing_stop_atr"
                logger.warning(f"📉 TRAILING STOP (ATR): {symbol} @ ${px_now:.4f}")
                state = {}
                return orders, {symbol: state} if state else {}, consumed, exit_reason
        
        # Priority 3: Take Profit (full or partial)
        long_tp = entry_px * (1.0 + float(take_profit_pct))
        if px_now >= long_tp:
            if use_partial_profits:
                partial_orders, state = partial_profit_scaling(
                    symbol, px_now, entry_px, pos_qty, state
                )
                orders.extend(partial_orders)
                if len(partial_orders) > 0:
                    exit_reason = "partial_profit"
                    logger.info(f"💰 PARTIAL PROFIT: {symbol} @ ${px_now:.4f}")
            else:
                orders.append(("sell", float(abs(pos_qty))))
                consumed = True
                exit_reason = "take_profit"
                logger.info(f"💰 TAKE PROFIT: {symbol} @ ${px_now:.4f}")
                state = {}
        
        # Priority 4: Volatility exit
        if use_volatility_exit and entry_volatility > 0:
            if volatility_exit(symbol, g, entry_volatility, volatility):
                orders.append(("sell", float(abs(pos_qty))))
                consumed = True
                exit_reason = "volatility_exit"
                logger.warning(f"⚡ VOLATILITY EXIT: {symbol}")
                state = {}
                return orders, {symbol: state} if state else {}, consumed, exit_reason
        
        # Priority 5: Trend reversal
        if use_trend_reversal:
            if trend_reversal_exit(symbol, g, entry_px, px_now):
                orders.append(("sell", float(abs(pos_qty))))
                consumed = True
                exit_reason = "trend_reversal"
                logger.warning(f"🔄 TREND REVERSAL: {symbol}")
                state = {}
                return orders, {symbol: state} if state else {}, consumed, exit_reason
        
        # Priority 6: Time decay exit
        if use_time_decay:
            should_exit, urgency = time_decay_exit(
                symbol, entry_time, px_now, entry_px, max_hold_hours
            )
            if should_exit:
                orders.append(("sell", float(abs(pos_qty))))
                consumed = True
                exit_reason = "time_decay"
                logger.warning(f"⏰ TIME DECAY EXIT: {symbol} (urgency: {urgency:.2f})")
                state = {}
                return orders, {symbol: state} if state else {}, consumed, exit_reason
        
        # Priority 7: Signal-based exit
        if exit_on_negative_signal and current_signal <= signal_exit_threshold:
            orders.append(("sell", float(abs(pos_qty))))
            consumed = True
            exit_reason = "signal_exit"
            logger.warning(f"📉 SIGNAL EXIT: {symbol} (signal: {current_signal:.3f})")
            state = {}
            return orders, {symbol: state} if state else {}, consumed, exit_reason
        
        # Priority 8: Time-based exit
        if entry_time.tzinfo is None:
            entry_time_utc = entry_time.replace(tzinfo=timezone.utc)
        else:
            entry_time_utc = entry_time
        
        time_held = (datetime.now(timezone.utc) - entry_time_utc).total_seconds() / 3600.0
        if time_held >= max_hold_hours:
            orders.append(("sell", float(abs(pos_qty))))
            consumed = True
            exit_reason = "time_exit"
            logger.warning(f"⏰ TIME EXIT: {symbol} (held {time_held:.1f}h)")
            state = {}
            return orders, {symbol: state} if state else {}, consumed, exit_reason
    
    # Update exit state
    exit_state = dict(exit_state)
    if state:
        exit_state[symbol] = state
    elif symbol in exit_state:
        exit_state.pop(symbol, None)
    
    return orders, exit_state, consumed, exit_reason