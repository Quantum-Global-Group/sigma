from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import random
from typing import Union

import pandas as pd
from loguru import logger

from .config import settings


@dataclass
class PaperOrder:
    t: datetime
    symbol: str
    side: str
    qty: float
    px: float
    fee: float
    slip: float


class PaperExecutor:
    """Paper trading executor with realistic slippage and fees"""
    
    def __init__(self):
        self.orders: list[PaperOrder] = []
    
    async def market_order(self, symbol: str, side: str, qty: float, px: float) -> PaperOrder:
        """Execute a market order with realistic costs"""
        if qty <= 0:
            return PaperOrder(
                t=datetime.now(timezone.utc),
                symbol=symbol,
                side=side,
                qty=0.0,
                px=px,
                fee=0.0,
                slip=0.0
            )
        
        # Calculate slippage
        slippage_bps = self._calculate_slippage(symbol, qty, px)
        slip_px = px * (slippage_bps / 10000)
        
        # Apply slippage
        if side == "buy":
            exec_px = px + slip_px
        else:  # sell
            exec_px = px - slip_px
        
        # Calculate fees
        notional = qty * exec_px
        fee_bps = settings.maker_fee_bps if side == "buy" else settings.taker_fee_bps
        fee = notional * (fee_bps / 10000)
        
        # Add latency
        latency_ms = settings.order_latency_ms
        if settings.order_latency_jitter_min_ms > 0:
            jitter = random.randint(
                settings.order_latency_jitter_min_ms,
                settings.order_latency_jitter_max_ms
            )
            latency_ms += jitter
        
        # Simulate partial fills
        fill_pct = settings.partial_fill_pct
        if fill_pct < 1.0:
            fill_pct = random.uniform(fill_pct, 1.0)
        
        final_qty = qty * fill_pct
        
        order = PaperOrder(
            t=datetime.now(timezone.utc),
            symbol=symbol,
            side=side,
            qty=final_qty,
            px=exec_px,
            fee=fee,
            slip=slip_px * final_qty
        )
        
        self.orders.append(order)
        logger.info(f"Executed {side} {final_qty:.4f} {symbol} @ ${exec_px:.4f} (fee: ${fee:.2f}, slip: ${order.slip:.2f})")
        
        return order
    
    def _calculate_slippage(self, symbol: str, qty: float, px: float) -> float:
        """Calculate realistic slippage based on order size and market conditions"""
        base_slippage = settings.strategy.slippage_bps
        
        # Higher slippage for small cap coins
        if px < settings.smallcap_price_threshold_usd:
            base_slippage = settings.smallcap_slippage_bps
        
        # Scale slippage with order size (simplified)
        notional = qty * px
        if notional > 10000:  # Large orders
            base_slippage *= 1.5
        elif notional < 1000:  # Small orders
            base_slippage *= 0.5
        
        return base_slippage
    
    def get_order_history(self) -> pd.DataFrame:
        """Get all executed orders as DataFrame"""
        if not self.orders:
            return pd.DataFrame()
        
        data = []
        for order in self.orders:
            data.append({
                't': order.t,
                'symbol': order.symbol,
                'side': order.side,
                'qty': order.qty,
                'px': order.px,
                'fee': order.fee,
                'slip': order.slip
            })
        
        return pd.DataFrame(data)


def get_executor() -> Union[PaperExecutor, "CoinbaseExecutor"]:
    """
    Factory function to get the appropriate executor based on settings
    
    Returns:
        PaperExecutor or CoinbaseExecutor instance
    """
    if settings.executor_mode == "coinbase":
        try:
            from .coinbase_executor import CoinbaseExecutor
            logger.info("Using Coinbase Advanced Trade executor")
            return CoinbaseExecutor()
        except Exception as e:
            logger.error(f"Failed to initialize Coinbase executor: {e}")
            logger.warning("Falling back to paper executor")
            return PaperExecutor()
    else:
        logger.info("Using paper trading executor")
        return PaperExecutor()