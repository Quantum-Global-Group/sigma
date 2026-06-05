"""Synthetic offline providers (PR-P) — the substrate for a no-creds full run."""

from __future__ import annotations

import os
from datetime import date

import pytest

import markets
from sim.synthetic import (
    SyntheticCryptoAdapter,
    SyntheticEquityAdapter,
    SyntheticForexAdapter,
    SyntheticOptionData,
    install_synthetic_providers,
)


@pytest.fixture
def restore_registry(monkeypatch):
    """Save/restore the global market registry + OPTION_DATA_PROVIDER so installing
    synthetics in a test never leaks into other tests."""
    saved = dict(markets._REGISTRY)
    saved_env = os.environ.get("OPTION_DATA_PROVIDER")
    yield
    markets._REGISTRY.clear()
    markets._REGISTRY.update(saved)
    if saved_env is None:
        os.environ.pop("OPTION_DATA_PROVIDER", None)
    else:
        os.environ["OPTION_DATA_PROVIDER"] = saved_env


# ---------------------------------------------------------------------------
# adapters produce usable OHLCV
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("adapter,tf", [
    (SyntheticEquityAdapter(), "daily"),
    (SyntheticCryptoAdapter(), "5m"),
    (SyntheticForexAdapter(), "4h"),
])
def test_synthetic_adapter_ohlcv(adapter, tf):
    df = adapter.fetch_ohlcv("TEST", tf)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) > 50 and (df["close"] > 0).all()
    assert adapter.is_market_open() is True        # always open → loop ticks any time


def test_crypto_normalizes_to_usd_pair():
    assert SyntheticCryptoAdapter().normalize_symbol("btc") == "BTC-USD"


def test_forex_normalizes_to_underscore_pair():
    assert SyntheticForexAdapter().normalize_symbol("eurusd") == "EUR_USD"


# ---------------------------------------------------------------------------
# synthetic option chain
# ---------------------------------------------------------------------------

def test_synthetic_option_chain_and_quotes():
    prov = SyntheticOptionData(spot=150.0)
    exps = prov.list_expiries("AAPL")
    assert exps and all(isinstance(e, date) for e in exps)
    chain = prov.get_chain("AAPL", exps[0])
    assert {c.right for c in chain} == {"call", "put"}
    quotes = prov.get_quotes(chain)
    assert len(quotes) == len(chain)
    q = quotes[0]
    assert q.bid > 0 and q.ask >= q.bid and q.open_interest > 0
    assert q.delta is not None and q.implied_vol == 0.30   # liquid → passes gates


# ---------------------------------------------------------------------------
# installer
# ---------------------------------------------------------------------------

def test_install_swaps_registry_and_enables_option_provider(restore_registry, monkeypatch):
    monkeypatch.setattr("config.settings.oanda_api_token", "")   # no token → forex synthetic
    installed = install_synthetic_providers()
    assert set(installed) == {"equity", "crypto", "option", "forex"}
    assert isinstance(markets._REGISTRY["equity"], SyntheticEquityAdapter)
    assert isinstance(markets._REGISTRY["forex"], SyntheticForexAdapter)
    assert os.environ["OPTION_DATA_PROVIDER"] == "synthetic"
    # and the factory now returns the synthetic provider
    from markets.options import get_option_data_provider
    assert isinstance(get_option_data_provider(), SyntheticOptionData)


def test_install_keeps_real_forex_when_oanda_token_set(restore_registry, monkeypatch):
    monkeypatch.setattr("config.settings.oanda_api_token", "fake-token")
    from markets.oanda import OandaAdapter
    installed = install_synthetic_providers()
    assert "forex" not in installed                       # real OANDA retained
    assert isinstance(markets._REGISTRY["forex"], OandaAdapter)
