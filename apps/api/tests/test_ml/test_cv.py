"""Tests for purged + embargoed CV (ml/cv.py), including leakage assertions."""

from __future__ import annotations

import numpy as np

from ml.cv import (
    horizon_end_times,
    purged_kfold_splits,
    purged_train_test_split,
)

HORIZON = 5


def _fixed_horizon(n: int, horizon: int = HORIZON):
    """t_start = bar position; t_end = bar position + horizon (clamped)."""
    t_start = np.arange(n)
    t_end = horizon_end_times(t_start, horizon)
    return t_start, t_end


# ---------------------------------------------------------------------------
# purged_train_test_split (walk-forward holdout)
# ---------------------------------------------------------------------------

def test_holdout_test_is_chronological_tail():
    n = 100
    ts, te = _fixed_horizon(n)
    train, test = purged_train_test_split(ts, te, test_frac=0.2)
    assert test.tolist() == list(range(80, 100))


def test_holdout_purges_overlap_into_test():
    """No training sample's label may end at/after the test window start."""
    n = 100
    ts, te = _fixed_horizon(n)
    train, test = purged_train_test_split(ts, te, test_frac=0.2)
    test_start = ts[test].min()
    # Every retained train sample's label fully precedes the test window.
    assert np.all(te[train] < test_start)
    # The 5 bars whose horizon bleeds into the test (positions 75-79) are purged.
    assert max(train) < 75
    # train and test are disjoint.
    assert set(train).isdisjoint(set(test))


def test_holdout_embargo_drops_extra_leading_train():
    n = 100
    ts, te = _fixed_horizon(n)
    base_train, _ = purged_train_test_split(ts, te, test_frac=0.2, embargo_frac=0.0)
    emb_train, _ = purged_train_test_split(ts, te, test_frac=0.2, embargo_frac=0.1)
    assert len(emb_train) < len(base_train)


def test_holdout_empty_input():
    train, test = purged_train_test_split([], [], test_frac=0.2)
    assert len(train) == 0 and len(test) == 0


# ---------------------------------------------------------------------------
# purged_kfold_splits
# ---------------------------------------------------------------------------

def test_kfold_yields_n_splits_and_disjoint_folds():
    n = 60
    ts, te = _fixed_horizon(n, horizon=3)
    folds = list(purged_kfold_splits(ts, te, n_splits=5))
    assert len(folds) == 5
    seen = []
    for _, test in folds:
        seen.extend(test.tolist())
    # Every sample appears in exactly one test fold.
    assert sorted(seen) == list(range(n))


def test_kfold_no_train_test_label_overlap():
    """Core leakage guarantee: retained train labels never overlap the test window."""
    n = 60
    ts, te = _fixed_horizon(n, horizon=3)
    for train, test in purged_kfold_splits(ts, te, n_splits=5):
        test_start, test_end = ts[test].min(), te[test].max()
        # purge condition is overlap = (ts <= test_end) & (te >= test_start)
        overlaps = (ts[train] <= test_end) & (te[train] >= test_start)
        assert not overlaps.any()
        assert set(train).isdisjoint(set(test))


def test_kfold_embargo_removes_samples_after_test():
    n = 60
    ts, te = _fixed_horizon(n, horizon=3)
    no_emb = list(purged_kfold_splits(ts, te, n_splits=5, embargo_frac=0.0))
    with_emb = list(purged_kfold_splits(ts, te, n_splits=5, embargo_frac=0.1))
    # For an early fold (test not at the very end), embargo must shrink train.
    tr0_no = len(no_emb[0][0])
    tr0_emb = len(with_emb[0][0])
    assert tr0_emb < tr0_no


def test_kfold_degenerate_nsplits():
    ts, te = _fixed_horizon(10)
    assert list(purged_kfold_splits(ts, te, n_splits=1)) == []
