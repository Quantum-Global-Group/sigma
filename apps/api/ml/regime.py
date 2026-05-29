"""Market regime detection via a Gaussian Mixture Model (Moomoo doc §5.2).

Clusters (trailing-return, realized-vol) space into regimes, then labels each
cluster by its statistics so the output is interpretable and drives strategy
selection: SIGMA should not run the same option strategy in every regime.

Labels: TRENDING_UP, TRENDING_DOWN, RANGE, HIGH_VOL, LOW_VOL. (Event-driven /
liquidity-shock regimes need exogenous signals — out of scope here.)

GaussianMixture (sklearn, already a dependency) over hmmlearn keeps the install
lean; random_state makes it deterministic for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

import numpy as np
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegimeResult:
    regime: Regime
    confidence: float            # posterior prob of the assigned cluster
    trend_z: float               # standardized trailing return of the cluster
    vol_z: float                 # standardized realized vol of the cluster


def _features(prices: np.ndarray, ret_window: int, vol_window: int) -> np.ndarray:
    logret = np.diff(np.log(prices))
    n = len(logret)
    feats = []
    for i in range(n):
        lo_r = max(0, i - ret_window + 1)
        lo_v = max(0, i - vol_window + 1)
        trail_ret = logret[lo_r : i + 1].sum()
        vol = logret[lo_v : i + 1].std(ddof=0) * np.sqrt(252) if i - lo_v >= 1 else 0.0
        feats.append([trail_ret, vol])
    return np.asarray(feats, dtype=float)


class RegimeDetector:
    """Fit a GMM on a price history, then label the latest (or any) bar."""

    def __init__(self, n_components: int = 4, ret_window: int = 10, vol_window: int = 20,
                 trend_threshold: float = 0.5, random_state: int = 42) -> None:
        self.n_components = n_components
        self.ret_window = ret_window
        self.vol_window = vol_window
        self.trend_threshold = trend_threshold  # |trend_z| above this → trending
        self.random_state = random_state
        self._gmm: Optional[GaussianMixture] = None
        self._scaler: Optional[StandardScaler] = None
        self._feats: Optional[np.ndarray] = None
        self._labels: Optional[np.ndarray] = None
        self._cluster_z: dict[int, tuple[float, float]] = {}

    def fit(self, prices: Sequence[float]) -> "RegimeDetector":
        p = np.asarray(prices, dtype=float)
        p = p[np.isfinite(p) & (p > 0)]
        if len(p) < max(self.vol_window, self.ret_window) + 5:
            raise ValueError("not enough price history to fit regime detector")

        feats = _features(p, self.ret_window, self.vol_window)
        scaler = StandardScaler()
        X = scaler.fit_transform(feats)
        k = min(self.n_components, max(2, len(X) // 10))
        gmm = GaussianMixture(n_components=k, covariance_type="full", random_state=self.random_state)
        labels = gmm.fit_predict(X)

        # Standardized cluster means (trend_z, vol_z) in scaled space.
        self._cluster_z = {
            c: (float(X[labels == c, 0].mean()), float(X[labels == c, 1].mean()))
            for c in range(k)
        }
        self._gmm, self._scaler, self._feats, self._labels = gmm, scaler, feats, labels
        return self

    def _label_cluster(self, cluster: int) -> tuple[Regime, float, float]:
        trend_z, vol_z = self._cluster_z[cluster]
        if trend_z > self.trend_threshold:
            return Regime.TRENDING_UP, trend_z, vol_z
        if trend_z < -self.trend_threshold:
            return Regime.TRENDING_DOWN, trend_z, vol_z
        if vol_z > self.trend_threshold:
            return Regime.HIGH_VOL, trend_z, vol_z
        if vol_z < -self.trend_threshold:
            return Regime.LOW_VOL, trend_z, vol_z
        return Regime.RANGE, trend_z, vol_z

    def label_latest(self) -> RegimeResult:
        if self._gmm is None:
            raise RuntimeError("fit() before label_latest()")
        X = self._scaler.transform(self._feats[-1:])
        probs = self._gmm.predict_proba(X)[0]
        cluster = int(np.argmax(probs))
        regime, trend_z, vol_z = self._label_cluster(cluster)
        return RegimeResult(regime=regime, confidence=float(probs[cluster]), trend_z=trend_z, vol_z=vol_z)


def detect_regime(prices: Sequence[float], **kwargs) -> RegimeResult:
    """Convenience: fit + label the latest bar. Returns UNKNOWN on too-short data."""
    try:
        return RegimeDetector(**kwargs).fit(prices).label_latest()
    except (ValueError, RuntimeError):
        return RegimeResult(Regime.UNKNOWN, 0.0, 0.0, 0.0)
