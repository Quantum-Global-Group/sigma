"""Meta-labeling model — predicts P(win) of taking the primary signal.

López de Prado's meta-labeling: a *primary* model decides the side (here, SIGMA's
existing strategy combiner), and a *secondary* (meta) model decides whether to act
on it and how big. This separates direction (hard) from bet/no-bet (easier) and
reliably lifts precision and net Sharpe.

The meta-model is a class-balanced gradient-boosted binary classifier over
[base features + primary-signal descriptors]; its `P(win)` output gates bets
(τ threshold → HOLD) and sizes them (feeds `win_rate` into the Kelly sizer).

Pure-ish: training/predict are deterministic given inputs; persistence is plain
pickle to the registry naming `{asset}_meta_{version}.pkl`.
"""

from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
from sklearn.utils.class_weight import compute_sample_weight


class MetaLabeler:
    """Binary meta-model: P(win | features, primary side)."""

    def __init__(self, **xgb_kwargs):
        self.model = None
        self.feature_names: list[str] = []
        self._constant: float | None = None
        self._kwargs = xgb_kwargs

    def _new_model(self):
        from xgboost import XGBClassifier

        params = dict(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss", n_jobs=2,
        )
        params.update(self._kwargs)
        return XGBClassifier(**params)

    def train(self, X: pd.DataFrame, y_bin) -> MetaLabeler:
        """Fit on binary win/loss labels (1=the primary bet won). Class-balanced.

        Degenerate single-class targets fall back to a constant P(win) so the
        caller never crashes on a thin or one-sided window."""
        y = np.asarray(y_bin).astype(int)
        self.feature_names = list(X.columns)
        if len(y) == 0 or len(np.unique(y)) < 2:
            self._constant = float(y.mean()) if len(y) else 0.5
            self.model = None
            return self
        self._constant = None
        self.model = self._new_model()
        sw = compute_sample_weight("balanced", y)
        self.model.fit(X.values, y, sample_weight=sw)
        return self

    def predict_proba_win(self, X) -> np.ndarray:
        """P(win) per row. Constant fallback when the model is degenerate."""
        n = len(X)
        if self.model is None:
            return np.full(n, self._constant if self._constant is not None else 0.5, dtype=float)
        Xv = X.values if hasattr(X, "values") else np.asarray(X)
        return self.model.predict_proba(Xv)[:, 1]

    def save(self, path: str) -> None:
        with open(path, "wb") as fh:
            pickle.dump(
                {"model": self.model, "feature_names": self.feature_names,
                 "constant": self._constant}, fh,
            )

    @classmethod
    def load(cls, path: str) -> MetaLabeler:
        with open(path, "rb") as fh:
            d = pickle.load(fh)
        m = cls()
        m.model = d["model"]
        m.feature_names = d["feature_names"]
        m._constant = d.get("constant")
        return m
