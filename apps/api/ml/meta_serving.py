"""Serving-side helpers for meta-labeling (kept pure for unit testing).

At each tick, for an asset with a trained meta-model, the worker builds a one-row
feature frame = [build_features row + combiner descriptors], asks the meta-model for
P(win), then gates/sizes the signal:
  * P(win) < tau           → collapse BUY/SELL to HOLD (don't take the bet)
  * otherwise              → keep the side, set confidence = P(win) (feeds sizing)

The combiner descriptors mirror exactly what the meta-model was trained on
(see scripts/train_models.py::train_meta): strength, conf, side, abs_strength.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

META_DESCRIPTORS = ["strength", "conf", "side", "abs_strength"]


def build_meta_row(
    model_feats_last: pd.DataFrame,
    strength: float,
    confidence: float,
    feature_names: Sequence[str],
) -> pd.DataFrame:
    """One-row frame for the meta-model, reindexed to its training column order.

    `model_feats_last` is the last row of build_features(df) (a 1-row DataFrame)."""
    side = 1.0 if strength > 0 else (-1.0 if strength < 0 else 0.0)
    row = model_feats_last.copy()
    row["strength"] = float(strength)
    row["conf"] = float(confidence)
    row["side"] = side
    row["abs_strength"] = abs(float(strength))
    return row.reindex(columns=list(feature_names), fill_value=0.0)


def apply_meta_gate(result, p_win: float, tau: float):
    """Gate/size a SignalResult by P(win). Mutates and returns `result`.

    Sets confidence = P(win) so downstream sizing reflects the meta-model's edge;
    collapses a directional signal to HOLD when P(win) is below tau."""
    result.confidence = float(p_win)
    if getattr(result, "signal", "HOLD") in ("BUY", "SELL") and p_win < tau:
        result.signal = "HOLD"
        result.predicted_return = 0.0
    return result
