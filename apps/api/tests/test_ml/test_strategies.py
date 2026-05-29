"""Tests for the per-asset-class strategy combiner (A1/A4 of equity-alpha plan).

Verifies that build_default_combiner respects asset-class strategy lists:
  - crypto excludes SDE strategies (daily-bar assumption invalid on 5m bars)
  - equity includes SDE strategies (daily bars, dt=1/252 valid)
  - fallback (None) produces a non-empty combiner from the global list
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))  # apps/api

from ml.strategies.combiner import build_default_combiner

SDE = {"gbm", "ou", "heston"}


def test_crypto_combiner_excludes_sde():
    c = build_default_combiner("crypto")
    assert not SDE.intersection(c.strategies), (
        f"SDE strategies should be excluded from crypto combiner; got {set(c.strategies)}"
    )


def test_equity_combiner_includes_sde():
    c = build_default_combiner("equity")
    assert SDE.issubset(c.strategies), (
        f"SDE strategies should be present in equity combiner; got {set(c.strategies)}"
    )


def test_equity_combiner_includes_ict():
    c = build_default_combiner("equity")
    assert "ict" in c.strategies


def test_crypto_combiner_includes_fourier_and_macd():
    c = build_default_combiner("crypto")
    assert {"macd", "fourier"}.issubset(c.strategies)


def test_fallback_combiner_non_empty():
    # No asset class — uses the legacy enabled_strategies global
    c = build_default_combiner(None)
    assert len(c.strategies) > 0


def test_weights_sum_to_one_equity():
    c = build_default_combiner("equity")
    assert abs(sum(c.weights.values()) - 1.0) < 1e-9, (
        f"Weights should sum to 1.0; got {sum(c.weights.values())}"
    )


def test_weights_sum_to_one_crypto():
    c = build_default_combiner("crypto")
    assert abs(sum(c.weights.values()) - 1.0) < 1e-9


def test_strategy_keys_match_weight_keys():
    for asset_class in ("crypto", "equity", None):
        c = build_default_combiner(asset_class)
        assert set(c.strategies) == set(c.weights), (
            f"Mismatch between strategy and weight keys for {asset_class!r}"
        )
