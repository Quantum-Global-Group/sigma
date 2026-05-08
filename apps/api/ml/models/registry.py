"""Model registry — resolves a `BaseSignalModel` by (asset_class, name).

Artifact naming convention on disk:
    {settings.model_dir}/{asset_class}_{model_type}_{version}.{pkl|pt}

Example:
    saved_models/equity_ensemble_v1.0.pkl
    saved_models/crypto_ranking_v1.0.pkl

Load order per asset class is configurable but defaults to the order below.
A failed load (missing or corrupt artifact) advances to the next entry; if
nothing loads, callers fall back to `_heuristic_predict` in `inference.py`."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


_DEFAULT_ORDER: dict[str, list[str]] = {
    # Equities: ensemble first (RF+XGB), then LSTM, then quantum-hybrid
    "equity": ["ensemble", "lstm", "quantum_hybrid"],
    # Crypto: razorBill RankingModel (LightGBM) first, then ensemble fallback
    "crypto": ["ranking", "ensemble"],
}


def _path_for(asset_class: str, model_type: str, version: str) -> Path:
    return Path(settings.model_dir) / f"{asset_class}_{model_type}_{version}.{_ext(model_type)}"


def _legacy_path_for(model_type: str, version: str) -> Path:
    """Pre-asset-class artifact layout (used by sigma before the merge)."""
    return Path(settings.model_dir) / f"{model_type}_{version}.{_ext(model_type)}"


def _ext(model_type: str) -> str:
    return "pt" if model_type == "lstm" else "pkl"


def _load_one(model_type: str, path: Path):
    if model_type == "ensemble":
        from ml.models.ensemble import EnsembleSignalModel
        return EnsembleSignalModel.load(str(path))
    if model_type == "lstm":
        from ml.models.lstm import LSTMSignalModel
        return LSTMSignalModel.load(str(path))
    if model_type == "quantum_hybrid":
        from ml.models.quantum_hybrid import QuantumHybridModel
        return QuantumHybridModel.load(str(path))
    if model_type == "ranking":
        from ml.models.ranking import RankingModel
        return RankingModel.load(str(path))
    raise ValueError(f"Unknown model_type: {model_type!r}")


_cache: dict[tuple[str, str], object] = {}


def resolve(asset_class: str, version: Optional[str] = None):
    """Return the first loadable model for the given asset class, or None."""
    version = version or settings.model_version
    key = (asset_class, version)
    if key in _cache:
        return _cache[key]

    for model_type in _DEFAULT_ORDER.get(asset_class, []):
        path = _path_for(asset_class, model_type, version)
        if not path.exists():
            # Back-compat: equity artifacts saved under the legacy naming
            legacy = _legacy_path_for(model_type, version)
            if legacy.exists():
                path = legacy
            else:
                continue
        try:
            model = _load_one(model_type, path)
            logger.info("Loaded %s model for %s from %s", model_type, asset_class, path)
            _cache[key] = model
            return model
        except Exception as exc:
            logger.warning("Failed to load %s for %s: %s", model_type, asset_class, exc)

    logger.info("No trained model for asset_class=%s — heuristic fallback", asset_class)
    _cache[key] = None
    return None


def clear_cache() -> None:
    _cache.clear()
