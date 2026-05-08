from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from loguru import logger

from .config import settings
from .db import SessionLocal, Candle, PositionRow, OrderRow, SignalRow, FeatureRow
from .models import FeatureEngineer, SequenceBuilder, RankingModel
from .strategy import detect_regime, fuse_signal, RiskState, apply_risk, size_position
from .execution import get_executor
from .exits import (
    compute_exit_orders, 
    compute_advanced_exit_orders,
    load_exit_state, 
    save_exit_state
)
from .nlp import get_sentiment_client
from .risk_manager import RiskManager
from .portfolio_manager import PortfolioManager
from .sizing import PositionSizer, SizingMethod
from .strategies import (
    MomentumStrategy,
    MeanReversionStrategy,
    BreakoutStrategy,
    RegimeStrategy,
    MLStrategy,
    StrategyCombiner
)
from .multi_timeframe import MultiTimeframeAnalyzer


async def one_cycle(equity: float = 10000.0) -> None:
    """Main trading cycle with enhanced multi-strategy framework"""
    executor = get_executor()
    
    # Initialize risk and portfolio managers
    risk_manager = RiskManager(equity)
    portfolio_manager = PortfolioManager(equity, risk_manager)
    
    # Initialize position sizer
    sizer = PositionSizer(equity)
    
    # Initialize strategies
    strategies = {}
    strategy_weights = settings.strategy_weights_dict
    
    if "momentum" in settings.enabled_strategies_list:
        strategies["momentum"] = MomentumStrategy()
    if "mean_reversion" in settings.enabled_strategies_list:
        strategies["mean_reversion"] = MeanReversionStrategy()
    if "breakout" in settings.enabled_strategies_list:
        strategies["breakout"] = BreakoutStrategy()
    if "regime" in settings.enabled_strategies_list:
        strategies["regime"] = RegimeStrategy()
    
    # Strategy combiner
    strategy_combiner = StrategyCombiner(strategies, strategy_weights)
    
    # Multi-timeframe analyzer
    mtf_analyzer = None
    if settings.use_multi_timeframe:
        mtf_analyzer = MultiTimeframeAnalyzer(settings.primary_timeframe)
    
    # Load current positions
    pos_by_symbol: dict[str, tuple[float, float]] = {}
    async with SessionLocal() as session:
        res = await session.execute(PositionRow.__table__.select())  # type: ignore[attr-defined]
        rows = res.fetchall()
        for r in rows:
            symbol = str(r._mapping["symbol"])  # type: ignore[index]
            qty = float(r._mapping["qty"])  # type: ignore[index]
            entry_px = float(r._mapping["entry_px"])  # type: ignore[index]
            pos_by_symbol[symbol] = (qty, entry_px)
    
    # Load recent candles
    async with SessionLocal() as session:
        # Get last 100 bars for each symbol
        symbols = settings.universe_list
        frames = []
        for sym in symbols:
            q = (
                Candle.__table__.select()
                .where(Candle.symbol == sym)  # type: ignore[attr-defined]
                .order_by(Candle.t.desc())  # type: ignore[attr-defined]
                .limit(100)
            )
            res = await session.execute(q)
            rows = res.fetchall()
            if not rows:
                continue
            df = pd.DataFrame([dict(r._mapping) for r in rows])
            df["t"] = pd.to_datetime(df["t"], utc=True)
            frames.append(df)
        
        if not frames:
            logger.warning("No candle data available")
            return
        
        candles = pd.concat(frames, ignore_index=True)
    
    # Compute features
    fe = FeatureEngineer()
    feats = pd.concat([fe.compute(g) for _, g in candles.groupby("symbol")], ignore_index=True)
    feats = feats.sort_values(["symbol", "t"]).reset_index(drop=True)
    
    # Store features in database
    rows = []
    for _, row in feats.iterrows():
        rows.append(
            FeatureRow(
                symbol=row["symbol"],
                t=row["t"],
                rsi=row["rsi"],
                atr=row["atr"],
                ema_fast=row["ema_fast"],
                ema_slow=row["ema_slow"],
                mom_1=row["mom_1"],
                mom_3=row["mom_3"],
                mom_12=row["mom_12"],
                vol_realized=row["vol_realized"],
                rolling_vol_50=row["rolling_vol_50"],
                v_spike=row["v_spike"],
                breakout_20=row["breakout_20"],
                regime=str(detect_regime(row["ema_fast"], row["ema_slow"], row["vol_realized"])),
            )
        )
    async with SessionLocal() as session:
        for r in rows:
            session.add(r)
        await session.commit()

    # Sequences and model
    sb = SequenceBuilder(window=settings.window)
    seqs: list = []
    metas: list[dict] = []
    for sym, g in feats.groupby("symbol"):
        if len(g) < settings.window + 1:  # Skip symbols with insufficient data
            logger.warning(f"Skipping {sym}: insufficient data ({len(g)} bars)")
            continue
        try:
            seqs_sym = sb.fit_transform(g)
            seqs += seqs_sym
            metas += [s.meta for s in seqs_sym]
        except Exception as e:
            logger.warning(f"Skipping {sym}: model error - {e}")
            continue

    if not seqs:
        logger.warning("No valid sequences found; skipping model training")
        return
    
    model = RankingModel()
    model.fit(seqs)
    preds = model.predict(seqs)

    # RankIC per decision time (Top-K stub)
    y = np.array([s.y for s in seqs], dtype=np.float32)
    ic = model.rank_ic(preds, y) if len(preds) == len(y) else float("nan")
    logger.info("RankIC (global): {}", ic)

    # Use last window per symbol to produce signal now
    signals: list[SignalRow] = []
    any_orders = False
    # Optionally buy top-K by model score now
    top_k = int(settings.top_k_buy)
    metas_by_idx = {i: m for i, m in enumerate(metas)}
    pred_indices = list(range(len(preds)))
    top_syms: list[str] = []
    if top_k > 0 and pred_indices:
        top_ix = sorted(pred_indices, key=lambda i: float(preds[i]), reverse=True)[:top_k]
        top_syms = [metas_by_idx[i]["symbol"] for i in top_ix]
        logger.info("Top-{} by model: {}", top_k, top_syms)

    # Per-symbol exit state for partial TP and breakeven/trailing adjustments
    if not hasattr(one_cycle, "_exit_state"):
        # Load persisted state on first run
        exit_loaded = await load_exit_state()
        setattr(one_cycle, "_exit_state", exit_loaded)
    exit_state: dict[str, dict] = getattr(one_cycle, "_exit_state")

    # Sentiment analysis
    sent_by_symbol: dict[str, tuple[float, int]] = {}
    if settings.sentiment_provider != "none":
        sentiment_client = get_sentiment_client()
        for sym in symbols:
            try:
                result = await sentiment_client.fetch_sentiment(sym)
                sent_by_symbol[sym] = (result.score, result.n_docs)
            except Exception as e:
                logger.warning(f"Sentiment failed for {sym}: {e}")
                sent_by_symbol[sym] = (0.0, 0)
    
    # Prepare model predictions for ML strategy
    model_predictions: dict[str, float] = {}
    for sym in symbols:
        sym_idxs = [i for i, m in enumerate(metas) if m["symbol"] == sym]
        if sym_idxs:
            model_predictions[sym] = float(preds[sym_idxs[-1]])
        else:
            model_predictions[sym] = 0.0
    
    # Add ML strategy if enabled
    if "ml" in settings.enabled_strategies_list:
        strategies["ml"] = MLStrategy(model_predictions)
        strategy_combiner = StrategyCombiner(strategies, strategy_weights)
    
    # Calculate returns for risk management
    returns_by_symbol: dict[str, pd.Series] = {}
    for sym in symbols:
        sym_feats = feats[feats["symbol"] == sym]
        if len(sym_feats) > 1 and "ret1" in sym_feats.columns:
            returns_by_symbol[sym] = sym_feats["ret1"]
    
    # Update portfolio manager with current positions
    portfolio_manager.update_positions(pos_by_symbol)
    
    # Calculate correlation matrix
    correlation_matrix = portfolio_manager.calculate_correlation_matrix(returns_by_symbol)
    
    # Check portfolio-level risk limits
    is_violated, violation_reason = risk_manager.check_portfolio_risk_limits(
        pos_by_symbol, returns_by_symbol, correlation_matrix, equity
    )
    if is_violated:
        logger.warning(f"Portfolio risk limit violated: {violation_reason}")
        # Could implement circuit breaker here
        if settings.circuit_breaker_enabled:
            logger.error("Circuit breaker triggered - stopping trading")
            return

    # Process each symbol
    for sym in feats["symbol"].unique():
        g = feats[feats["symbol"] == sym].copy()
        if len(g) < settings.window + 1:
            continue
        last = g.iloc[-1]
        px_now = float(last["c"])

        # Validate position quantities
        pos_tuple = pos_by_symbol.get(sym)
        if pos_tuple is not None:
            pos_qty, entry_px = pos_tuple
            if pos_qty < 0:
                logger.warning(f"⚠️ Negative position quantity for {sym}: {pos_qty}. Skipping exit logic.")
                # Continue to signal calculation

        # Generate signal using multi-strategy framework
        combined_signal = strategy_combiner.combine_signals(
            symbol=sym,
            features=g,
            current_price=px_now,
            model_predictions=model_predictions
        )
        
        # Multi-timeframe filtering if enabled
        if mtf_analyzer and settings.higher_timeframe_filter:
            # For now, use primary timeframe data (would need multi-timeframe data fetching)
            # This is a placeholder - full implementation would fetch multiple timeframes
            should_trade, adjusted_signal = True, combined_signal.strength
            if not should_trade:
                combined_signal.strength = 0.0
        
        # Apply risk scaling
        position_risk = risk_manager.calculate_position_risk_metrics(
            symbol=sym,
            qty=pos_tuple[0] if pos_tuple else 0.0,
            entry_px=pos_tuple[1] if pos_tuple else px_now,
            current_px=px_now,
            returns=returns_by_symbol.get(sym, pd.Series()),
            atr=float(last["atr"])
        )
        
        # Apply risk adjustment to signal
        risk_scale = 1.0
        if settings.use_portfolio_var:
            var_budget = settings.strategy.risk_var_95 * equity
            if position_risk.risk_metrics.var_95 > 0:
                risk_scale = min(1.0, var_budget / (position_risk.risk_metrics.var_95 * abs(combined_signal.strength) + 1e-6))
        
        final_sig = combined_signal.strength * risk_scale
        final_sig = float(np.clip(final_sig, -1.0, 1.0))
        
        # Store signal
        signals.append(
            SignalRow(
                t=pd.Timestamp(last["t"]).to_pydatetime(),
                symbol=sym,
                signal=final_sig,
                weight_model=settings.strategy.weight_model,
                weight_sent=settings.strategy.weight_sent,
                weight_regime=settings.strategy.weight_regime,
                conf=combined_signal.confidence,
                risk_var_95=position_risk.risk_metrics.var_95,
                atr=float(last["atr"]),
            )
        )
        
        # Exit logic - use advanced exits if configured
        if sym in pos_by_symbol:
            pos_qty, entry_px = pos_by_symbol[sym]
            entry_time = None
            
            # Get entry time from database
            async with SessionLocal() as session:
                res = await session.execute(
                    PositionRow.__table__.select().where(PositionRow.symbol == sym)  # type: ignore[attr-defined]
                )
                row = res.fetchone()
                if row:
                    entry_time = row._mapping.get("entry_time")  # type: ignore[index]
            
            if abs(pos_qty) > 1e-9 and entry_px > 0:
                # Use advanced exits if any are enabled
                if (settings.use_atr_trailing or settings.use_volatility_exit or 
                    settings.use_trend_reversal_exit or settings.use_partial_profits or 
                    settings.use_time_decay_exit):
                    
                    # Get entry volatility
                    entry_volatility = float(last.get("vol_realized", 0.0))
                    current_volatility = float(last.get("vol_realized", 0.0))
                    
                    orders, exit_state, consumed, exit_reason = compute_advanced_exit_orders(
                        symbol=sym,
                        g=g,
                        px_now=px_now,
                        pos_qty=float(pos_qty),
                        entry_px=float(entry_px),
                        entry_time=entry_time or pd.Timestamp(last["t"]).to_pydatetime(),
                        current_signal=final_sig,
                        exit_state=exit_state,
                        atr=float(last["atr"]),
                        volatility=current_volatility,
                        entry_volatility=entry_volatility,
                        stop_loss_pct=float(settings.stop_loss_pct),
                        take_profit_pct=float(settings.take_profit_pct),
                        trailing_stop_pct=float(settings.trailing_stop_pct),
                        trailing_stop_atr_multiplier=float(settings.trailing_stop_atr_multiplier),
                        use_atr_trailing=bool(settings.use_atr_trailing),
                        use_volatility_exit=bool(settings.use_volatility_exit),
                        use_trend_reversal=bool(settings.use_trend_reversal_exit),
                        use_partial_profits=bool(settings.use_partial_profits),
                        use_time_decay=bool(settings.use_time_decay_exit),
                        max_hold_hours=int(settings.max_hold_hours),
                        exit_on_negative_signal=bool(settings.exit_on_negative_signal),
                        signal_exit_threshold=float(settings.signal_exit_threshold),
                    )
                else:
                    # Use basic exits
                    orders, exit_state, consumed = compute_exit_orders(
                        symbol=sym,
                        g=g,
                        px_now=px_now,
                        pos_qty=float(pos_qty),
                        entry_px=float(entry_px),
                        exit_state=exit_state,
                        stop_loss_pct=float(settings.stop_loss_pct),
                        take_profit_pct=float(settings.take_profit_pct),
                        move_stop_to_breakeven=bool(settings.move_stop_to_breakeven),
                        trailing_stop_pct=float(settings.trailing_stop_pct),
                        trailing_stop_pct_after_tp=float(settings.trailing_stop_pct_after_tp),
                        trailing_lookback_bars=int(settings.trailing_lookback_bars),
                    )
                
                # Execute exit orders
                for side, qty in orders:
                    if qty > 0:
                        po = await executor.market_order(sym, side, qty, px_now)
                        if po.qty > 0:
                            any_orders = True
                            # Store order in database
                            async with SessionLocal() as session:
                                session.add(
                                    OrderRow(
                                        t=po.t,
                                        symbol=po.symbol,
                                        side=po.side,
                                        qty=po.qty,
                                        px=po.px,
                                        fee=po.fee,
                                        slip=po.slip,
                                    )
                                )
                                await session.commit()
                
                if consumed:
                    # Remove position from database
                    async with SessionLocal() as session:
                        await session.execute(
                            PositionRow.__table__.delete().where(PositionRow.symbol == sym)  # type: ignore[attr-defined]
                        )
                        await session.commit()
                    pos_by_symbol.pop(sym, None)

        # Entry logic
        if (final_sig > 0 and 
            combined_signal.confidence >= settings.min_signal_confidence and
            sym not in pos_by_symbol):
            
            # Portfolio-level validation
            is_allowed, reason = portfolio_manager.validate_new_position(sym, 0.0, px_now)
            if not is_allowed:
                logger.info(f"Skipping {sym} entry: {reason}")
                continue
            
            # Check position count
            max_positions = int(settings.max_concurrent_positions)
            if len(pos_by_symbol) >= max_positions:
                continue
            
            # Calculate position size using selected method
            sizing_method_map = {
                "kelly": SizingMethod.KELLY,
                "volatility_target": SizingMethod.VOLATILITY_TARGET,
                "risk_parity": SizingMethod.RISK_PARITY,
                "fixed_fractional": SizingMethod.FIXED_FRACTIONAL,
                "atr_based": SizingMethod.ATR_BASED,
            }
            
            method = sizing_method_map.get(settings.sizing_method, SizingMethod.KELLY)
            
            # Get correlation for sizing adjustment
            correlation = 1.0
            if settings.use_correlation_adjustment and sym in correlation_matrix.index:
                # Average correlation with current positions
                if len(pos_by_symbol) > 0:
                    position_symbols = list(pos_by_symbol.keys())
                    if position_symbols:
                        correlations = [
                            correlation_matrix.loc[sym, pos_sym] 
                            for pos_sym in position_symbols 
                            if pos_sym in correlation_matrix.index
                        ]
                        if correlations:
                            correlation = 1.0 - (sum(correlations) / len(correlations)) * 0.5  # Reduce size for correlated positions
                            correlation = max(0.5, correlation)  # Don't reduce below 50%
            
            sizing = sizer.size_position(
                method=method,
                price=px_now,
                signal=final_sig,
                volatility=float(last.get("vol_realized", 0.2)),
                atr=float(last.get("atr", px_now * 0.01)),
                symbol=sym,
                correlation_adjustment=correlation,
                target_volatility=settings.target_volatility,
                fraction=settings.fixed_fractional_pct,
                risk_per_trade=settings.atr_risk_per_trade,
                num_positions=len(pos_by_symbol) + 1,
                portfolio_volatility=settings.target_volatility
            )
            
            # Check position risk limits
            if sizing.qty > 0:
                is_violated, reason = risk_manager.check_position_risk_limits(
                    sym, sizing.qty, px_now, 
                    returns_by_symbol.get(sym, pd.Series()),
                    float(last["atr"])
                )
                if is_violated:
                    logger.info(f"Skipping {sym} entry due to risk limits: {reason}")
                    continue
                
                # Final portfolio validation with actual size
                is_allowed, reason = portfolio_manager.validate_new_position(sym, sizing.qty, px_now)
                if not is_allowed:
                    logger.info(f"Skipping {sym} entry: {reason}")
                    continue
                
                if sizing.qty > 0:
                    po = await executor.market_order(sym, "buy", sizing.qty, px_now)
                    if po.qty > 0:
                        any_orders = True
                        # Store order in database
                        async with SessionLocal() as session:
                            session.add(
                                OrderRow(
                                    t=po.t,
                                    symbol=po.symbol,
                                    side=po.side,
                                    qty=po.qty,
                                    px=po.px,
                                    fee=po.fee,
                                    slip=po.slip,
                                )
                            )
                            await session.commit()
                        
                        # Store position in database
                        async with SessionLocal() as session:
                            session.add(
                                PositionRow(
                                    symbol=sym,
                                    qty=po.qty,
                                    entry_px=po.px,
                                    entry_time=po.t,
                                    current_px=px_now,
                                    unrealized_pnl=(px_now - po.px) * po.qty,
                                )
                            )
                            await session.commit()
                        
                        pos_by_symbol[sym] = (po.qty, po.px)

    # Store signals in database
    async with SessionLocal() as session:
        for signal in signals:
            session.add(signal)
        await session.commit()

    # Save exit state
    await save_exit_state(exit_state)
    setattr(one_cycle, "_exit_state", exit_state)
    
    # Update risk manager equity history
    risk_manager.update_equity_history(equity)
    
    # Calculate and log portfolio metrics
    current_prices = {}
    for sym in pos_by_symbol.keys():
        sym_data = feats[feats["symbol"] == sym]
        if len(sym_data) > 0:
            current_prices[sym] = float(sym_data.iloc[-1]["c"])
        else:
            logger.warning(f"No data found for position symbol {sym}, skipping price lookup")
    
    if current_prices:
        portfolio_metrics = portfolio_manager.calculate_portfolio_metrics(
            returns_by_symbol, current_prices
        )
    else:
        logger.warning("No valid prices found for portfolio metrics calculation")
        portfolio_metrics = {}
    
    logger.info(f"Cycle complete. Orders executed: {any_orders}")
    logger.info(f"Current positions: {len(pos_by_symbol)}")
    logger.info(f"Portfolio VaR (95%): ${portfolio_metrics.portfolio_var_95:.2f}")
    logger.info(f"Diversification score: {portfolio_metrics.diversification_score:.2f}")
    logger.info(f"Concentration risk: {portfolio_metrics.concentration_risk:.2f}")


async def main():
    """Main entry point for paper trading"""
    logger.info("Starting RazorBill paper trading bot")
    
    while True:
        try:
            await one_cycle()
            logger.info("Sleeping for 5 minutes...")
            await asyncio.sleep(300)  # 5 minutes
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")
            await asyncio.sleep(60)  # Wait 1 minute before retrying


if __name__ == "__main__":
    asyncio.run(main())