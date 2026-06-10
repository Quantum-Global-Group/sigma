"""Purged + embargoed cross-validation (López de Prado, *Advances in Financial ML*).

Financial labels overlap in time: a bar's label is realized over a forward window,
so adjacent train/test samples share information. Plain k-fold (or a naive
chronological split) leaks that overlap and inflates out-of-sample metrics — the
root cause of backtests that look great and trade terribly.

Two corrections:
  * **purge**  — drop training samples whose label interval [t_start, t_end]
                 overlaps the test window.
  * **embargo**— additionally drop a buffer of training samples immediately
                 *after* the test window (serial correlation bleeds forward).

All functions are pure (operate on arrays of comparable times / integer
positions) and unit-tested, including explicit leakage assertions.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import numpy as np


def _as_float_array(x: Sequence) -> np.ndarray:
    """Coerce times (datetimes, ints, floats) to a sortable float array."""
    arr = np.asarray(x)
    if np.issubdtype(arr.dtype, np.datetime64):
        return arr.astype("datetime64[ns]").astype("int64").astype(float)
    return arr.astype(float)


def purged_train_test_split(
    t_start: Sequence,
    t_end: Sequence,
    *,
    test_frac: float = 0.2,
    embargo_frac: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Single walk-forward holdout with purge (and optional leading embargo).

    Test = the most-recent `test_frac` of samples (chronological). Train = earlier
    samples whose label window does not overlap the test window. Returns
    (train_idx, test_idx) as integer position arrays into the original order.

    This is the leak-free replacement for the simple chronological tail split used
    by the harnesses and `scripts/train_models.py::_split`."""
    ts = _as_float_array(t_start)
    te = _as_float_array(t_end)
    n = len(ts)
    if n == 0:
        return np.array([], dtype=int), np.array([], dtype=int)

    order = np.argsort(ts, kind="mergesort")
    n_test = max(1, int(round(n * test_frac)))
    test_idx = np.sort(order[-n_test:])
    test_start = ts[test_idx].min()

    # Optional embargo *before* the test block (drop a buffer of the latest train
    # samples leading into the test window).
    embargo = int(round(n * embargo_frac))
    train_order = order[: n - n_test]
    if embargo > 0:
        train_order = train_order[: max(0, len(train_order) - embargo)]

    # Purge: keep only train samples whose label ends before the test starts.
    train_mask = te[train_order] < test_start
    train_idx = np.sort(train_order[train_mask])
    return train_idx, test_idx


def purged_kfold_splits(
    t_start: Sequence,
    t_end: Sequence,
    *,
    n_splits: int = 5,
    embargo_frac: float = 0.0,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield (train_idx, test_idx) for purged k-fold with an embargo.

    Folds are contiguous chronological blocks. For each test fold, training
    samples are purged if their label interval overlaps the test window, and an
    embargo of `embargo_frac * n` samples immediately after the test block is also
    removed. Indices are positions into the original (unsorted) arrays."""
    ts = _as_float_array(t_start)
    te = _as_float_array(t_end)
    n = len(ts)
    if n == 0 or n_splits < 2:
        return

    order = np.argsort(ts, kind="mergesort")
    rank = np.empty(n, dtype=int)
    rank[order] = np.arange(n)            # chronological rank of each sample
    embargo = int(round(n * embargo_frac))

    for fold in np.array_split(order, n_splits):
        if len(fold) == 0:
            continue
        test_idx = np.sort(fold)
        test_start = ts[test_idx].min()
        test_end = te[test_idx].max()
        hi = rank[test_idx].max()         # last chronological rank in the test block

        overlap = (ts <= test_end) & (te >= test_start)        # purge
        emb = (rank > hi) & (rank <= hi + embargo)             # embargo after test
        train_mask = ~overlap & ~emb
        train_mask[test_idx] = False
        train_idx = np.where(train_mask)[0]
        yield train_idx, test_idx


def horizon_end_times(index: Sequence, horizon_bars: int) -> np.ndarray:
    """Convenience: label end-times for fixed-horizon bar labels.

    Each sample at position i has its label realized `horizon_bars` later, so its
    end-time is index[i + horizon_bars] (clamped to the last index). Use the bar
    index itself as t_start."""
    arr = np.asarray(index)
    n = len(arr)
    end_pos = np.minimum(np.arange(n) + max(0, horizon_bars), n - 1)
    return arr[end_pos]
