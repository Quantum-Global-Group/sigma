"""
Random Forest + XGBoost ensemble with soft voting.

Trains on a feature DataFrame (rows = days, cols = engineered features) and
labels (0=SELL, 1=HOLD, 2=BUY). Predicts on the latest row at inference time.
"""

from __future__ import annotations

import logging

import joblib
import numpy as np
import pandas as pd

from config import settings
from ml.inference import SignalResult
from ml.models.base import BaseSignalModel, label_to_signal

logger = logging.getLogger(__name__)


class EnsembleSignalModel(BaseSignalModel):
    model_version = "ensemble_v1.0"

    def __init__(self, n_estimators: int = 200, random_state: int = 42):
        from sklearn.ensemble import RandomForestClassifier
        from xgboost import XGBClassifier

        self.rf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=8,
            min_samples_leaf=5,
            n_jobs=-1,
            random_state=random_state,
        )
        self.xgb = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=6,
            learning_rate=0.05,
            objective="multi:softprob",
            num_class=3,
            random_state=random_state,
            verbosity=0,
        )
        self.feature_names: list[str] = []
        self._fitted = False

    def train(self, X: pd.DataFrame, y: np.ndarray) -> None:
        from sklearn.utils.class_weight import compute_sample_weight

        self.feature_names = list(X.columns)
        # Class-balanced sample weights so the model doesn't collapse to the
        # majority class. Labels are heavily HOLD-skewed (crypto 5m ~97% HOLD,
        # forex ~60%); without balancing both RF and XGB just predict HOLD and
        # never emit BUY/SELL — the source of the trained-model degeneracy.
        sample_weight = compute_sample_weight(class_weight="balanced", y=y)
        self.rf.fit(X.values, y, sample_weight=sample_weight)
        self.xgb.fit(X.values, y, sample_weight=sample_weight)
        self._fitted = True
        logger.info("EnsembleSignalModel trained on %d samples (class-balanced)", len(X))

    def predict(self, features: pd.DataFrame) -> SignalResult:
        if not self._fitted or features.empty:
            return SignalResult("HOLD", 0.5, 0.0)

        # Use last row, align columns to training order
        if self.feature_names:
            X = features[self.feature_names].iloc[[-1]].values
        else:
            X = features.iloc[[-1]].values

        rf_proba = self.rf.predict_proba(X)[0]
        xgb_proba = self.xgb.predict_proba(X)[0]
        avg_proba = (rf_proba + xgb_proba) / 2.0

        label = int(np.argmax(avg_proba))
        confidence = float(avg_proba[label])
        # Map class probabilities to a tiny predicted return signal
        predicted_return = float((avg_proba[2] - avg_proba[0]) * 0.05)

        result = SignalResult(label_to_signal(label), round(confidence, 4), round(predicted_return, 6))
        result.model_version = self.model_version
        return result

    def save(self, path: str) -> None:
        joblib.dump({
            "rf": self.rf,
            "xgb": self.xgb,
            "feature_names": self.feature_names,
            "model_version": self.model_version,
        }, path)

    @classmethod
    def load(cls, path: str) -> "EnsembleSignalModel":
        data = joblib.load(path)
        instance = cls.__new__(cls)
        instance.rf = data["rf"]
        instance.xgb = data["xgb"]
        instance.feature_names = data["feature_names"]
        instance.model_version = data.get("model_version", "ensemble_v1.0")
        instance._fitted = True
        return instance
