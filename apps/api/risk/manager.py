from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import logging

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    """Comprehensive risk metrics for a position or portfolio"""
    var_95: float  # Value at Risk at 95% confidence
    var_99: float  # Value at Risk at 99% confidence
    cvar_95: float  # Conditional VaR (Expected Shortfall) at 95%
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    volatility: float
    atr: float


@dataclass
class PositionRisk:
    """Risk metrics for a single position"""
    symbol: str
    qty: float
    entry_px: float
    current_px: float
    notional: float
    unrealized_pnl: float
    risk_metrics: RiskMetrics
    correlation_with_portfolio: float


class RiskManager:
    """Comprehensive risk management for portfolio and positions"""
    
    def __init__(self, equity: float):
        self.equity = equity
        self.daily_pnl_history: List[Tuple[datetime, float]] = []
        self.equity_history: List[Tuple[datetime, float]] = []
        self.peak_equity = equity
        
    def calculate_historical_var(
        self, 
        returns: pd.Series, 
        confidence: float = 0.95,
        lookback: int = 100
    ) -> float:
        """Calculate Historical VaR"""
        if len(returns) < lookback:
            lookback = len(returns)
        if lookback == 0:
            return 0.0
        
        recent_returns = returns.tail(lookback)
        if len(recent_returns) == 0:
            return 0.0
        
        var = float(np.percentile(recent_returns, (1 - confidence) * 100))
        return abs(var) if var < 0 else 0.0
    
    def calculate_parametric_var(
        self,
        returns: pd.Series,
        confidence: float = 0.95,
        lookback: int = 100
    ) -> float:
        """Calculate Parametric VaR assuming normal distribution"""
        if len(returns) < lookback:
            lookback = len(returns)
        if lookback == 0:
            return 0.0
        
        recent_returns = returns.tail(lookback)
        if len(recent_returns) == 0:
            return 0.0
        
        mean = float(recent_returns.mean())
        std = float(recent_returns.std())
        
        if std <= 0:
            return 0.0
        
        # Z-score for confidence level
        z_score = {0.95: 1.65, 0.99: 2.33}.get(confidence, 1.65)
        var = abs(mean - z_score * std)
        return var
    
    def calculate_cvar(
        self,
        returns: pd.Series,
        confidence: float = 0.95,
        lookback: int = 100
    ) -> float:
        """Calculate Conditional VaR (Expected Shortfall)"""
        if len(returns) < lookback:
            lookback = len(returns)
        if lookback == 0:
            return 0.0
        
        recent_returns = returns.tail(lookback)
        if len(recent_returns) == 0:
            return 0.0
        
        var_threshold = self.calculate_historical_var(recent_returns, confidence, lookback)
        tail_losses = recent_returns[recent_returns <= -var_threshold]
        
        if len(tail_losses) == 0:
            return var_threshold
        
        cvar = float(abs(tail_losses.mean()))
        return cvar
    
    def calculate_portfolio_var(
        self,
        positions: Dict[str, Tuple[float, float]],  # symbol -> (qty, entry_px)
        returns_by_symbol: Dict[str, pd.Series],
        correlation_matrix: Optional[pd.DataFrame] = None
    ) -> Tuple[float, float, float]:
        """
        Calculate portfolio VaR considering correlations
        
        Returns: (var_95, var_99, cvar_95)
        """
        if not positions:
            return 0.0, 0.0, 0.0
        
        # Calculate individual position VaRs
        position_vars: Dict[str, float] = {}
        position_weights: Dict[str, float] = {}
        total_notional = 0.0
        
        for symbol, (qty, entry_px) in positions.items():
            if symbol not in returns_by_symbol:
                continue
            
            notional = abs(qty * entry_px)
            total_notional += notional
            position_weights[symbol] = notional
            
            returns = returns_by_symbol[symbol]
            var_95 = self.calculate_parametric_var(returns, confidence=0.95)
            position_vars[symbol] = var_95
        
        if total_notional == 0:
            return 0.0, 0.0, 0.0
        
        # Normalize weights
        for symbol in position_weights:
            position_weights[symbol] /= total_notional
        
        # Portfolio VaR with correlation
        if correlation_matrix is not None:
            symbols = list(position_weights.keys())
            if len(symbols) > 1:
                # Build covariance matrix
                var_vector = np.array([position_vars.get(s, 0.0) for s in symbols])
                weight_vector = np.array([position_weights[s] for s in symbols])

                # Extract correlation submatrix
                corr_submatrix = correlation_matrix.loc[symbols, symbols].values

                # Portfolio variance = w^T * Cov * w
                # Cov = diag(stds) * Corr * diag(stds)
                std_vector = var_vector / 1.65  # Convert VaR to std (approximate)
                cov_matrix = np.outer(std_vector, std_vector) * corr_submatrix
                portfolio_variance = weight_vector @ cov_matrix @ weight_vector
                portfolio_std = np.sqrt(max(0.0, portfolio_variance))

                # Convert back to VaR
                portfolio_var_95 = 1.65 * portfolio_std
                portfolio_var_99 = 2.33 * portfolio_std
            else:
                # Handle single symbol case
                var_vector = np.array([position_vars.get(s, 0.0) for s in symbols])
                portfolio_var_95 = var_vector[0] if len(var_vector) > 0 else 0.0
                portfolio_var_99 = portfolio_var_95 * (2.33 / 1.65)
        else:
            # Simple sum (no correlation)
            portfolio_var_95 = sum(position_vars.values())
            portfolio_var_99 = portfolio_var_95 * (2.33 / 1.65)
        
        # Calculate CVaR
        portfolio_cvar_95 = portfolio_var_95 * 1.2  # Approximate CVaR as 1.2x VaR
        
        return float(portfolio_var_95), float(portfolio_var_99), float(portfolio_cvar_95)
    
    def calculate_max_drawdown(self, equity_curve: pd.Series) -> float:
        """Calculate maximum drawdown from equity curve"""
        if len(equity_curve) == 0:
            return 0.0
        
        peak = equity_curve.expanding().max()
        drawdown = (equity_curve - peak) / peak
        max_dd = float(abs(drawdown.min())) if len(drawdown) > 0 else 0.0
        return max_dd
    
    def calculate_sharpe_ratio(
        self,
        returns: pd.Series,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252
    ) -> float:
        """Calculate Sharpe ratio"""
        if len(returns) < 2:
            return 0.0
        
        excess_returns = returns - risk_free_rate / periods_per_year
        if excess_returns.std() == 0:
            return 0.0
        
        sharpe = float(np.sqrt(periods_per_year) * excess_returns.mean() / excess_returns.std())
        return sharpe
    
    def calculate_sortino_ratio(
        self,
        returns: pd.Series,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252
    ) -> float:
        """Calculate Sortino ratio (downside deviation only)"""
        if len(returns) < 2:
            return 0.0
        
        excess_returns = returns - risk_free_rate / periods_per_year
        downside_returns = excess_returns[excess_returns < 0]
        
        if len(downside_returns) == 0 or downside_returns.std() == 0:
            return 0.0
        
        sortino = float(np.sqrt(periods_per_year) * excess_returns.mean() / downside_returns.std())
        return sortino
    
    def check_portfolio_risk_limits(
        self,
        positions: Dict[str, Tuple[float, float]],
        returns_by_symbol: Dict[str, pd.Series],
        correlation_matrix: Optional[pd.DataFrame] = None,
        current_equity: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Check if portfolio violates risk limits
        
        Returns: (is_violated, reason)
        """
        equity = current_equity or self.equity
        
        # Check maximum drawdown
        if len(self.equity_history) > 1:
            equity_series = pd.Series([e for _, e in self.equity_history])
            max_dd = self.calculate_max_drawdown(equity_series)
            if max_dd >= settings.strategy.risk_max_drawdown:
                return True, f"Maximum drawdown limit exceeded: {max_dd:.2%}"
        
        # Check portfolio VaR
        var_95, var_99, cvar_95 = self.calculate_portfolio_var(
            positions, returns_by_symbol, correlation_matrix
        )
        var_budget = settings.strategy.risk_var_95 * equity
        
        if var_95 > var_budget:
            return True, f"Portfolio VaR exceeds budget: ${var_95:.2f} > ${var_budget:.2f}"
        
        # Check daily loss limit
        if len(self.daily_pnl_history) > 0:
            today_pnl = sum(pnl for _, pnl in self.daily_pnl_history 
                          if (datetime.now() - _).days < 1)
            daily_loss_limit = settings.max_daily_loss_pct * equity
            if today_pnl < -daily_loss_limit:
                return True, f"Daily loss limit exceeded: ${abs(today_pnl):.2f}"
        
        # Check portfolio loss limit
        if len(self.equity_history) > 0:
            initial_equity = self.equity_history[0][1] if self.equity_history else equity
            current_equity_val = self.equity_history[-1][1] if self.equity_history else equity
            portfolio_loss_pct = (initial_equity - current_equity_val) / initial_equity
            if portfolio_loss_pct >= settings.max_portfolio_loss_pct:
                return True, f"Portfolio loss limit exceeded: {portfolio_loss_pct:.2%}"
        
        return False, ""
    
    def check_position_risk_limits(
        self,
        symbol: str,
        qty: float,
        price: float,
        returns: pd.Series,
        atr: float
    ) -> Tuple[bool, str]:
        """
        Check if a new position would violate risk limits
        
        Returns: (is_violated, reason)
        """
        notional = abs(qty * price)
        
        # Check per-trade notional cap
        if settings.per_trade_notional_cap_usd > 0:
            if notional > settings.per_trade_notional_cap_usd:
                return True, f"Position size exceeds per-trade cap: ${notional:.2f}"
        
        # Check per-symbol notional cap
        symbol_caps = settings.per_symbol_caps_map
        if symbol in symbol_caps:
            if notional > symbol_caps[symbol]:
                return True, f"Position size exceeds symbol cap: ${notional:.2f}"
        
        # Check position VaR
        position_var = self.calculate_parametric_var(returns, confidence=0.95)
        var_budget = settings.strategy.risk_var_95 * self.equity
        
        if position_var * notional / self.equity > var_budget:
            return True, f"Position VaR exceeds budget"
        
        return False, ""
    
    def update_equity_history(self, equity: float):
        """Update equity history for drawdown calculation"""
        self.equity_history.append((datetime.now(), equity))
        if equity > self.peak_equity:
            self.peak_equity = equity
        
        # Keep only last 1000 points
        if len(self.equity_history) > 1000:
            self.equity_history = self.equity_history[-1000:]
    
    def update_daily_pnl(self, pnl: float):
        """Update daily PnL history"""
        self.daily_pnl_history.append((datetime.now(), pnl))
        
        # Keep only last 30 days
        cutoff = datetime.now() - timedelta(days=30)
        self.daily_pnl_history = [
            (dt, pnl) for dt, pnl in self.daily_pnl_history if dt >= cutoff
        ]
    
    def calculate_position_risk_metrics(
        self,
        symbol: str,
        qty: float,
        entry_px: float,
        current_px: float,
        returns: pd.Series,
        atr: float
    ) -> PositionRisk:
        """Calculate comprehensive risk metrics for a position"""
        notional = abs(qty * current_px)
        unrealized_pnl = (current_px - entry_px) * qty
        
        # Calculate risk metrics
        var_95 = self.calculate_parametric_var(returns, confidence=0.95)
        var_99 = self.calculate_parametric_var(returns, confidence=0.99)
        cvar_95 = self.calculate_cvar(returns, confidence=0.95)
        
        volatility = float(returns.std()) if len(returns) > 0 else 0.0
        sharpe = self.calculate_sharpe_ratio(returns)
        sortino = self.calculate_sortino_ratio(returns)
        
        risk_metrics = RiskMetrics(
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            max_drawdown=0.0,  # Position-level drawdown not calculated here
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            volatility=volatility,
            atr=atr
        )
        
        return PositionRisk(
            symbol=symbol,
            qty=qty,
            entry_px=entry_px,
            current_px=current_px,
            notional=notional,
            unrealized_pnl=unrealized_pnl,
            risk_metrics=risk_metrics,
            correlation_with_portfolio=0.0  # Will be calculated at portfolio level
        )

