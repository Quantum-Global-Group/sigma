"""Tests for the options strategy brain (P4): regime, structures, selection."""

from datetime import date

import numpy as np
import pytest

from markets.options import OptionContract, OptionQuote
from options_math import bs_price, bs_greeks
from ml.regime import Regime, RegimeDetector, detect_regime
from options.strategies import (
    long_call, long_put, call_debit_spread, iron_condor, long_straddle, build_structure,
)
from options.selection import applicable_strategies, select_candidates
from options_math import LiquidityFilters


# ---------------------------------------------------------------------------
# chain factory
# ---------------------------------------------------------------------------

def make_chain(spot=100.0, lo=80, hi=121, step=5, T=30 / 365, r=0.05, sigma=0.3,
               volume=1000, oi=5000, spread_frac=0.04):
    quotes = []
    for K in range(lo, hi, step):
        for right in ("call", "put"):
            price = max(0.05, bs_price(spot, K, T, r, sigma, right))
            g = bs_greeks(spot, K, T, r, sigma, right)
            sp = spread_frac * price
            c = OptionContract("AAPL", date(2026, 1, 16), float(K), right, f"US.AAPL.{K}{right[0]}")
            quotes.append(OptionQuote(
                contract=c, bid=round(price - sp / 2, 2), ask=round(price + sp / 2, 2),
                last=round(price, 2), volume=volume, open_interest=oi, implied_vol=sigma,
                delta=g["delta"], gamma=g["gamma"], theta=g["theta"], vega=g["vega"],
            ))
    return quotes


# ---------------------------------------------------------------------------
# regime detector
# ---------------------------------------------------------------------------

def test_detect_regime_short_data_unknown():
    assert detect_regime([100, 101, 102]).regime == Regime.UNKNOWN


def test_regime_high_vol_tail():
    rng = np.random.default_rng(0)
    calm = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, 200)))
    wild = calm[-1] * np.exp(np.cumsum(rng.normal(0, 0.04, 40)))
    res = RegimeDetector(random_state=42).fit(np.concatenate([calm, wild])).label_latest()
    assert res.regime in (Regime.HIGH_VOL, Regime.TRENDING_UP, Regime.TRENDING_DOWN)
    assert res.vol_z > 0                      # latest cluster is high-vol
    assert 0.0 <= res.confidence <= 1.0


def test_regime_trending_up_tail():
    rng = np.random.default_rng(1)
    flat = 100 + rng.normal(0, 0.05, 150)
    up = flat[-1] * np.exp(np.cumsum(np.full(60, 0.01)))   # steady strong uptrend
    res = RegimeDetector(random_state=42).fit(np.concatenate([flat, up])).label_latest()
    assert res.trend_z > 0


# ---------------------------------------------------------------------------
# structures
# ---------------------------------------------------------------------------

def test_long_call_profile():
    chain = make_chain()
    s = long_call(chain, 100.0, 30 / 365, 0.05)
    assert s is not None and s.name == "long_call"
    assert s.net_greeks["delta"] > 0
    assert s.max_profit == float("inf")
    assert s.max_loss == pytest.approx(s.net_debit * 100)
    assert s.breakevens[0] > 100             # call BE above strike


def test_long_put_negative_delta():
    s = long_put(make_chain(), 100.0, 30 / 365, 0.05)
    assert s.net_greeks["delta"] < 0


def test_call_debit_spread_capped():
    s = call_debit_spread(make_chain(), 100.0, 30 / 365, 0.05, width_pct=0.05)
    assert s is not None and len(s.legs) == 2
    assert s.net_debit > 0                    # debit spread
    assert s.max_profit < float("inf")
    assert s.max_loss == pytest.approx(s.net_debit * 100)


def test_long_straddle_delta_neutral():
    s = long_straddle(make_chain(), 100.0, 30 / 365, 0.05)
    assert s is not None and len(s.legs) == 2
    assert abs(s.net_greeks["delta"]) < 0.2   # ATM call+put ≈ delta-neutral
    assert len(s.breakevens) == 2


def test_iron_condor_is_credit():
    s = iron_condor(make_chain(), 100.0, 30 / 365, 0.05, body_pct=0.05, wing_pct=0.10)
    assert s is not None and len(s.legs) == 4
    assert s.is_credit                        # net credit received
    assert s.max_profit == pytest.approx(s.metadata["credit"] * 100)


def test_build_structure_unknown_returns_none():
    assert build_structure("nope", make_chain(), 100.0, 30 / 365, 0.05) is None


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def test_applicable_strategies_bullish_low_iv():
    out = applicable_strategies(strength=0.7, regime=Regime.TRENDING_UP, iv_rank=0.2)
    assert out[0] == "long_call"
    assert "call_debit_spread" in out


def test_applicable_strategies_bullish_high_iv_prefers_spread():
    out = applicable_strategies(strength=0.7, regime=Regime.TRENDING_UP, iv_rank=0.8)
    assert out[0] == "call_debit_spread"


def test_applicable_strategies_high_iv_range_has_condor():
    out = applicable_strategies(strength=0.0, regime=Regime.RANGE, iv_rank=0.8)
    assert "iron_condor" in out


def test_applicable_strategies_low_iv_has_long_vol():
    out = applicable_strategies(strength=0.0, regime=Regime.LOW_VOL, iv_rank=0.1)
    assert "long_straddle" in out and "long_strangle" in out


def test_select_candidates_bullish_top_is_call():
    chain = make_chain()
    cands = select_candidates(
        chain=chain, spot=100.0, strength=0.7, regime=Regime.TRENDING_UP, iv_rank=0.2, T=30 / 365,
    )
    assert len(cands) > 0
    assert cands[0].structure.net_greeks["delta"] > 0      # bullish structure on top
    assert all(0.0 <= c.score <= 1.0 for c in cands)
    # ranked descending
    assert cands == sorted(cands, key=lambda c: c.score, reverse=True)


def test_select_candidates_filters_reject_illiquid():
    chain = make_chain(volume=1, oi=1)
    cands = select_candidates(
        chain=chain, spot=100.0, strength=0.7, regime=Regime.TRENDING_UP, iv_rank=0.2, T=30 / 365,
        filters=LiquidityFilters(min_volume=100, min_open_interest=500),
    )
    assert cands == []


def test_select_candidates_explicit_strategy_list():
    chain = make_chain()
    cands = select_candidates(
        chain=chain, spot=100.0, strength=0.5, regime=Regime.RANGE, iv_rank=0.5, T=30 / 365,
        strategies=["long_straddle"],
    )
    assert len(cands) == 1 and cands[0].strategy == "long_straddle"
