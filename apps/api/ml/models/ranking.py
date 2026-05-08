"""RankingModel — sequence-based regression of next-N-bar returns.

Body ported from razorBill `models.py::RankingModel`. Adapted to sigma's
`BaseSignalModel` interface: predict() takes a feature DataFrame (or raw
OHLCV) and returns a `SignalResult` with BUY/SELL/HOLD bucketed from the
predicted return via `settings.ranking_signal_threshold`.

Backend selection: LightGBM > XGBoost > SGDRegressor (fallback).

Training entry point is `fit_from_ohlcv(df_or_dfs)`; the BaseSignalModel
`train(X, y)` contract is preserved for compatibility but is a thin
wrapper that requires pre-built sequences."""

from __future__ import annotations

import logging
import pickle
from typing import Iterable, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from config import settings
from ml.inference import SignalResult
from ml.models.base import BaseSignalModel
from ml.sequences import FEATURE_COLUMNS, FeatureEngineer, Sequence, SequenceBuilder

logger = logging.getLogger(__name__)

try:
    import lightgbm as lgb  # type: ignore
    _HAS_LGB = True
except Exception:  # pragma: no cover
    _HAS_LGB = False

try:
    import xgboost as xgb  # type: ignore
    _HAS_XGB = True
except Exception:  # pragma: no cover
    _HAS_XGB = False


