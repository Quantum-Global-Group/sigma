"""
Inference layer.

If a trained model exists at MODEL_DIR/{MODEL_VERSION}.{pkl|pt} it is loaded
on first call and used for all subsequent predictions. Otherwise we fall back
to a transparent rule-based heuristic (RSI + EMA + recent momentum) so the
API never returns errors purely from a missing model file.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


class SignalResult:
    def __init__(self, signal: str, confidence: float, predicted_return: float):
        self.signal = signal
        self.confidence = confidence
        self.predicted_return = predicted_return
        self.model_version = settings.model_version


_loaded_model = None  # type: ignore[var-annotated]
_load_attempted = False


def load_model(version: str | None = None):
    """Try to load a trained model from disk. Returns the model or None."""
    global _loaded_model, _load_attempted
    if _load_attempted:
        return _loaded_model
    _load_attempted = True

    version = version or settings.model_version
    model_dir = Path(settings.model_dir)

    # Try ensemble (.pkl) first, then LSTM (.pt)
    pkl_path = model_dir / f"ensemble_{version}.pkl"
    pt_path = model_dir / f"lstm_{version}.pt"
    qhybrid_path = model_dir / f"quantum_hybrid_{version}.pkl"

    if pkl_path.exists():
        try:
            from ml.models.ensemble import EnsembleSignalModel
            _loaded_model = EnsembleSignalModel.load(str(pkl_path))
            logger.info("Loaded ensemble model from %s", pkl_path)
            return _loaded_model
        except Exception as exc:
            logger.warning("Failed to load ensemble model: %s", exc)

    if pt_path.exists():
        try:
            from ml.models.lstm import LSTMSignalModel
            _loaded_model = LSTMSignalModel.load(str(pt_path))
            logger.info("Loaded LSTM model from %s", pt_path)
            return _loaded_model
        except Exception as exc:
            logger.warning("Failed to load LSTM model: %s", exc)

    if qhybrid_path.exists():
        try:
            from ml.models.quantum_hybrid import QuantumHybridModel
            _loaded_model = QuantumHybridModel.load(str(qhybrid_path))
            logger.info("Loaded quantum-hybrid model from %s", qhybrid_path)
            return _loaded_model
        except Exception as exc:
            logger.warning("Failed to load quantum-hybrid model: %s", exc)

    logger.info("No trained model found in %s — using rule-based heuristic", model_dir)
    return None


def _heuristic_predict(features: pd.DataFrame) -> SignalResult:
    """Fallback rule-based signal: RSI + EMA + 5-day momentum."""
    if features.empty:
        return SignalResult("HOLD", 0.5, 0.0)

    row = features.iloc[-1]
    rsi = row.get("rsi_14", 50.0)
    ema_ratio = row.get("ema_ratio", 1.0)
    ret_5d = row.get("ret_5d", 0.0)

    score = 0.0
    score += (50 - rsi) / 50 * 0.4
    score += (ema_ratio - 1.0) * 2.0 * 0.4
    score += np.clip(ret_5d * 5, -0.2, 0.2)

    confidence = float(np.clip(abs(score) * 1.5 + 0.35, 0.35, 0.95))
    predicted_return = float(np.clip(score * 0.05, -0.10, 0.10))

    if score > 0.15:
        signal = "BUY"
    elif score < -0.15:
        signal = "SELL"
    else:
        signal = "HOLD"

    return SignalResult(signal, round(confidence, 4), round(predicted_return, 6))


def predict(features: pd.DataFrame) -> SignalResult:
    model = load_model()
    if model is not None:
        try:
            return model.predict(features)
        except Exception as exc:
            logger.warning("Trained model predict failed: %s — using heuristic", exc)
    return _heuristic_predict(features)
