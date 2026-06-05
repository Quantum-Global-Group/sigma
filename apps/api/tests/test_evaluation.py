"""Model-evaluation tests (PR-E) — pure metric math on labeled signal rows."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ml.evaluation import compute_metrics


def _row(predicted, realized, outcome):
    return SimpleNamespace(predicted_return=predicted, realized_return=realized, outcome=outcome)


def test_compute_metrics_directional_accuracy():
    rows = [
        _row(0.02, 0.03, "win"),    # both + → directional hit
        _row(-0.01, -0.02, "win"),  # both - → hit
        _row(0.02, -0.01, "loss"),  # predicted + actual - → miss
        _row(-0.02, 0.01, "loss"),  # predicted - actual + → miss
    ]
    m = compute_metrics(rows)
    assert m.n_samples == 4
    assert m.directional_accuracy == pytest.approx(0.5)   # 2 of 4
    assert m.signal_accuracy == pytest.approx(0.5)        # 2 wins / 4 decided
    assert m.mean_abs_error == pytest.approx((0.01 + 0.01 + 0.03 + 0.03) / 4, abs=1e-9)


def test_compute_metrics_ignores_unlabeled():
    rows = [_row(0.02, 0.03, "win"), _row(0.02, None, None)]  # 2nd unlabeled
    m = compute_metrics(rows)
    assert m.n_samples == 1
    assert m.directional_accuracy == pytest.approx(1.0)


def test_compute_metrics_flat_only_gives_none_signal_accuracy():
    rows = [_row(0.0, 0.0005, "flat"), _row(0.0, -0.0003, "flat")]
    m = compute_metrics(rows)
    assert m.signal_accuracy is None          # no win/loss rows
    assert m.n_samples == 2


def test_compute_metrics_empty():
    m = compute_metrics([])
    assert m.n_samples == 0
    assert m.directional_accuracy is None and m.signal_accuracy is None and m.mean_abs_error is None
