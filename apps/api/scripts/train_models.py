#!/usr/bin/env python
"""
Offline model training for SIGMA.

Usage:
    python scripts/train_models.py [--ensemble] [--lstm] [--quantum-hybrid] [--all]

Defaults to ensemble only (fastest, ~60s on CPU). Run with --all for the full
training suite (LSTM ~10 min CPU; quantum-hybrid ~20 min CPU due to kernel matrix).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# Resolve imports relative to apps/api
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from ml.data import fetch_ohlcv
from ml.features import build_features
from ml.models.base import label_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_models")

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "WMT"]


def build_training_set(tickers: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    """Combine features + labels across tickers into a single training set."""
    X_parts: list[pd.DataFrame] = []
    y_parts: list[np.ndarray] = []

    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker, "daily")
        except Exception as exc:
            logger.warning("Skipping %s: %s", ticker, exc)
            continue

        features = build_features(df)
        if features.empty:
            continue

        # Future 1-day return is the supervisory signal
        future_return = df["close"].pct_change().shift(-1).reindex(features.index).fillna(0.0)
        labels = label_signals(future_return, threshold=0.005)

        # Drop the last row — no future return available
        features = features.iloc[:-1]
        labels = labels[:-1]

        X_parts.append(features)
        y_parts.append(labels)
        logger.info("Loaded %d samples for %s", len(features), ticker)

    if not X_parts:
        raise RuntimeError("No training data fetched")

    X = pd.concat(X_parts, ignore_index=True)
    y = np.concatenate(y_parts)
    logger.info("Total training set: %d samples, %d features", len(X), X.shape[1])
    return X, y


def train_ensemble(X: pd.DataFrame, y: np.ndarray, version: str) -> str:
    from ml.models.ensemble import EnsembleSignalModel

    out_path = os.path.join(settings.model_dir, f"ensemble_{version}.pkl")
    os.makedirs(settings.model_dir, exist_ok=True)

    model = EnsembleSignalModel()
    model.train(X, y)
    model.save(out_path)
    logger.info("Saved ensemble model → %s", out_path)
    return out_path


def train_lstm(X: pd.DataFrame, y: np.ndarray, version: str) -> str:
    from ml.models.lstm import LSTMSignalModel

    out_path = os.path.join(settings.model_dir, f"lstm_{version}.pt")
    os.makedirs(settings.model_dir, exist_ok=True)

    model = LSTMSignalModel(n_features=X.shape[1])
    model.train(X, y, epochs=20)
    model.save(out_path)
    logger.info("Saved LSTM model → %s", out_path)
    return out_path


def train_quantum_hybrid(X: pd.DataFrame, y: np.ndarray, version: str) -> str:
    from ml.models.quantum_hybrid import QuantumHybridModel

    out_path = os.path.join(settings.model_dir, f"quantum_hybrid_{version}.pkl")
    os.makedirs(settings.model_dir, exist_ok=True)

    # Quantum kernel scales O(n²) — subsample if dataset is large
    if len(X) > 500:
        idx = np.random.RandomState(42).choice(len(X), 500, replace=False)
        X_sub = X.iloc[idx].reset_index(drop=True)
        y_sub = y[idx]
    else:
        X_sub, y_sub = X, y

    model = QuantumHybridModel()
    model.train(X_sub, y_sub)
    model.save(out_path)
    logger.info("Saved quantum-hybrid model → %s", out_path)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ensemble", action="store_true", help="Train ensemble model")
    parser.add_argument("--lstm", action="store_true", help="Train LSTM model")
    parser.add_argument("--quantum-hybrid", action="store_true", help="Train quantum-hybrid model")
    parser.add_argument("--all", action="store_true", help="Train all models")
    parser.add_argument("--version", default=settings.model_version)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    args = parser.parse_args()

    if not (args.ensemble or args.lstm or args.quantum_hybrid or args.all):
        args.ensemble = True  # default

    X, y = build_training_set(args.tickers)

    if args.all or args.ensemble:
        train_ensemble(X, y, args.version)
    if args.all or args.lstm:
        train_lstm(X, y, args.version)
    if args.all or args.quantum_hybrid:
        train_quantum_hybrid(X, y, args.version)


if __name__ == "__main__":
    main()
