from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
from loguru import logger

from .config import settings


@dataclass
class Signal:
    """Trading signal with strength and confidence"""
    strength: float  # -1 to 1, where 1 is strong buy, -1 is strong sell
    confidence: float  # 0 to 1, confidence in the signal
    method: str  # Strategy method name
    metadata: Dict = None  # Additional strategy-specific data


class BaseStrategy(ABC):
    """Base class for all trading strategies"""
    
    def __init__(self, name: str):
        self.name = name
    
    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float
    ) -> Signal:
        """Generate trading signal for a symbol"""
        pass
    
    def should_trade(self, signal: Signal, min_confidence: float = 0.3) -> bool:
        """Determine if signal is strong enough to trade"""
        return abs(signal.strength) > 0.1 and signal.confidence >= min_confidence


class MomentumStrategy(BaseStrategy):
    """Momentum-based trading strategy"""
    
    def __init__(self):
        super().__init__("momentum")
        self.momentum_periods = [1, 3, 5, 10, 20]
        self.volume_confirmation = True
        self.min_volume_spike = 1.5
    
    def generate_signal(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float
    ) -> Signal:
        """Generate momentum signal"""
        if len(features) < max(self.momentum_periods):
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        last = features.iloc[-1]
        
        # Calculate momentum scores
        momentum_scores = []
        for period in self.momentum_periods:
            if len(features) >= period:
                ret = (features["c"].iloc[-1] / features["c"].iloc[-period] - 1.0)
                momentum_scores.append(ret)
        
        if not momentum_scores:
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        # Weighted momentum (more weight to shorter periods)
        weights = np.array([1.0 / (i + 1) for i in range(len(momentum_scores))])
        weights = weights / weights.sum()
        momentum_score = float(np.average(momentum_scores, weights=weights))
        
        # Volume confirmation
        volume_confirmed = True
        if self.volume_confirmation and "v" in features.columns:
            if len(features) >= 20:
                avg_volume = features["v"].tail(20).mean()
                current_volume = features["v"].iloc[-1]
                volume_spike = current_volume / avg_volume if avg_volume > 0 else 1.0
                volume_confirmed = volume_spike >= self.min_volume_spike
        
        # Trend strength (EMA alignment)
        trend_strength = 0.0
        if "ema_fast" in features.columns and "ema_slow" in features.columns:
            ema_fast = last["ema_fast"]
            ema_slow = last["ema_slow"]
            if ema_fast > ema_slow:
                trend_strength = min(1.0, (ema_fast - ema_slow) / ema_slow)
            else:
                trend_strength = max(-1.0, (ema_fast - ema_slow) / ema_slow)
        
        # Combine signals
        signal_strength = momentum_score * 10.0  # Scale to -1 to 1 range
        signal_strength = np.clip(signal_strength, -1.0, 1.0)
        
        # Adjust for trend alignment
        if signal_strength > 0 and trend_strength > 0:
            signal_strength *= (1.0 + trend_strength)
        elif signal_strength < 0 and trend_strength < 0:
            signal_strength *= (1.0 + abs(trend_strength))
        
        signal_strength = np.clip(signal_strength, -1.0, 1.0)
        
        # Confidence based on momentum consistency and volume
        confidence = min(1.0, abs(momentum_score) * 20.0)
        if not volume_confirmed:
            confidence *= 0.7
        
        return Signal(
            strength=float(signal_strength),
            confidence=float(confidence),
            method=self.name,
            metadata={
                "momentum_score": momentum_score,
                "trend_strength": trend_strength,
                "volume_confirmed": volume_confirmed
            }
        )


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion trading strategy"""
    
    def __init__(self):
        super().__init__("mean_reversion")
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.bb_period = 20
        self.bb_std = 2.0
    
    def generate_signal(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float
    ) -> Signal:
        """Generate mean reversion signal"""
        if len(features) < self.bb_period:
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        last = features.iloc[-1]
        
        # RSI-based signal
        rsi_signal = 0.0
        rsi_confidence = 0.0
        if "rsi" in features.columns:
            rsi = last["rsi"]
            if rsi < self.rsi_oversold:
                rsi_signal = 1.0  # Oversold, buy
                rsi_confidence = (self.rsi_oversold - rsi) / self.rsi_oversold
            elif rsi > self.rsi_overbought:
                rsi_signal = -1.0  # Overbought, sell
                rsi_confidence = (rsi - self.rsi_overbought) / (100 - self.rsi_overbought)
        
        # Bollinger Bands signal
        bb_signal = 0.0
        bb_confidence = 0.0
        if len(features) >= self.bb_period:
            prices = features["c"].tail(self.bb_period)
            sma = prices.mean()
            std = prices.std()
            
            upper_band = sma + self.bb_std * std
            lower_band = sma - self.bb_std * std
            
            if current_price < lower_band:
                bb_signal = 1.0  # Below lower band, buy
                bb_confidence = min(1.0, (lower_band - current_price) / (lower_band - sma))
            elif current_price > upper_band:
                bb_signal = -1.0  # Above upper band, sell
                bb_confidence = min(1.0, (current_price - upper_band) / (upper_band - sma))
        
        # Combine signals
        if rsi_signal == 0 and bb_signal == 0:
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        # Weighted combination
        if rsi_signal != 0 and bb_signal != 0:
            # Both agree
            if np.sign(rsi_signal) == np.sign(bb_signal):
                signal_strength = (rsi_signal + bb_signal) / 2.0
                confidence = (rsi_confidence + bb_confidence) / 2.0
            else:
                # Disagree, use stronger signal
                if rsi_confidence > bb_confidence:
                    signal_strength = rsi_signal
                    confidence = rsi_confidence * 0.5
                else:
                    signal_strength = bb_signal
                    confidence = bb_confidence * 0.5
        elif rsi_signal != 0:
            signal_strength = rsi_signal
            confidence = rsi_confidence
        else:
            signal_strength = bb_signal
            confidence = bb_confidence
        
        return Signal(
            strength=float(signal_strength),
            confidence=float(confidence),
            method=self.name,
            metadata={
                "rsi": last.get("rsi", 50.0),
                "bb_signal": bb_signal,
                "rsi_signal": rsi_signal
            }
        )


class BreakoutStrategy(BaseStrategy):
    """Breakout trading strategy"""
    
    def __init__(self):
        super().__init__("breakout")
        self.lookback_period = 20
        self.volume_threshold = 1.5
        self.volatility_expansion_threshold = 1.2
    
    def generate_signal(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float
    ) -> Signal:
        """Generate breakout signal"""
        if len(features) < self.lookback_period:
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        last = features.iloc[-1]
        
        # Support and resistance levels
        lookback_data = features.tail(self.lookback_period)
        resistance = lookback_data["h"].max()
        support = lookback_data["l"].min()
        
        # Check for breakout
        breakout_signal = 0.0
        breakout_confidence = 0.0
        
        # Resistance breakout (bullish)
        if current_price > resistance:
            breakout_signal = 1.0
            breakout_confidence = min(1.0, (current_price - resistance) / resistance)
        
        # Support breakdown (bearish)
        elif current_price < support:
            breakout_signal = -1.0
            breakout_confidence = min(1.0, (support - current_price) / support)
        
        if breakout_signal == 0:
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        # Volume confirmation
        volume_confirmed = True
        if "v" in features.columns and len(features) >= 20:
            avg_volume = features["v"].tail(20).mean()
            current_volume = features["v"].iloc[-1]
            volume_spike = current_volume / avg_volume if avg_volume > 0 else 1.0
            volume_confirmed = volume_spike >= self.volume_threshold
            if not volume_confirmed:
                breakout_confidence *= 0.6
        
        # Volatility expansion
        volatility_expansion = False
        if "vol_realized" in features.columns and len(features) >= 20:
            avg_vol = features["vol_realized"].tail(20).mean()
            current_vol = last["vol_realized"]
            volatility_expansion = current_vol >= avg_vol * self.volatility_expansion_threshold
            if volatility_expansion:
                breakout_confidence *= 1.2
                breakout_confidence = min(1.0, breakout_confidence)
        
        return Signal(
            strength=float(breakout_signal),
            confidence=float(breakout_confidence),
            method=self.name,
            metadata={
                "resistance": resistance,
                "support": support,
                "volume_confirmed": volume_confirmed,
                "volatility_expansion": volatility_expansion
            }
        )


class RegimeStrategy(BaseStrategy):
    """Enhanced regime detection strategy"""
    
    def __init__(self):
        super().__init__("regime")
    
    def generate_signal(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float
    ) -> Signal:
        """Generate regime-based signal"""
        if len(features) < 26:  # Need enough for EMA
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        last = features.iloc[-1]
        
        # Enhanced regime detection
        ema_fast = last.get("ema_fast", current_price)
        ema_slow = last.get("ema_slow", current_price)
        vol_realized = last.get("vol_realized", 0.0)
        
        # Regime classification
        if ema_fast > ema_slow and vol_realized < 0.05:
            regime = "bull"
            signal_strength = 1.0
            confidence = 0.7
        elif ema_fast < ema_slow and vol_realized > 0.05:
            regime = "bear"
            signal_strength = -1.0
            confidence = 0.7
        else:
            regime = "neutral"
            signal_strength = 0.0
            confidence = 0.3
        
        # Adjust confidence based on trend strength
        trend_strength = abs(ema_fast - ema_slow) / ema_slow if ema_slow > 0 else 0.0
        confidence = min(1.0, confidence + trend_strength)
        
        return Signal(
            strength=float(signal_strength),
            confidence=float(confidence),
            method=self.name,
            metadata={
                "regime": regime,
                "trend_strength": trend_strength,
                "volatility": vol_realized
            }
        )


class MLStrategy(BaseStrategy):
    """ML-based strategy (refactored from current approach)"""
    
    def __init__(self, model_predictions: Dict[str, float]):
        super().__init__("ml")
        self.model_predictions = model_predictions
    
    def generate_signal(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float
    ) -> Signal:
        """Generate ML-based signal"""
        if symbol not in self.model_predictions:
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        if len(features) < 50:
            return Signal(strength=0.0, confidence=0.0, method=self.name)
        
        # Get model prediction
        model_score = self.model_predictions[symbol]
        
        # Calculate confidence based on volatility
        last = features.iloc[-1]
        volatility = last.get("vol_realized", 0.0)
        
        # Higher volatility = lower confidence (for same signal strength)
        if volatility > 0:
            confidence = min(1.0, abs(model_score) / (volatility + 1e-6))
        else:
            confidence = abs(model_score)
        
        # Scale model score to -1 to 1 range
        signal_strength = float(np.clip(model_score * 10.0, -1.0, 1.0))
        
        return Signal(
            strength=signal_strength,
            confidence=float(confidence),
            method=self.name,
            metadata={
                "model_score": model_score,
                "volatility": volatility
            }
        )


class StrategyCombiner:
    """Combine signals from multiple strategies"""
    
    def __init__(self, strategies: Dict[str, BaseStrategy], weights: Dict[str, float]):
        self.strategies = strategies
        self.weights = weights
        
        # Normalize weights
        total_weight = sum(weights.values())
        if total_weight > 0:
            self.weights = {k: v / total_weight for k, v in weights.items()}
    
    def combine_signals(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float,
        model_predictions: Optional[Dict[str, float]] = None
    ) -> Signal:
        """Combine signals from all strategies"""
        signals: Dict[str, Signal] = {}
        
        for name, strategy in self.strategies.items():
            try:
                # Special handling for ML strategy
                if isinstance(strategy, MLStrategy) and model_predictions:
                    strategy.model_predictions = model_predictions
                
                signal = strategy.generate_signal(symbol, features, current_price)
                signals[name] = signal
            except Exception as e:
                logger.warning(f"Strategy {name} failed for {symbol}: {e}")
                continue
        
        if not signals:
            return Signal(strength=0.0, confidence=0.0, method="combined")
        
        # Weighted combination
        total_strength = 0.0
        total_confidence = 0.0
        
        for name, signal in signals.items():
            weight = self.weights.get(name, 0.0)
            total_strength += signal.strength * weight
            total_confidence += signal.confidence * weight
        
        # Clip to valid range
        combined_strength = float(np.clip(total_strength, -1.0, 1.0))
        combined_confidence = float(np.clip(total_confidence, 0.0, 1.0))
        
        return Signal(
            strength=combined_strength,
            confidence=combined_confidence,
            method="combined",
            metadata={"component_signals": {name: s.strength for name, s in signals.items()}}
        )

