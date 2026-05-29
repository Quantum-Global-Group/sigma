"""Unit tests for the pure options_math package (Phase 2)."""

import math

import numpy as np
import pytest

from options_math import (
    bs_price, bs_greeks, implied_vol,
    binomial_price, binomial_greeks,
    mc_price, compute_greeks,
    realized_vol, iv_rank, iv_percentile, vol_skew, spread_pct,
    LiquidityFilters, expected_value, passes_filters,
)

# Reference scenario
S, K, T, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.20


# --------------------------------------------------------------------------
# Black-Scholes
# --------------------------------------------------------------------------

def test_bs_atm_call_textbook_value():
    # Known BS value for S=K=100, T=1, r=5%, sigma=20%, q=0 → ~10.4506
    assert bs_price(S, K, T, r, sigma, "call") == pytest.approx(10.4506, abs=1e-3)


def test_bs_atm_put_textbook_value():
    assert bs_price(S, K, T, r, sigma, "put") == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    # C - P = S*e^{-qT} - K*e^{-rT}
    c = bs_price(S, K, T, r, sigma, "call")
    p = bs_price(S, K, T, r, sigma, "put")
    assert (c - p) == pytest.approx(S - K * math.exp(-r * T), abs=1e-6)


def test_bs_expiry_returns_intrinsic():
    assert bs_price(110, 100, 0.0, r, sigma, "call") == pytest.approx(10.0)
    assert bs_price(90, 100, 0.0, r, sigma, "put") == pytest.approx(10.0)
    assert bs_price(90, 100, 0.0, r, sigma, "call") == pytest.approx(0.0)


def test_bs_call_delta_in_zero_one():
    g = bs_greeks(S, K, T, r, sigma, "call")
    assert 0.0 < g["delta"] < 1.0
    assert g["gamma"] > 0
    assert g["vega"] > 0
    assert g["theta"] < 0  # long option bleeds time value


def test_bs_put_delta_negative():
    g = bs_greeks(S, K, T, r, sigma, "put")
    assert -1.0 < g["delta"] < 0.0


def test_call_put_delta_relationship():
    # delta_call - delta_put = e^{-qT} = 1 for q=0
    cd = bs_greeks(S, K, T, r, sigma, "call")["delta"]
    pd_ = bs_greeks(S, K, T, r, sigma, "put")["delta"]
    assert (cd - pd_) == pytest.approx(1.0, abs=1e-6)


# --------------------------------------------------------------------------
# Implied vol round-trip
# --------------------------------------------------------------------------

@pytest.mark.parametrize("right", ["call", "put"])
@pytest.mark.parametrize("true_sigma", [0.10, 0.20, 0.45])
def test_iv_roundtrip(right, true_sigma):
    price = bs_price(S, K, T, r, true_sigma, right)
    iv = implied_vol(price, S, K, T, r, right)
    assert iv is not None
    assert iv == pytest.approx(true_sigma, abs=1e-4)


def test_iv_below_intrinsic_returns_none():
    # Price below intrinsic is arbitrage-violating → no solution
    assert implied_vol(0.5, 120, 100, T, r, "call") is None


# --------------------------------------------------------------------------
# Binomial (American) vs BS (European)
# --------------------------------------------------------------------------

def test_binomial_european_converges_to_bs():
    eu = binomial_price(S, K, T, r, sigma, "call", steps=500, american=False)
    bs = bs_price(S, K, T, r, sigma, "call")
    assert eu == pytest.approx(bs, abs=0.05)


def test_american_put_ge_european_put():
    am = binomial_price(S, K, T, r, sigma, "put", steps=300, american=True)
    eu = binomial_price(S, K, T, r, sigma, "put", steps=300, american=False)
    assert am >= eu - 1e-9  # early exercise is never worth less


def test_binomial_greeks_match_bs_sign_and_rough_magnitude():
    bg = binomial_greeks(S, K, T, r, sigma, "call", steps=300)
    ag = bs_greeks(S, K, T, r, sigma, "call")
    assert bg["delta"] == pytest.approx(ag["delta"], abs=0.02)
    assert bg["gamma"] > 0


# --------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------

def test_mc_price_close_to_bs():
    out = mc_price(S, K, T, r, sigma, "call", n_paths=200_000, seed=7)
    bs = bs_price(S, K, T, r, sigma, "call")
    # within ~3 standard errors
    assert abs(out["price"] - bs) < 3 * out["stderr"] + 0.05


# --------------------------------------------------------------------------
# greeks dispatch
# --------------------------------------------------------------------------

def test_compute_greeks_dataclass_scaling():
    g = compute_greeks(S, K, T, r, sigma, "call", model="bs")
    assert g.theta_per_day == pytest.approx(g.theta / 365.0)
    assert g.vega_per_vol_point == pytest.approx(g.vega / 100.0)
    assert "delta" in g.as_dict()


# --------------------------------------------------------------------------
# volatility analytics
# --------------------------------------------------------------------------

def test_realized_vol_constant_series_zero():
    assert realized_vol([100.0] * 30) == pytest.approx(0.0)


def test_realized_vol_positive_for_noisy_series():
    rng = np.random.default_rng(0)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    rv = realized_vol(prices)
    assert 0.05 < rv < 0.5


def test_iv_rank_and_percentile():
    hist = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert iv_rank(0.3, hist) == pytest.approx(0.5)
    assert iv_rank(0.5, hist) == pytest.approx(1.0)
    assert iv_percentile(0.35, hist) == pytest.approx(0.6)  # 0.1,0.2,0.3 below


def test_spread_pct_and_skew():
    assert spread_pct(0.95, 1.05) == pytest.approx(0.10, abs=1e-9)
    assert spread_pct(0, 0) == float("inf")
    assert vol_skew(0.30, 0.25) == pytest.approx(0.05)


# --------------------------------------------------------------------------
# expected value + filters
# --------------------------------------------------------------------------

def test_expected_value_positive_and_negative():
    pos = expected_value(prob_itm=0.6, expected_payoff=5.0, premium=2.0, fees=0.05, slippage=0.05)
    assert pos.positive and pos.ev == pytest.approx(0.9, abs=1e-9)
    neg = expected_value(prob_itm=0.3, expected_payoff=2.0, premium=2.0)
    assert not neg.positive


def test_filters_accept_clean_contract():
    ok, reasons = passes_filters(
        bid=1.00, ask=1.04, volume=500, open_interest=2000,
        delta=0.45, iv=0.30, theta_per_day=-0.02,
        filters=LiquidityFilters(delta_range=(0.2, 0.8)),
    )
    assert ok and reasons == []


def test_filters_reject_wide_spread_and_low_liquidity():
    ok, reasons = passes_filters(
        bid=1.00, ask=1.50, volume=1, open_interest=5,
        delta=0.95, iv=3.0, theta_per_day=-1.0,
        filters=LiquidityFilters(delta_range=(0.2, 0.8), max_iv=2.0, max_abs_theta_per_day=0.5),
    )
    assert not ok
    assert len(reasons) >= 4  # spread, volume, OI, delta, iv, theta all trip
