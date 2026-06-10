"""Tests for serving-side meta-labeling helpers (ml/meta_serving.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from ml.meta_serving import apply_meta_gate, build_meta_row


def _result(signal="BUY", conf=0.6, pr=0.01):
    return SimpleNamespace(signal=signal, confidence=conf, predicted_return=pr)


def test_build_meta_row_orders_to_feature_names():
    last = pd.DataFrame({"rsi_14": [55.0], "ema_ratio": [1.02]})
    cols = ["rsi_14", "ema_ratio", "strength", "conf", "side", "abs_strength"]
    row = build_meta_row(last, strength=0.4, confidence=0.7, feature_names=cols)
    assert list(row.columns) == cols
    assert row["strength"].iloc[0] == 0.4
    assert row["side"].iloc[0] == 1.0          # positive strength → long
    assert row["abs_strength"].iloc[0] == 0.4
    assert row["conf"].iloc[0] == 0.7


def test_build_meta_row_negative_side_and_missing_cols_filled():
    last = pd.DataFrame({"rsi_14": [40.0]})
    cols = ["rsi_14", "missing_feat", "strength", "conf", "side", "abs_strength"]
    row = build_meta_row(last, strength=-0.3, confidence=0.5, feature_names=cols)
    assert row["side"].iloc[0] == -1.0
    assert row["missing_feat"].iloc[0] == 0.0   # absent feature filled with 0
    assert list(row.columns) == cols


def test_gate_collapses_low_pwin_to_hold():
    r = apply_meta_gate(_result("BUY"), p_win=0.40, tau=0.55)
    assert r.signal == "HOLD"
    assert r.predicted_return == 0.0
    assert r.confidence == 0.40                 # confidence still reflects P(win)


def test_gate_keeps_high_pwin_and_sets_confidence():
    r = apply_meta_gate(_result("SELL", pr=-0.02), p_win=0.72, tau=0.55)
    assert r.signal == "SELL"
    assert r.predicted_return == -0.02
    assert r.confidence == 0.72


def test_gate_leaves_hold_untouched_directionally():
    r = apply_meta_gate(_result("HOLD", pr=0.0), p_win=0.30, tau=0.55)
    assert r.signal == "HOLD"
    assert r.confidence == 0.30
