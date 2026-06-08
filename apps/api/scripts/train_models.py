#!/usr/bin/env python
"""
Offline model training for SIGMA — asset-class-parameterized, MLflow-tracked.

Usage:
    python scripts/train_models.py [--ensemble] [--lstm] [--quantum-hybrid] [--all]
    python scripts/train_models.py --asset-class forex --symbols EUR_USD GBP_USD
    python scripts/train_models.py --asset-class equity --version v1.1

Defaults to ensemble only (fastest, ~60s on CPU). Run with --all for the full
suite (LSTM ~10 min CPU; quantum-hybrid ~20 min CPU due to the kernel matrix).

Each run logs params/metrics/artifacts to MLflow (local ./mlruns by default;
set MLFLOW_TRACKING_URI for a server) and writes a model-card JSON next to the
artifact so lineage exists even when MLflow is unavailable. Artifacts use the
registry's asset-class-prefixed naming: {asset_class}_{model_type}_{version}.{ext}.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# Resolve imports relative to apps/api
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from markets import get_market_adapter
from ml.experiment import start_run
from ml.features import build_features
from ml.models.base import label_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_models")

# Per-asset-class training defaults (symbols + bar timeframe).
_DEFAULTS = {
    "equity": (["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "WMT"], "daily"),
    "crypto": (["BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", "AVAX-USD"], "5m"),
    "forex": (["EUR_USD", "GBP_USD", "AUD_USD", "USD_JPY", "USD_CAD"], "4h"),
}


def _defaults_for(asset_class: str) -> tuple[list[str], str]:
    return _DEFAULTS.get(asset_class, (_DEFAULTS["equity"][0], "daily"))


def build_training_set(
    symbols: list[str], asset_class: str, timeframe: str, threshold: float = 0.005,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Combine features + labels across symbols into a single training set.

    Pulls bars via the same MarketAdapter the worker trades on, so training and
    serving share the exact data path."""
    adapter = get_market_adapter(asset_class)
    X_parts: list[pd.DataFrame] = []
    y_parts: list[np.ndarray] = []

    for symbol in symbols:
        try:
            df = adapter.fetch_ohlcv(symbol, timeframe)
        except Exception as exc:
            logger.warning("Skipping %s: %s", symbol, exc)
            continue

        features = build_features(df)
        if features.empty:
            continue

        future_return = df["close"].pct_change().shift(-1).reindex(features.index).fillna(0.0)
        labels = label_signals(future_return, threshold=threshold)

        features = features.iloc[:-1]   # drop last row — no future return
        labels = labels[:-1]

        X_parts.append(features)
        y_parts.append(labels)
        logger.info("Loaded %d samples for %s", len(features), symbol)

    if not X_parts:
        raise RuntimeError("No training data fetched")

    X = pd.concat(X_parts, ignore_index=True)
    y = np.concatenate(y_parts)
    logger.info("Total training set: %d samples, %d features", len(X), X.shape[1])
    return X, y


def _artifact_path(asset_class: str, model_type: str, version: str, ext: str) -> str:
    os.makedirs(settings.model_dir, exist_ok=True)
    return os.path.join(settings.model_dir, f"{asset_class}_{model_type}_{version}.{ext}")


def _class_balance(y: np.ndarray) -> dict:
    vals, counts = np.unique(y, return_counts=True)
    names = {0: "sell", 1: "hold", 2: "buy"}
    total = max(1, len(y))
    return {f"class_{names.get(int(v), v)}_frac": round(int(c) / total, 4) for v, c in zip(vals, counts)}


def _split(X: pd.DataFrame, y: np.ndarray, val_frac: float = 0.2):
    """Chronological (walk-forward) holdout — NO shuffle.

    A random/stratified split leaks adjacent bars (bar t in train, t+1 in val)
    so the model memorizes and posts implausible accuracy (e.g. 0.99). Training
    on the earlier rows and validating on the most-recent tail gives an honest
    out-of-sample estimate that reflects how the model will actually trade."""
    from sklearn.model_selection import train_test_split
    return train_test_split(X, y, test_size=val_frac, shuffle=False)


