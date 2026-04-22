from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum

import numpy as np
from loguru import logger

from .config import settings


class SizingMethod(str, Enum):
    """Position sizing methods"""
    KELLY = "kelly"
    VOLATILITY_TARGET = "volatility_target"
    RISK_PARITY = "risk_parity"
    FIXED_FRACTIONAL = "fixed_fractional"
    ATR_BASED = "atr_based"


@dataclass
class Sizing:
    """Position sizing result"""
    qty: float
    notional: float
    method: str
    confidence: float = 1.0


class PositionSizer:
    """Advanced position sizing with multiple methods"""
    
    def __init__(self, equity: float):
        self.equity = equity
    
    def kelly_optimal(
        self,
        price: float,
        signal: float,
        win_rate: float = 0.5,
        avg_win: float = 0.02,
        avg_loss: float = 0.01,
        correlation_adjustment: float = 1.0
    ) -> Sizing:
        """
        Enhanced Kelly Criterion with correlation adjustment
        
        Args:
            price: Current price
            signal: Signal strength (-1 to 1)
            win_rate: Historical win rate
            avg_win: Average winning trade return
            avg_loss: Average losing trade return (positive value)
            correlation_adjustment: Adjust for portfolio correlation (0-1)
        """
        if price <= 0:
            return Sizing(qty=0.0, notional=0.0, method="kelly")
        
        # Basic Kelly fraction
        if avg_loss == 0:
            kelly_fraction = 0.0
        else:
            kelly_fraction = win_rate - ((1 - win_rate) / (avg_win / avg_loss))
        
        # Apply signal strength and cap
        kelly_fraction *= abs(signal)
        kelly_fraction = min(kelly_fraction, settings.strategy.kelly_cap)
        
        # Correlation adjustment (reduce size for correlated positions)
        kelly_fraction *= correlation_adjustment
        
        notional = self.equity * kelly_fraction
        
        # Apply per-trade cap
        if settings.per_trade_notional_cap_usd > 0:
            notional = min(notional, settings.per_trade_notional_cap_usd)
        
        qty = notional / price
        
        return Sizing(
            qty=max(0.0, qty),
            notional=notional,
            method="kelly",
            confidence=abs(signal)
        )
    
    def volatility_targeting(
        self,
        price: float,
        volatility: float,
        target_volatility: float = 0.15,
        signal: float = 1.0
    ) -> Sizing:
        """
        Size position to target portfolio volatility
        
        Args:
            price: Current price
            volatility: Annualized volatility of the asset
            target_volatility: Target annualized portfolio volatility (default 15%)
            signal: Signal strength (-1 to 1)
        """
        if price <= 0 or volatility <= 0:
            return Sizing(qty=0.0, notional=0.0, method="volatility_target")
        
        # Calculate position size to achieve target volatility
        # Assuming equal weight across positions (simplified)
        # For single position: position_vol = asset_vol * weight
        # We want: portfolio_vol = target_vol
        # Simplified: weight = target_vol / asset_vol
        
        weight = min(1.0, target_volatility / volatility)
        weight *= abs(signal)  # Scale by signal strength
        
        notional = self.equity * weight
        
        # Apply per-trade cap
        if settings.per_trade_notional_cap_usd > 0:
            notional = min(notional, settings.per_trade_notional_cap_usd)
        
        qty = notional / price
        
        return Sizing(
            qty=max(0.0, qty),
            notional=notional,
            method="volatility_target",
            confidence=abs(signal)
        )
    
    def risk_parity(
        self,
        price: float,
        volatility: float,
        portfolio_volatility: float = 0.15,
        num_positions: int = 1,
        signal: float = 1.0
    ) -> Sizing:
        """
        Risk parity sizing - equal risk contribution
        
        Args:
            price: Current price
            volatility: Asset volatility
            portfolio_volatility: Target portfolio volatility
            num_positions: Number of positions in portfolio
            signal: Signal strength (-1 to 1)
        """
        if price <= 0 or volatility <= 0 or num_positions == 0:
            return Sizing(qty=0.0, notional=0.0, method="risk_parity")
        
        # Equal risk contribution: each position contributes portfolio_vol / num_positions
        target_position_vol = portfolio_volatility / num_positions
        
        # Weight = target_vol / asset_vol
        weight = min(1.0, target_position_vol / volatility)
        weight *= abs(signal)
        
        notional = self.equity * weight
        
        # Apply per-trade cap
        if settings.per_trade_notional_cap_usd > 0:
            notional = min(notional, settings.per_trade_notional_cap_usd)
        
        qty = notional / price
        
        return Sizing(
            qty=max(0.0, qty),
            notional=notional,
            method="risk_parity",
            confidence=abs(signal)
        )
    
    def fixed_fractional(
        self,
        price: float,
        fraction: float = 0.1,
        signal: float = 1.0
    ) -> Sizing:
        """
        Fixed fractional sizing - fixed percentage of equity
        
        Args:
            price: Current price
            fraction: Fraction of equity to risk (default 10%)
            signal: Signal strength (-1 to 1)
        """
        if price <= 0 or fraction <= 0:
            return Sizing(qty=0.0, notional=0.0, method="fixed_fractional")
        
        notional = self.equity * fraction * abs(signal)
        
        # Apply per-trade cap
        if settings.per_trade_notional_cap_usd > 0:
            notional = min(notional, settings.per_trade_notional_cap_usd)
        
        qty = notional / price
        
        return Sizing(
            qty=max(0.0, qty),
            notional=notional,
            method="fixed_fractional",
            confidence=abs(signal)
        )
    
    def atr_based(
        self,
        price: float,
        atr: float,
        risk_per_trade: float = 0.01,
        signal: float = 1.0
    ) -> Sizing:
        """
        ATR-based sizing - size based on stop distance
        
        Args:
            price: Current price
            atr: Average True Range
            risk_per_trade: Risk per trade as fraction of equity (default 1%)
            signal: Signal strength (-1 to 1)
        """
        if price <= 0 or atr <= 0:
            return Sizing(qty=0.0, notional=0.0, method="atr_based")
        
        # Use ATR as stop distance (e.g., 2x ATR)
        stop_distance = 2.0 * atr
        if stop_distance == 0:
            return Sizing(qty=0.0, notional=0.0, method="atr_based")
        
        # Risk amount
        risk_amount = self.equity * risk_per_trade * abs(signal)
        
        # Position size = risk_amount / stop_distance
        qty = risk_amount / stop_distance
        
        notional = qty * price
        
        # Apply per-trade cap
        if settings.per_trade_notional_cap_usd > 0:
            notional = min(notional, settings.per_trade_notional_cap_usd)
            qty = notional / price
        
        return Sizing(
            qty=max(0.0, qty),
            notional=notional,
            method="atr_based",
            confidence=abs(signal)
        )
    
    def size_position(
        self,
        method: SizingMethod,
        price: float,
        signal: float,
        volatility: Optional[float] = None,
        atr: Optional[float] = None,
        **kwargs
    ) -> Sizing:
        """
        Main sizing method that routes to appropriate sizing function
        
        Args:
            method: Sizing method to use
            price: Current price
            signal: Signal strength (-1 to 1)
            volatility: Asset volatility (for volatility-based methods)
            atr: Average True Range (for ATR-based method)
            **kwargs: Additional parameters for specific methods
        """
        if price <= 0:
            return Sizing(qty=0.0, notional=0.0, method=method.value)
        
        # Apply per-symbol cap if exists
        symbol = kwargs.get("symbol", "")
        symbol_caps = settings.per_symbol_caps_map
        if symbol and symbol in symbol_caps:
            max_notional = symbol_caps[symbol]
        else:
            max_notional = None
        
        if method == SizingMethod.KELLY:
            sizing = self.kelly_optimal(
                price=price,
                signal=signal,
                win_rate=kwargs.get("win_rate", 0.5),
                avg_win=kwargs.get("avg_win", 0.02),
                avg_loss=kwargs.get("avg_loss", 0.01),
                correlation_adjustment=kwargs.get("correlation_adjustment", 1.0)
            )
        elif method == SizingMethod.VOLATILITY_TARGET:
            if volatility is None:
                volatility = kwargs.get("volatility", 0.2)
            sizing = self.volatility_targeting(
                price=price,
                volatility=volatility,
                target_volatility=kwargs.get("target_volatility", 0.15),
                signal=signal
            )
        elif method == SizingMethod.RISK_PARITY:
            if volatility is None:
                volatility = kwargs.get("volatility", 0.2)
            sizing = self.risk_parity(
                price=price,
                volatility=volatility,
                portfolio_volatility=kwargs.get("portfolio_volatility", 0.15),
                num_positions=kwargs.get("num_positions", 1),
                signal=signal
            )
        elif method == SizingMethod.FIXED_FRACTIONAL:
            sizing = self.fixed_fractional(
                price=price,
                fraction=kwargs.get("fraction", 0.1),
                signal=signal
            )
        elif method == SizingMethod.ATR_BASED:
            if atr is None:
                atr = kwargs.get("atr", price * 0.01)
            sizing = self.atr_based(
                price=price,
                atr=atr,
                risk_per_trade=kwargs.get("risk_per_trade", 0.01),
                signal=signal
            )
        else:
            # Default to Kelly
            sizing = self.kelly_optimal(price=price, signal=signal)
        
        # Apply per-symbol cap
        if max_notional is not None and sizing.notional > max_notional:
            sizing.notional = max_notional
            sizing.qty = max_notional / price
        
        return sizing


# Backward compatibility function
def size_position(equity: float, price: float, vol_target: float, signal: float) -> Sizing:
    """
    Legacy function for backward compatibility
    
    Uses Kelly method with simplified parameters
    """
    sizer = PositionSizer(equity)
    return sizer.size_position(
        method=SizingMethod.KELLY,
        price=price,
        signal=signal,
        volatility=vol_target
    )