class RankingModel(BaseSignalModel):
    model_version = "ranking-v1"

    def __init__(self) -> None:
        self.backend = self._select_backend()
        self.model = self._init_model(self.backend)
        self.feature_engineer = FeatureEngineer()
        self.sequence_builder = SequenceBuilder(window=int(settings.ranking_window))
        self._trained = False

    # ---- backend selection -------------------------------------------------

    @staticmethod
    def _select_backend() -> str:
        if _HAS_LGB:
            return "lgb"
        if _HAS_XGB:
            return "xgb"
        return "sgd"

    def _init_model(self, backend: str):
        if backend == "lgb":
            return lgb.LGBMRegressor(
                n_estimators=int(settings.lgb_n_estimators),
                learning_rate=float(settings.lgb_learning_rate),
                max_depth=int(settings.lgb_max_depth),
                subsample=float(settings.lgb_subsample),
                colsample_bytree=float(settings.lgb_colsample_bytree),
                reg_alpha=float(settings.lgb_reg_alpha),
                reg_lambda=float(settings.lgb_reg_lambda),
                random_state=42,
            )
        if backend == "xgb":
            # XGBoost 2.0+ moved early_stopping_rounds from fit() to the
            # constructor. Set it here so fit() can stay simple and version-
            # tolerant. eval_set still has to be passed at fit() time.
            return xgb.XGBRegressor(
                n_estimators=int(settings.xgb_n_estimators),
                learning_rate=float(settings.xgb_learning_rate),
                max_depth=int(settings.xgb_max_depth),
                subsample=float(settings.xgb_subsample),
                colsample_bytree=float(settings.xgb_colsample_bytree),
                reg_alpha=float(settings.xgb_reg_alpha),
                reg_lambda=float(settings.xgb_reg_lambda),
                random_state=42,
                tree_method="hist",
                n_jobs=0,
                early_stopping_rounds=50,
            )
        from sklearn.linear_model import SGDRegressor
        return SGDRegressor(max_iter=1000, tol=1e-3)

    # ---- training ----------------------------------------------------------

    def fit_from_ohlcv(self, ohlcv: pd.DataFrame | Iterable[pd.DataFrame]) -> None:
        """Fit on one DataFrame (single symbol) or many (multi-symbol).

        Multi-symbol training is symbol-aware:
          * Features are computed per symbol (so labels and sequences never
            straddle symbol boundaries).
          * The scaler is fit ONCE on the concatenated feature matrix so all
            sequences share a common scaling — fixes the bug where the old
            implementation refit the scaler per symbol and only the last
            symbol's distribution survived.
          * Sequences are then built per symbol using the already-fit scaler
            in transform-only mode."""
        if isinstance(ohlcv, pd.DataFrame):
            ohlcv = [ohlcv]
        ohlcv = list(ohlcv)
        if not ohlcv:
            return

        horizon = int(settings.pred_horizon_bars)
        window = self.sequence_builder.window

        # Pass 1 — per-symbol features + labels.
        labeled: list[pd.DataFrame] = []
        for df in ohlcv:
            feats = self.feature_engineer.compute(df)
            feats = feats.dropna(subset=FEATURE_COLUMNS + ["c"]).copy()
            feats["y"] = feats["c"].pct_change(horizon).shift(-horizon)
            feats = feats.dropna(subset=["y"])
            if len(feats) < window:
                continue
            labeled.append(feats)
        if not labeled:
            return

        # Fit the scaler once on all features.
        all_X = np.vstack([f[FEATURE_COLUMNS].values.astype(np.float32) for f in labeled])
        self.sequence_builder.scaler.fit(all_X)
        self.sequence_builder._fitted = True

        # Pass 2 — build sequences per symbol using the shared scaler.
        all_seqs: list[Sequence] = []
        for feats in labeled:
            X_full = feats[FEATURE_COLUMNS].values.astype(np.float32)
            X_scaled = self.sequence_builder.scaler.transform(X_full)
            for i in range(window, len(feats)):
                Xw = X_scaled[i - window : i, :]
                y = float(feats.iloc[i]["y"])
                meta = {
                    "symbol": feats.iloc[i].get("symbol", ""),
                    "window": window,
                    "t": feats.iloc[i].get("t"),
                }
                all_seqs.append(Sequence(X=Xw, y=y, meta=meta))

        self.fit(all_seqs)

    def fit(self, sequences: list[Sequence]) -> None:
        if not sequences:
            return
        X = np.array([s.X.flatten() for s in sequences], dtype=np.float32)
        y = np.array([s.y for s in sequences], dtype=np.float32)

        if self.backend in ("lgb", "xgb") and len(X) > 100:
            split = int(0.8 * len(X))
            X_tr, X_val = X[:split], X[split:]
            y_tr, y_val = y[:split], y[split:]
            if self.backend == "lgb":
                self.model.fit(
                    X_tr, y_tr,
                    eval_set=[(X_val, y_val)],
                    callbacks=[lgb.early_stopping(50, verbose=False)],
                )
            else:
                # XGB: early_stopping_rounds is set on the constructor;
                # eval_set here triggers it. verbose kwarg name varies
                # across XGBoost versions, so omit it.
                self.model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)])
        else:
            self.model.fit(X, y)

        self._trained = True

    def train(self, X: pd.DataFrame, y: np.ndarray) -> None:
        """BaseSignalModel contract — interpret X as a single OHLCV DataFrame."""
        # y is ignored; sequences derive their own labels from forward returns.
        self.fit_from_ohlcv(X)

    # ---- inference ---------------------------------------------------------

    def predict_score(self, sequences: list[Sequence]) -> np.ndarray:
        if not sequences:
            return np.zeros((0,), dtype=np.float32)
        X = np.array([s.X.flatten() for s in sequences], dtype=np.float32)
        return self.model.predict(X).astype(np.float32)

    def predict(self, features: pd.DataFrame) -> SignalResult:
        """BaseSignalModel contract — accepts either a feature DataFrame
        (engineered columns already present) or raw OHLCV. Returns a
        SignalResult bucketed by the predicted next-horizon return."""
        feats = (
            features
            if all(col in features.columns for col in FEATURE_COLUMNS)
            else self.feature_engineer.compute(features)
        )
        seq = self.sequence_builder.transform_latest(feats)
        if seq is None:
            return SignalResult("HOLD", 0.5, 0.0, {"ranking": 0.0, "reason": "insufficient_window"})

        try:
            score = float(self.predict_score([seq])[0])
        except Exception as exc:
            logger.warning("RankingModel inference failed: %s — returning HOLD", exc)
            return SignalResult("HOLD", 0.5, 0.0, {"ranking": 0.0, "error": str(exc)})

        threshold = float(settings.ranking_signal_threshold)
        if score > threshold:
            signal = "BUY"
        elif score < -threshold:
            signal = "SELL"
        else:
            signal = "HOLD"

        confidence = float(min(0.95, 0.5 + abs(score) / max(threshold * 4, 1e-6) * 0.45))
        return SignalResult(
            signal=signal,
            confidence=round(confidence, 4),
            predicted_return=round(score, 6),
            component_weights={"ranking": 1.0, "raw_score": score},
        )

    @staticmethod
    def rank_ic(preds: np.ndarray, rets: np.ndarray) -> float:
        if preds.size == 0 or rets.size == 0:
            return float("nan")
        ic, _ = spearmanr(preds, rets)
        return float(ic)

    # ---- persistence -------------------------------------------------------

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "backend": self.backend,
                    "model": self.model,
                    "scaler_state": self.sequence_builder.scaler,
                    "fitted": self._trained,
                    "window": self.sequence_builder.window,
                    "version": self.model_version,
                },
                f,
            )

    @classmethod
    def load(cls, path: str) -> "RankingModel":
        with open(path, "rb") as f:
            state = pickle.load(f)
        instance = cls()
        instance.backend = state["backend"]
        instance.model = state["model"]
        instance.sequence_builder.scaler = state["scaler_state"]
        instance.sequence_builder._fitted = bool(state.get("fitted", False))
        instance.sequence_builder.window = int(state.get("window", instance.sequence_builder.window))
        instance._trained = bool(state.get("fitted", False))
        return instance
