"""Tests for ml/options_income.py — the defined-risk put-credit-spread brain."""

import sys
from pathlib import Path

_api = Path(__file__).parents[2]
sys.path.insert(0, str(_api))

import pytest

from ml.options_income import (
    monthly_risk_budget,
    select_put_credit_spread,
)


def test_risk_budget_is_small_sleeve():
    assert monthly_risk_budget(100_000, 0.10) == pytest.approx(10_000)
    assert monthly_risk_budget(100_000, 0.0) == 0.0
    assert monthly_risk_budget(-5, 0.1) == 0.0


def test_spread_is_below_spot_and_capped():
    s = select_put_credit_spread(500.0, risk_budget_usd=2000, otm_pct=0.05, width_pct=0.02)
    # short ~5% below 500 = 475; long ~2% (=10) below = 465
    assert s.short_strike == pytest.approx(475.0)
    assert s.long_strike == pytest.approx(465.0)
    assert s.width == pytest.approx(10.0)
    assert s.short_strike < 500.0 and s.long_strike < s.short_strike


def test_sizing_respects_risk_budget():
    # width 10 × 100 = $1000 max loss per spread; budget 2000 → 2 contracts
    s = select_put_credit_spread(500.0, risk_budget_usd=2000, otm_pct=0.05, width_pct=0.02)
    assert s.contracts == 2
    assert s.max_loss == pytest.approx(2000.0)
    assert s.max_loss <= 2000.0 and s.is_tradeable


def test_budget_too_small_is_not_tradeable():
    # one spread risks $1000; budget 500 → 0 contracts, not tradeable
    s = select_put_credit_spread(500.0, risk_budget_usd=500, otm_pct=0.05, width_pct=0.02)
    assert s.contracts == 0 and not s.is_tradeable and s.max_loss == 0.0


def test_max_loss_never_exceeds_budget_across_prices():
    for spot in (50.0, 123.45, 500.0, 4200.0):
        for budget in (1000, 5000, 25_000):
            s = select_put_credit_spread(spot, risk_budget_usd=budget, width_pct=0.02)
            assert s.max_loss <= budget + 1e-6        # capped by construction


def test_long_strike_forced_below_short_when_width_rounds_to_zero():
    # tiny width_pct on a low-priced underlying could round long==short; must fix
    s = select_put_credit_spread(20.0, risk_budget_usd=5000, otm_pct=0.05,
                                 width_pct=0.001, strike_increment=1.0)
    assert s.long_strike < s.short_strike and s.width >= 1.0


def test_zero_or_negative_inputs_are_safe():
    assert not select_put_credit_spread(0.0, risk_budget_usd=1000).is_tradeable
    assert not select_put_credit_spread(500.0, risk_budget_usd=0).is_tradeable
