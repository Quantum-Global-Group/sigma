from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pandas as pd
from sklearn.linear_model import SGDRegressor
from sklearn.preprocessing import StandardScaler
from scipy.stats import spearmanr
from loguru import logger
from .config import settings

# Optional boosters; fall back to SGD if unavailable
try:  # LightGBM preferred
    import lightgbm as lgb  # type: ignore
    _HAS_LGB = True
except Exception:  # noqa: BLE001
    _HAS_LGB = False
try:  # XGBoost as secondary option
    import xgboost as xgb  # type: ignore
    _HAS_XGB = True
except Exception:  # noqa: BLE001
    _HAS_XGB = False


class Sequence(NamedTuple):
    X: np.ndarray  # shape [window, n_features]
    y: float
    meta: dict


class FeatureEngineer:
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out = out.sort_values("t")
        out["ret1"] = out["c"].pct_change().fillna(0.0)
        out["ema_fast"] = out["c"].ewm(span=12, adjust=False).mean().fillna(out["c"])
        out["ema_slow"] = out["c"].ewm(span=26, adjust=False).mean().fillna(out["c"])
        out["rsi"] = self._rsi(out["c"], 14).fillna(50.0)  # Default to neutral RSI
        tr = pd.concat([
            (out["h"] - out["l"]).abs(),
            (out["h"] - out["c"].shift(1)).abs(),
            (out["l"] - out["c"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        out["atr"] = tr.rolling(14).mean().bfill()
        out["mom_1"] = out["c"].pct_change(1).fillna(0.0)
        out["vol_realized"] = out["ret1"].rolling(30).std().fillna(0.0)
        # Additional momentum horizons and breakout/volume spike features
        out["mom_3"] = out["c"].pct_change(3).fillna(0.0)
        out["mom_12"] = out["c"].pct_change(12).fillna(0.0)
        out["rolling_vol_50"] = out["ret1"].rolling(50).std().fillna(0.0)
        out["v_ma20"] = out["v"].rolling(20).mean().replace(0.0, 1e-6)
        out["v_spike"] = (out["v"] / out["v_ma20"]).clip(upper=50.0).fillna(1.0)  # Default to normal volume
        out["high_20"] = out["h"].rolling(20).max().bfill()
        out["breakout_20"] = (out["c"] / (out["high_20"] + 1e-6))
        return out

    def _rsi(self, s: pd.Series, period: int) -> pd.Series:
        delta = s.diff()
        up = delta.clip(lower=0.0)
        down = -delta.clip(upper=0.0)
        ma_up = up.rolling(period).mean()
        ma_down = down.rolling(period).mean()
        rs = ma_up / (ma_down + 1e-12)
        return 100 - (100 / (1 + rs))


class SequenceBuilder:
    def __init__(self, window: int = 60) -> None:
        self.window = window
        self.scaler = StandardScaler()

    def fit_transform(self, feats: pd.DataFrame) -> list[Sequence]:
        cols = [
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
        feats = feats.dropna(subset=cols + ["c"]).copy()
        # Predict returns over configurable horizon
        from .config import settings
        horizon = max(1, int(settings.pred_horizon_bars))
        feats["y"] = feats["c"].pct_change(horizon).shift(-horizon)
        feats = feats.dropna(subset=["y"])  # drop last
        X_full = feats[cols].values.astype(np.float32)
        X_scaled = self.scaler.fit_transform(X_full)
        sequences: list[Sequence] = []
        for i in range(self.window, len(feats)):
            Xw = X_scaled[i - self.window : i, :]
            y = float(feats.iloc[i]["y"])
            meta = {"symbol": feats.iloc[i]["symbol"], "window": self.window, "t": feats.iloc[i]["t"]}
            sequences.append(Sequence(X=Xw, y=y, meta=meta))
        return sequences


class RankingModel:
    def __init__(self) -> None:
        self.backend = self._select_backend()
        self.model = self._init_model(self.backend)

    def _select_backend(self) -> str:
        if _HAS_LGB:
            return "lgb"
        if _HAS_XGB:
            return "xgb"
        return "sgd"

    def _init_model(self, backend: str):  # type: ignore[no-untyped-def]
        if backend == "lgb":
            # Reasonable defaults; tuned later via Optuna
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
            )
        return SGDRegressor(max_iter=1000, tol=1e-3)

    def fit(self, sequences: list[Sequence]) -> None:
        if not sequences:
            return
        X = np.array([s.X.flatten() for s in sequences], dtype=np.float32)
        y = np.array([s.y for s in sequences], dtype=np.float32)
        if len(X) == 0:
            return
        # Early stopping for boosters
        if self.backend in ["lgb", "xgb"] and len(X) > 100:
            # Split for validation
            split_idx = int(0.8 * len(X))
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]
            if self.backend == "lgb":
                self.model.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    callbacks=[lgb.early_stopping(50, verbose=False)]
                )
            elif self.backend == "xgb":
                self.model.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    early_stopping_rounds=50,
                    verbose=False
                )
            return
        # Fallback: no early stopping
        if self.backend == "sgd":
            self.model.fit(X, y)
            return
        # Small data path for boosters
        self.model.fit(X, y)  # type: ignore[attr-defined]

    def predict(self, sequences: list[Sequence]) -> np.ndarray:
        if not sequences:
            return np.zeros((0,), dtype=np.float32)
        X = np.array([s.X.flatten() for s in sequences], dtype=np.float32)
        preds = self.model.predict(X)  # type: ignore[attr-defined]
        return preds.astype(np.float32)

    def save(self, path: str | None = None) -> None:
        path = path or settings.model_path
        try:
            if self.backend == "lgb":
                self.model.booster_.save_model(path)  # type: ignore[attr-defined]
            elif self.backend == "xgb":
                self.model.save_model(path)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            logger.warning("Model save failed: {}", e)

    def load(self, path: str | None = None) -> None:
        path = path or settings.model_path
        try:
            if self.backend == "lgb":
                booster = lgb.Booster(model_file=path)  # type: ignore[attr-defined]
                params = self.model.get_params()
                self.model = lgb.LGBMRegressor(**params)
                self.model._Booster = booster  # type: ignore[attr-defined]
            elif self.backend == "xgb":
                self.model.load_model(path)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            logger.warning("Model load failed: {}", e)

    def rank_ic(self, preds: np.ndarray, rets: np.ndarray) -> float:
        if preds.size == 0 or rets.size == 0:
            return float("nan")
        ic, _ = spearmanr(preds, rets)
        return float(ic)