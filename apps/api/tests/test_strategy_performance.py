"""Tests for strategy performance aggregation."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from ml.strategy_performance import (
    aggregate_strategy_stats,
    build_strategy_report_summary,
    parse_period,
    resolve_since,
)


def _row(cw, outcome=None, realized=None):
    return SimpleNamespace(component_weights=cw, outcome=outcome, realized_return=realized)


def test_aggregate_strategy_stats_basic():
    rows = [
        _row({"component_signals": {"ict": 0.5, "momentum": 0.1}, "component_confidence": {}}, "win", 0.02),
        _row({"component_signals": {"ict": 0.2, "momentum": 0.4}, "component_confidence": {}}, "loss", -0.01),
        _row({"component_signals": {"ict": 0.05, "momentum": 0.0}, "component_confidence": {}}, "flat", 0.0),
    ]
    stats = aggregate_strategy_stats(rows, strength_threshold=0.3)
    by_name = {s.strategy: s for s in stats}
    assert "ict" in by_name and "momentum" in by_name
    ict = by_name["ict"]
    assert ict.contribution_count == 3
    assert ict.contribution_frequency == pytest.approx(1.0)
    assert ict.n_above_threshold == 1  # only first row > 0.3
    assert ict.n_labeled_above_threshold == 1
    assert ict.win_rate_above_threshold == pytest.approx(1.0)


def test_aggregate_strategy_stats_empty():
    assert aggregate_strategy_stats([]) == []


def test_parse_period_days_and_hours():
    assert parse_period("7d") == timedelta(days=7)
    assert parse_period("24h") == timedelta(hours=24)


def test_parse_period_invalid():
    with pytest.raises(ValueError, match="invalid period"):
        parse_period("1w")


def test_resolve_since_period_overrides():
    since, period = resolve_since(period="7d")
    assert period == "7d"
    assert since is not None


def test_build_strategy_report_summary_markdown():
    data = {
        "asset_class": "equity",
        "period": "7d",
        "since": "2026-01-01T00:00:00+00:00",
        "n_signals": 10,
        "n_labeled": 5,
        "strength_threshold": 0.3,
        "strategies": [
            {
                "strategy": "momentum",
                "contribution_frequency": 0.8,
                "avg_strength_when_present": 0.45,
                "win_rate_above_threshold": 0.6,
                "n_above_threshold": 4,
            }
        ],
    }
    md = build_strategy_report_summary(data)
    assert "# Strategy report — equity (7d)" in md
    assert "momentum" in md
    assert "60.0%" in md
