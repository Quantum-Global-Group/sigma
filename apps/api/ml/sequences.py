"""Feature engineering + windowed sequence builder for the RankingModel.

Ported from razorBill `models.py::FeatureEngineer` and `SequenceBuilder`.
Produces fixed-length sliding windows of technical indicators that the
RankingModel consumes.

Input convention: OHLCV DataFrame with either lowercase short names
(o, h, l, c, v) or the long names sigma's MarketAdapters return
(open, high, low, close, volume). `_normalize_ohlcv` accepts both."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = [
    "rsi",
    "atr",
    "ema_fast",
    "ema_slow",
    "mom_1",
    "mom_3",
    "mom_12",
    "vol_realized",
    "rolling_vol_50",
    "v_spike",
    "breakout_20",
]


class Sequence(NamedTuple):
    X: np.ndarray  # shape [window, n_features]
    y: float
    meta: dict


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Accept either short (o,h,l,c,v) or long (open,high,low,close,volume) columns."""
    rename_map = {
        "open": "o", "high": "h", "low": "l", "close": "c", "volume": "v",
    }
    out = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}).copy()
    if "t" not in out.columns:
        # Use the index as timestamp if no 't' column was provided.
        out["t"] = out.index
    return out


class FeatureEngineer:
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        out = _normalize_ohlcv(df).sort_values("t")
        out["ret1"] = out["c"].pct_change().fillna(0.0)
        out["ema_fast"] = out["c"].ewm(span=12, adjust=False).mean().fillna(out["c"])
        out["ema_slow"] = out["c"].ewm(span=26, adjust=False).mean().fillna(out["c"])
        out["rsi"] = self._rsi(out["c"], 14).fillna(50.0)
        tr = pd.concat([
            (out["h"] - out["l"]).abs(),
            (out["h"] - out["c"].shift(1)).abs(),
            (out["l"] - out["c"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        out["atr"] = tr.rolling(14).mean().bfill()
        out["mom_1"] = out["c"].pct_change(1).fillna(0.0)
        out["mom_3"] = out["c"].pct_change(3).fillna(0.0)
        out["mom_12"] = out["c"].pct_change(12).fillna(0.0)
        out["vol_realized"] = out["ret1"].rolling(30).std().fillna(0.0)
        out["rolling_vol_50"] = out["ret1"].rolling(50).std().fillna(0.0)
        out["v_ma20"] = out["v"].rolling(20).mean().replace(0.0, 1e-6)
        out["v_spike"] = (out["v"] / out["v_ma20"]).clip(upper=50.0).fillna(1.0)
        out["high_20"] = out["h"].rolling(20).max().bfill()
        out["breakout_20"] = out["c"] / (out["high_20"] + 1e-6)
        return out

    @staticmethod
    def _rsi(s: pd.Series, period: int) -> pd.Series:
        delta = s.diff()
        up = delta.clip(lower=0.0)
        down = -delta.clip(upper=0.0)
        ma_up = up.rolling(period).mean()
        ma_down = down.rolling(period).mean()
        rs = ma_up / (ma_down + 1e-12)
        return 100 - (100 / (1 + rs))


class SequenceBuilder:
    """Build fixed-window scaled sequences for training or prediction.

    `fit_transform` is for training: it fits a StandardScaler to the data and
    returns labeled sequences.

    `transform_latest` is for inference: it uses an already-fit scaler to
    produce a single sequence from the last `window` rows (no label)."""

    def __init__(self, window: int = 30) -> None:
        self.window = window
        self.scaler = StandardScaler()
        self._fitted = False

    def fit_transform(
        self,
        feats: pd.DataFrame,
        horizon: int = 3,
        symbol: str | None = None,
    ) -> list[Sequence]:
        feats = feats.dropna(subset=FEATURE_COLUMNS + ["c"]).copy()
        feats["y"] = feats["c"].pct_change(horizon).shift(-horizon)
        feats = feats.dropna(subset=["y"])

        X_full = feats[FEATURE_COLUMNS].values.astype(np.float32)
        X_scaled = self.scaler.fit_transform(X_full)
        self._fitted = True

        sequences: list[Sequence] = []
        for i in range(self.window, len(feats)):
            Xw = X_scaled[i - self.window : i, :]
            y = float(feats.iloc[i]["y"])
            meta = {
                "symbol": symbol or feats.iloc[i].get("symbol", ""),
                "window": self.window,
                "t": feats.iloc[i].get("t"),
            }
            sequences.append(Sequence(X=Xw, y=y, meta=meta))
        return sequences

    def transform_latest(self, feats: pd.DataFrame) -> Sequence | None:
        feats = feats.dropna(subset=FEATURE_COLUMNS + ["c"]).copy()
        if len(feats) < self.window:
            return None

        X_full = feats[FEATURE_COLUMNS].values.astype(np.float32)
        X_scaled = self.scaler.transform(X_full) if self._fitted else self.scaler.fit_transform(X_full)
        Xw = X_scaled[-self.window :, :]
        meta = {"window": self.window, "t": feats.iloc[-1].get("t")}
        return Sequence(X=Xw, y=0.0, meta=meta)
