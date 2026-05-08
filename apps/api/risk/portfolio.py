from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import logging

import numpy as np
import pandas as pd

from config import settings
from risk.manager import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class PortfolioMetrics:
    """Portfolio-level metrics and analytics"""
    total_positions: int
    total_notional: float
    total_unrealized_pnl: float
    portfolio_var_95: float
    portfolio_var_99: float
    portfolio_cvar_95: float
    max_drawdown: float
    diversification_score: float
    correlation_matrix: pd.DataFrame
    exposure_by_symbol: Dict[str, float]
    concentration_risk: float


class PortfolioManager:
    """Portfolio-level controls, analytics, and rebalancing"""
    
    def __init__(self, equity: float, risk_manager: RiskManager):
        self.equity = equity
        self.risk_manager = risk_manager
        self.positions: Dict[str, Tuple[float, float]] = {}  # symbol -> (qty, entry_px)
        self.last_rebalance_time: Optional[datetime] = None
        
    def update_positions(self, positions: Dict[str, Tuple[float, float]]):
        """Update current positions"""
        self.positions = positions.copy()
    
    def calculate_correlation_matrix(
        self,
        returns_by_symbol: Dict[str, pd.Series],
        lookback: int = 100
    ) -> pd.DataFrame:
        """
        Calculate correlation matrix for all symbols
        
        Returns DataFrame with symbols as index and columns
        """
        if not returns_by_symbol:
            return pd.DataFrame()
        
        # Align all return series
        aligned_returns = {}
        for symbol, returns in returns_by_symbol.items():
            if len(returns) >= lookback:
                aligned_returns[symbol] = returns.tail(lookback)
        
        if not aligned_returns:
            return pd.DataFrame()
        
        # Create DataFrame with aligned returns
        try:
            returns_df = pd.DataFrame(aligned_returns)
            correlation_matrix = returns_df.corr()
            return correlation_matrix.fillna(0.0)
        except Exception as e:
            logger.warning(f"Error calculating correlation matrix: {e}")
            return pd.DataFrame()
    
    def calculate_diversification_score(
        self,
        positions: Dict[str, Tuple[float, float]],
        correlation_matrix: pd.DataFrame
    ) -> float:
        """
        Calculate diversification score (0-1, higher is better)
        
        Based on effective number of positions considering correlations
        """
        if not positions or len(positions) == 0:
            return 0.0
        
        if len(positions) == 1:
            return 0.0
        
        # Get symbols that exist in both positions and correlation matrix
        symbols = [s for s in positions.keys() if s in correlation_matrix.index]
        if len(symbols) < 2:
            return 0.5  # Partial diversification
        
        # Calculate weights
        total_notional = sum(abs(qty * px) for qty, px in positions.values())
        if total_notional == 0:
            return 0.0
        
        weights = np.array([
            abs(qty * px) / total_notional 
            for qty, px in [positions[s] for s in symbols]
        ])
        
        # Extract correlation submatrix
        corr_submatrix = correlation_matrix.loc[symbols, symbols].values
        
        # Effective number of positions = 1 / sum(w_i^2 * (1 + sum(corr_ij * w_j)))
        # Simplified: 1 / (w^T * Corr * w)
        portfolio_variance = weights @ corr_submatrix @ weights
        effective_n = 1.0 / max(portfolio_variance, 1e-6)
        
        # Normalize to 0-1 scale (max effective_n = actual_n)
        max_n = len(symbols)
        score = min(1.0, effective_n / max_n) if max_n > 0 else 0.0
        
        return float(score)
    
    def calculate_concentration_risk(
        self,
        positions: Dict[str, Tuple[float, float]]
    ) -> float:
        """
        Calculate concentration risk using Herfindahl-Hirschman Index (HHI)
        
        Returns value between 0 (perfect diversification) and 1 (maximum concentration)
        """
        if not positions:
            return 0.0
        
        total_notional = sum(abs(qty * px) for qty, px in positions.values())
        if total_notional == 0:
            return 0.0
        
        # Calculate HHI
        weights = [abs(qty * px) / total_notional for qty, px in positions.values()]
        hhi = sum(w ** 2 for w in weights)
        
        return float(hhi)
    
    def check_position_count_limit(self) -> Tuple[bool, str]:
        """Check if position count exceeds limit"""
        count = len(self.positions)
        max_positions = settings.max_concurrent_positions
        
        if count >= max_positions:
            return True, f"Maximum position count reached: {count}/{max_positions}"
        
        return False, ""
    
    def check_portfolio_exposure_limit(
        self,
        new_position_notional: float = 0.0
    ) -> Tuple[bool, str]:
        """Check if total portfolio exposure exceeds limit"""
        total_notional = sum(
            abs(qty * px) for qty, px in self.positions.values()
        ) + new_position_notional
        
        max_exposure = settings.portfolio_max_exposure * self.equity
        
        if total_notional > max_exposure:
            return True, f"Portfolio exposure exceeds limit: ${total_notional:.2f} > ${max_exposure:.2f}"
        
        return False, ""
    
    def check_cash_reserve(self, new_position_cost: float = 0.0) -> Tuple[bool, str]:
        """Check if cash reserve requirement is met"""
        total_notional = sum(
            abs(qty * px) for qty, px in self.positions.values()
        ) + new_position_cost
        
        cash_remaining = self.equity - total_notional
        min_reserve = settings.min_cash_reserve_usd
        
        if cash_remaining < min_reserve:
            return True, f"Insufficient cash reserve: ${cash_remaining:.2f} < ${min_reserve:.2f}"
        
        return False, ""
    
    def calculate_portfolio_metrics(
        self,
        returns_by_symbol: Dict[str, pd.Series],
        current_prices: Dict[str, float]
    ) -> PortfolioMetrics:
        """Calculate comprehensive portfolio metrics"""
        # Calculate correlation matrix
        correlation_matrix = self.calculate_correlation_matrix(returns_by_symbol)
        
        # Calculate portfolio VaR
        portfolio_var_95, portfolio_var_99, portfolio_cvar_95 = (
            self.risk_manager.calculate_portfolio_var(
                self.positions, returns_by_symbol, correlation_matrix
            )
        )
        
        # Calculate total notional and PnL
        total_notional = sum(abs(qty * px) for qty, px in self.positions.values())
        total_unrealized_pnl = sum(
            (current_prices.get(symbol, px) - px) * qty
            for symbol, (qty, px) in self.positions.items()
        )
        
        # Calculate diversification and concentration
        diversification_score = self.calculate_diversification_score(
            self.positions, correlation_matrix
        )
        concentration_risk = self.calculate_concentration_risk(self.positions)
        
        # Calculate max drawdown
        max_drawdown = 0.0
        if len(self.risk_manager.equity_history) > 1:
            equity_series = pd.Series([e for _, e in self.risk_manager.equity_history])
            max_drawdown = self.risk_manager.calculate_max_drawdown(equity_series)
        
        # Calculate exposure by symbol
        exposure_by_symbol = {
            symbol: abs(qty * px) / self.equity if self.equity > 0 else 0.0
            for symbol, (qty, px) in self.positions.items()
        }
        
        return PortfolioMetrics(
            total_positions=len(self.positions),
            total_notional=total_notional,
            total_unrealized_pnl=total_unrealized_pnl,
            portfolio_var_95=portfolio_var_95,
            portfolio_var_99=portfolio_var_99,
            portfolio_cvar_95=portfolio_cvar_95,
            max_drawdown=max_drawdown,
            diversification_score=diversification_score,
            correlation_matrix=correlation_matrix,
            exposure_by_symbol=exposure_by_symbol,
            concentration_risk=concentration_risk
        )
    
    def should_rebalance(
        self,
        rebalance_threshold: float = 0.1,
        rebalance_interval_hours: int = 24
    ) -> bool:
        """
        Determine if portfolio should be rebalanced
        
        Args:
            rebalance_threshold: Maximum drift before rebalancing (0.1 = 10%)
            rebalance_interval_hours: Minimum time between rebalances
        """
        # Time-based rebalancing
        if self.last_rebalance_time is not None:
            hours_since_rebalance = (
                (datetime.now() - self.last_rebalance_time).total_seconds() / 3600
            )
            if hours_since_rebalance < rebalance_interval_hours:
                return False
        
        # Threshold-based rebalancing (simplified - would need target weights)
        # For now, just check if we're close to limits
        concentration = self.calculate_concentration_risk(self.positions)
        if concentration > (1.0 - rebalance_threshold):
            return True
        
        return False
    
    def get_rebalance_orders(
        self,
        target_weights: Dict[str, float],
        current_prices: Dict[str, float]
    ) -> List[Tuple[str, str, float]]:
        """
        Generate rebalancing orders to achieve target weights
        
        Returns: List of (symbol, side, qty) tuples
        """
        orders: List[Tuple[str, str, float]] = []
        
        if not target_weights:
            return orders
        
        total_notional = sum(
            abs(qty * px) for qty, px in self.positions.values()
        )
        if total_notional == 0:
            total_notional = self.equity
        
        # Calculate target notional for each symbol
        for symbol, target_weight in target_weights.items():
            if symbol not in current_prices:
                continue
            
            target_notional = target_weight * total_notional
            current_notional = abs(
                self.positions.get(symbol, (0.0, 0.0))[0] * current_prices[symbol]
            )
            
            notional_diff = target_notional - current_notional
            
            if abs(notional_diff) < 10.0:  # Minimum rebalance size
                continue
            
            qty_diff = notional_diff / current_prices[symbol]
            
            if qty_diff > 0:
                orders.append((symbol, "buy", abs(qty_diff)))
            else:
                orders.append((symbol, "sell", abs(qty_diff)))
        
        return orders
    
    def validate_new_position(
        self,
        symbol: str,
        qty: float,
        price: float
    ) -> Tuple[bool, str]:
        """
        Validate if a new position can be added
        
        Returns: (is_allowed, reason)
        """
        # Check position count
        is_at_limit, reason = self.check_position_count_limit()
        if is_at_limit and symbol not in self.positions:
            return False, reason
        
        # Check portfolio exposure
        notional = abs(qty * price)
        is_over_exposure, reason = self.check_portfolio_exposure_limit(notional)
        if is_over_exposure:
            return False, reason
        
        # Check cash reserve
        is_insufficient, reason = self.check_cash_reserve(notional)
        if is_insufficient:
            return False, reason
        
        return True, ""

