from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime

import logging

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class TimeframeSignal:
    """Signal from a specific timeframe"""
    timeframe: str
    trend: str  # "bullish", "bearish", "neutral"
    strength: float  # -1 to 1
    confidence: float  # 0 to 1


@dataclass
class MultiTimeframeAnalysis:
    """Multi-timeframe analysis result"""
    primary_signal: float  # Combined signal from all timeframes
    timeframe_signals: Dict[str, TimeframeSignal]
    alignment_score: float  # How well timeframes align (0-1)
    recommendation: str  # "strong_buy", "buy", "neutral", "sell", "strong_sell"


class MultiTimeframeAnalyzer:
    """Analyze multiple timeframes for trading signals"""
    
    def __init__(self, primary_timeframe: str = "5m"):
        self.primary_timeframe = primary_timeframe
        self.timeframes = ["5m", "15m", "1h", "4h"]  # Lower to higher
    
    def detect_trend(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> TimeframeSignal:
        """
        Detect trend for a specific timeframe
        
        Args:
            df: DataFrame with OHLCV data
            timeframe: Timeframe name (for labeling)
        """
        if len(df) < 26:  # Need enough for EMAs
            return TimeframeSignal(
                timeframe=timeframe,
                trend="neutral",
                strength=0.0,
                confidence=0.0
            )
        
        last = df.iloc[-1]
        
        # Calculate EMAs if not present
        if "ema_fast" not in df.columns:
            df["ema_fast"] = df["c"].ewm(span=12, adjust=False).mean()
            df["ema_slow"] = df["c"].ewm(span=26, adjust=False).mean()
            last = df.iloc[-1]
        
        ema_fast = last["ema_fast"]
        ema_slow = last["ema_slow"]
        price = last["c"]
        
        # Trend direction
        if ema_fast > ema_slow and price > ema_fast:
            trend = "bullish"
            strength = min(1.0, (ema_fast - ema_slow) / ema_slow if ema_slow > 0 else 0.0)
        elif ema_fast < ema_slow and price < ema_fast:
            trend = "bearish"
            strength = min(1.0, (ema_slow - ema_fast) / ema_fast if ema_fast > 0 else 0.0)
        else:
            trend = "neutral"
            strength = 0.0
        
        # Confidence based on price distance from EMAs and volume
        price_distance = abs(price - ema_fast) / price if price > 0 else 0.0
        confidence = min(1.0, strength + price_distance * 0.5)
        
        # Adjust strength based on trend
        if trend == "bullish":
            signal_strength = strength
        elif trend == "bearish":
            signal_strength = -strength
        else:
            signal_strength = 0.0
        
        return TimeframeSignal(
            timeframe=timeframe,
            trend=trend,
            strength=float(signal_strength),
            confidence=float(confidence)
        )
    
    def analyze_timeframes(
        self,
        data_by_timeframe: Dict[str, pd.DataFrame]
    ) -> MultiTimeframeAnalysis:
        """
        Analyze all timeframes and combine signals
        
        Args:
            data_by_timeframe: Dict mapping timeframe names to DataFrames
        """
        timeframe_signals: Dict[str, TimeframeSignal] = {}
        
        # Analyze each timeframe
        for tf in self.timeframes:
            if tf in data_by_timeframe:
                df = data_by_timeframe[tf]
                signal = self.detect_trend(df, tf)
                timeframe_signals[tf] = signal
            else:
                # Create neutral signal if data not available
                timeframe_signals[tf] = TimeframeSignal(
                    timeframe=tf,
                    trend="neutral",
                    strength=0.0,
                    confidence=0.0
                )
        
        # Calculate alignment score
        alignment_score = self._calculate_alignment(timeframe_signals)
        
        # Combine signals with weights (higher timeframes get more weight)
        weights = {
            "5m": 0.1,
            "15m": 0.2,
            "1h": 0.3,
            "4h": 0.4
        }
        
        combined_strength = 0.0
        total_weight = 0.0
        
        for tf, signal in timeframe_signals.items():
            weight = weights.get(tf, 0.1)
            combined_strength += signal.strength * weight * signal.confidence
            total_weight += weight * signal.confidence
        
        if total_weight > 0:
            primary_signal = combined_strength / total_weight
        else:
            primary_signal = 0.0
        
        primary_signal = float(np.clip(primary_signal, -1.0, 1.0))
        
        # Generate recommendation
        recommendation = self._generate_recommendation(primary_signal, alignment_score)
        
        return MultiTimeframeAnalysis(
            primary_signal=primary_signal,
            timeframe_signals=timeframe_signals,
            alignment_score=alignment_score,
            recommendation=recommendation
        )
    
    def _calculate_alignment(self, signals: Dict[str, TimeframeSignal]) -> float:
        """Calculate how well timeframes align"""
        if not signals:
            return 0.0
        
        # Count bullish, bearish, neutral
        bullish_count = sum(1 for s in signals.values() if s.trend == "bullish")
        bearish_count = sum(1 for s in signals.values() if s.trend == "bearish")
        neutral_count = sum(1 for s in signals.values() if s.trend == "neutral")
        
        total = len(signals)
        if total == 0:
            return 0.0
        
        # Alignment is highest when all agree
        max_agreement = max(bullish_count, bearish_count, neutral_count)
        alignment = max_agreement / total
        
        # Boost alignment if higher timeframes agree
        higher_tf_signals = [signals.get(tf) for tf in ["1h", "4h"] if tf in signals]
        if higher_tf_signals:
            higher_tf_trends = [s.trend for s in higher_tf_signals if s]
            if len(set(higher_tf_trends)) == 1:  # All higher TFs agree
                alignment = min(1.0, alignment + 0.2)
        
        return float(alignment)
    
    def _generate_recommendation(
        self,
        signal_strength: float,
        alignment_score: float
    ) -> str:
        """Generate trading recommendation"""
        # Require minimum alignment for strong signals
        if alignment_score < 0.5:
            return "neutral"
        
        if signal_strength >= 0.7 and alignment_score >= 0.7:
            return "strong_buy"
        elif signal_strength >= 0.3:
            return "buy"
        elif signal_strength <= -0.7 and alignment_score >= 0.7:
            return "strong_sell"
        elif signal_strength <= -0.3:
            return "sell"
        else:
            return "neutral"
    
    def filter_by_higher_timeframe(
        self,
        entry_signal: float,
        higher_timeframe_analysis: MultiTimeframeAnalysis,
        min_alignment: float = 0.6
    ) -> Tuple[bool, float]:
        """
        Filter entry signals by higher timeframe trend
        
        Returns: (should_trade, adjusted_signal)
        """
        # Don't trade against higher timeframe trend
        htf_signal = higher_timeframe_analysis.primary_signal
        
        # If higher timeframe is bearish, don't take long entries
        if entry_signal > 0 and htf_signal < -0.3:
            return False, 0.0
        
        # If higher timeframe is bullish, don't take short entries (for long-only)
        if entry_signal < 0 and htf_signal > 0.3:
            return False, 0.0
        
        # Boost signal if higher timeframe agrees
        if np.sign(entry_signal) == np.sign(htf_signal):
            adjusted_signal = entry_signal * (1.0 + abs(htf_signal) * 0.5)
            adjusted_signal = float(np.clip(adjusted_signal, -1.0, 1.0))
        else:
            adjusted_signal = entry_signal * 0.5  # Reduce if disagree
        
        # Check alignment
        if higher_timeframe_analysis.alignment_score < min_alignment:
            return False, 0.0
        
        return True, adjusted_signal


def resample_to_timeframe(
    df: pd.DataFrame,
    target_timeframe: str
) -> pd.DataFrame:
    """
    Resample DataFrame to target timeframe
    
    Args:
        df: DataFrame with OHLCV data and datetime index
        target_timeframe: Target timeframe (e.g., "5m", "15m", "1h", "4h")
    """
    if "t" not in df.columns:
        logger.warning("DataFrame must have 't' column for resampling")
        return df
    
    # Set datetime index
    df_resampled = df.set_index("t").copy()
    
    # Resample OHLCV
    ohlc_dict = {
        "o": "first",
        "h": "max",
        "l": "min",
        "c": "last",
        "v": "sum"
    }
    
    # Keep other columns if they exist
    other_cols = [col for col in df_resampled.columns if col not in ohlc_dict]
    
    resampled = df_resampled.resample(target_timeframe).agg(ohlc_dict)
    
    # Re-add other columns (take last value)
    for col in other_cols:
        resampled[col] = df_resampled[col].resample(target_timeframe).last()
    
    resampled = resampled.dropna(subset=["c"])
    resampled = resampled.reset_index()
    
    return resampled

