"""Tests for the meta-labeling model (ml/meta_label.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.meta_label import MetaLabeler


def _separable(n=400, seed=0):
    """Feature x0 separates win (1) from loss (0): wins have higher x0."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    x0 = y + rng.normal(0, 0.3, n)            # signal
    x1 = rng.normal(0, 1, n)                  # noise
    X = pd.DataFrame({"x0": x0, "x1": x1})
    return X, y


def test_learns_separable_win_signal():
    X, y = _separable()
    m = MetaLabeler(n_estimators=80).train(X, y)
    p = m.predict_proba_win(X)
    # P(win) should be higher on true wins than true losses on average.
    assert p[y == 1].mean() > p[y == 0].mean() + 0.1
    assert p.min() >= 0.0 and p.max() <= 1.0


def test_degenerate_single_class_returns_constant():
    X = pd.DataFrame({"x0": np.arange(20.0), "x1": np.ones(20)})
    y = np.ones(20, dtype=int)                # all wins
    m = MetaLabeler().train(X, y)
    p = m.predict_proba_win(X)
    assert np.allclose(p, 1.0)
    assert m.model is None                     # fell back to constant


def test_empty_target_defaults_half():
    X = pd.DataFrame({"x0": [], "x1": []})
    m = MetaLabeler().train(X, np.array([], dtype=int))
    assert np.allclose(m.predict_proba_win(pd.DataFrame({"x0": [1.0], "x1": [2.0]})), 0.5)


def test_save_load_roundtrip(tmp_path):
    X, y = _separable(n=200)
    m = MetaLabeler(n_estimators=60).train(X, y)
    p1 = m.predict_proba_win(X)
    path = str(tmp_path / "equity_meta_test.pkl")
    m.save(path)
    m2 = MetaLabeler.load(path)
    p2 = m2.predict_proba_win(X)
    assert np.allclose(p1, p2)
    assert m2.feature_names == ["x0", "x1"]
