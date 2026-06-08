"""Tests for the transaction-cost model (ml/costs.py)."""

from __future__ import annotations

import numpy as np

from config import settings
from ml.costs import apply_cost, cost_bps, cost_frac, net_returns, sharpe


def test_cost_bps_reads_config_per_asset():
    assert cost_bps("equity") == settings.cost_bps_equity
    assert cost_bps("forex") == settings.cost_bps_forex
    assert cost_bps("crypto") == settings.cost_bps_crypto


def test_cost_bps_unknown_asset_falls_back():
    assert cost_bps("commodity") == 2.0  # default fallback


def test_cost_frac_scales_with_round_trips():
    assert cost_frac("equity", round_trips=1.0) == settings.cost_bps_equity / 1e4
    assert cost_frac("equity", round_trips=2.0) == 2 * settings.cost_bps_equity / 1e4


def test_apply_cost_subtracts_round_trip():
    gross = 0.01
    net = apply_cost(gross, "crypto")
    assert net == gross - settings.cost_bps_crypto / 1e4


def test_net_returns_only_charges_traded_bars():
    gross = [0.01, 0.0, 0.02]
    mask = [True, False, True]
    out = net_returns(gross, "equity", traded_mask=mask)
    c = settings.cost_bps_equity / 1e4
    assert np.allclose(out, [0.01 - c, 0.0, 0.02 - c])


def test_net_returns_default_charges_all():
    out = net_returns([0.01, 0.01], "forex")
    c = settings.cost_bps_forex / 1e4
    assert np.allclose(out, [0.01 - c, 0.01 - c])


def test_sharpe_basic_and_degenerate():
    assert sharpe([0.01]) is None          # need >= 2 points
    assert sharpe([0.0, 0.0, 0.0]) is None  # zero variance
    s = sharpe([0.01, -0.005, 0.02, 0.0, 0.015], periods_per_year=252)
    assert s is not None and np.isfinite(s)
