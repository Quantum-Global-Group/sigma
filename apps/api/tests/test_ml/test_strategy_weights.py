"""Phase C — learned strategy weights: edge computation is pure + testable."""

from ml.strategy_weights import compute_strategy_weights


class _Row:
    def __init__(self, comps, realized_return):
        self.component_weights = {"component_signals": comps}
        self.realized_return = realized_return


def _rows(n=60):
    rows = []
    for i in range(n):
        rr = 0.01 if i % 2 == 0 else -0.01
        rows.append(_Row(
            {
                "good": (1.0 if rr > 0 else -1.0),   # always correct direction
                "bad": (-1.0 if rr > 0 else 1.0),    # always wrong direction
                "abstain": 0.0,                       # never votes
            },
            rr,
        ))
    return rows


def test_edge_weighting_favours_accurate_strategy():
    w = compute_strategy_weights(_rows(60), flat_threshold=0.001, prior_strength=10.0, min_total_samples=0)
    assert w.get("good", 0.0) > 0.0
    assert w.get("bad", 0.0) == 0.0          # sub-coin-flip → zero edge → dropped
    assert "abstain" not in w                 # never voted → not weighted
    assert abs(sum(w.values()) - 1.0) < 1e-6  # normalized


def test_coinflip_strategy_yields_no_weights():
    rows = []
    for i in range(60):
        rr = 0.01 if i % 2 == 0 else -0.01
        s = 1.0 if i % 4 < 2 else -1.0   # agrees ~half the time
        rows.append(_Row({"rng": s}, rr))
    assert compute_strategy_weights(rows, flat_threshold=0.001, prior_strength=10.0, min_total_samples=0) == {}


def test_flat_outcomes_are_ignored():
    rows = [_Row({"x": 1.0}, 0.0)] * 60  # all flat (|rr| < threshold)
    assert compute_strategy_weights(rows, flat_threshold=0.001, min_total_samples=0) == {}


def test_min_samples_gate_keeps_equal_weights():
    # Strong edge but too few labeled rows → empty (caller keeps equal weights).
    assert compute_strategy_weights(_rows(20), flat_threshold=0.001, prior_strength=10.0, min_total_samples=50) == {}