def _write_model_card(path_no_ext: str, card: dict) -> str:
    card_path = f"{path_no_ext}.card.json"
    with open(card_path, "w") as fh:
        json.dump(card, fh, indent=2, default=str)
    logger.info("Wrote model card → %s", card_path)
    return card_path


def _base_card(asset_class, model_type, version, symbols, timeframe, threshold, X, y, extra=None) -> dict:
    card = {
        "asset_class": asset_class,
        "model_type": model_type,
        "version": version,
        "symbols": symbols,
        "timeframe": timeframe,
        "label_threshold": threshold,
        "n_samples": int(len(X)),
        "n_features": int(X.shape[1]),
        "feature_names": list(X.columns),
        "class_balance": _class_balance(y),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        card.update(extra)
    return card


def train_ensemble(X, y, *, asset_class, version, symbols, timeframe, threshold) -> str:
    from sklearn.metrics import accuracy_score
    from ml.models.ensemble import EnsembleSignalModel

    out_path = _artifact_path(asset_class, "ensemble", version, "pkl")
    X_tr, X_val, y_tr, y_val = _split(X, y)

    model = EnsembleSignalModel()
    model.train(X_tr, y_tr)

    # Batch validation accuracy via the ensemble's soft vote (rf + xgb).
    rf_p = model.rf.predict_proba(X_val.values)
    xgb_p = model.xgb.predict_proba(X_val.values)
    val_pred = np.argmax((rf_p + xgb_p) / 2.0, axis=1)
    val_acc = float(accuracy_score(y_val, val_pred))
    train_pred = np.argmax(
        (model.rf.predict_proba(X_tr.values) + model.xgb.predict_proba(X_tr.values)) / 2.0, axis=1
    )
    train_acc = float(accuracy_score(y_tr, train_pred))

    model.save(out_path)
    logger.info("Saved ensemble → %s (val_acc=%.3f)", out_path, val_acc)

    metrics = {"train_accuracy": train_acc, "val_accuracy": val_acc,
               "n_train": len(X_tr), "n_val": len(X_val)}
    card = _base_card(asset_class, "ensemble", version, symbols, timeframe, threshold, X,
                      y, extra={"metrics": metrics, "artifact": out_path})
    card_path = _write_model_card(out_path[:-4], card)

    with start_run(f"ensemble-{asset_class}-{version}",
                   tags={"asset_class": asset_class, "model_type": "ensemble"}) as run:
        run.log_params({"asset_class": asset_class, "model_type": "ensemble", "version": version,
                        "symbols": ",".join(symbols), "timeframe": timeframe, "threshold": threshold,
                        "n_samples": len(X), "n_features": X.shape[1]})
        run.log_metrics({**metrics, **_class_balance(y)})
        run.log_artifact(out_path)
        run.log_artifact(card_path)
    return out_path


def train_lstm(X, y, *, asset_class, version, symbols, timeframe, threshold) -> str:
    from ml.models.lstm import LSTMSignalModel

    out_path = _artifact_path(asset_class, "lstm", version, "pt")
    model = LSTMSignalModel(n_features=X.shape[1])
    model.train(X, y, epochs=20)
    model.save(out_path)
    logger.info("Saved LSTM → %s", out_path)

    card = _base_card(asset_class, "lstm", version, symbols, timeframe, threshold, X, y,
                      extra={"epochs": 20, "artifact": out_path})
    card_path = _write_model_card(out_path[:-3], card)

    with start_run(f"lstm-{asset_class}-{version}",
                   tags={"asset_class": asset_class, "model_type": "lstm"}) as run:
        run.log_params({"asset_class": asset_class, "model_type": "lstm", "version": version,
                        "symbols": ",".join(symbols), "timeframe": timeframe, "epochs": 20,
                        "n_samples": len(X), "n_features": X.shape[1]})
        run.log_metrics(_class_balance(y))
        run.log_artifact(out_path)
        run.log_artifact(card_path)
    return out_path


def train_quantum_hybrid(X, y, *, asset_class, version, symbols, timeframe, threshold) -> str:
    from ml.models.quantum_hybrid import QuantumHybridModel

    out_path = _artifact_path(asset_class, "quantum_hybrid", version, "pkl")
    if len(X) > 500:  # quantum kernel is O(n²) — subsample
        idx = np.random.RandomState(42).choice(len(X), 500, replace=False)
        X_sub, y_sub = X.iloc[idx].reset_index(drop=True), y[idx]
    else:
        X_sub, y_sub = X, y

    model = QuantumHybridModel()
    model.train(X_sub, y_sub)
    model.save(out_path)
    logger.info("Saved quantum-hybrid → %s", out_path)

    card = _base_card(asset_class, "quantum_hybrid", version, symbols, timeframe, threshold,
                      X_sub, y_sub, extra={"subsampled": len(X) > 500, "artifact": out_path})
    card_path = _write_model_card(out_path[:-4], card)

    with start_run(f"quantum_hybrid-{asset_class}-{version}",
                   tags={"asset_class": asset_class, "model_type": "quantum_hybrid"}) as run:
        run.log_params({"asset_class": asset_class, "model_type": "quantum_hybrid", "version": version,
                        "symbols": ",".join(symbols), "timeframe": timeframe,
                        "n_samples": len(X_sub), "n_features": X_sub.shape[1]})
        run.log_metrics(_class_balance(y_sub))
        run.log_artifact(out_path)
        run.log_artifact(card_path)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ensemble", action="store_true", help="Train ensemble model")
    parser.add_argument("--lstm", action="store_true", help="Train LSTM model")
    parser.add_argument("--quantum-hybrid", action="store_true", help="Train quantum-hybrid model")
    parser.add_argument("--all", action="store_true", help="Train all models")
    parser.add_argument("--asset-class", default="equity", choices=sorted(_DEFAULTS.keys()))
    parser.add_argument("--version", default=settings.model_version)
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Override the per-asset-class default symbol list")
    parser.add_argument("--timeframe", default=None, help="Override the per-asset-class default timeframe")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Label threshold for BUY/SELL (default: per-asset from settings: "
                             "equity=0.005, forex=0.001, crypto=0.005)")
    args = parser.parse_args()

    if not (args.ensemble or args.lstm or args.quantum_hybrid or args.all):
        args.ensemble = True  # default

    default_symbols, default_tf = _defaults_for(args.asset_class)
    symbols = args.symbols or default_symbols
    timeframe = args.timeframe or default_tf

    # Per-asset-class label threshold: equity/crypto use 0.5% (daily moves), forex uses
    # 0.1% (4h bars typically move 0.07-0.17% median — 0.5% would label 98%+ as HOLD).
    _thresh_defaults = {
        "equity": settings.label_threshold_equity,
        "forex": settings.label_threshold_forex,
        "crypto": settings.label_threshold_crypto,
    }
    threshold = args.threshold if args.threshold is not None else _thresh_defaults.get(args.asset_class, 0.005)

    logger.info("Training asset_class=%s version=%s symbols=%s timeframe=%s threshold=%.4f",
                args.asset_class, args.version, symbols, timeframe, threshold)
    X, y = build_training_set(symbols, args.asset_class, timeframe, threshold=threshold)

    kw = dict(asset_class=args.asset_class, version=args.version, symbols=symbols,
              timeframe=timeframe, threshold=threshold)
    if args.all or args.ensemble:
        train_ensemble(X, y, **kw)
    if args.all or args.lstm:
        train_lstm(X, y, **kw)
    if args.all or args.quantum_hybrid:
        train_quantum_hybrid(X, y, **kw)


if __name__ == "__main__":
    main()
