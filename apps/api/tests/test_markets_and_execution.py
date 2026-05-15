"""Smoke tests for the new markets/, universe/, and execution/ skeletons."""

import asyncio
from unittest.mock import patch

import pandas as pd
import pytest

from execution import OrderRequest, get_executor
from execution.paper import PaperExecutor
from markets import get_market_adapter
from markets.crypto import CoinbaseAdapter
from markets.equity import EquityAdapter
from universe import get_universe_selector


def test_market_adapter_registry():
    assert isinstance(get_market_adapter("equity"), EquityAdapter)
    assert isinstance(get_market_adapter("crypto"), CoinbaseAdapter)


def test_market_adapter_unknown():
    with pytest.raises(ValueError):
        get_market_adapter("options")


def test_crypto_normalize_symbol():
    adapter = CoinbaseAdapter()
    assert adapter.normalize_symbol("btc") == "BTC-USD"
    assert adapter.normalize_symbol("eth/usd") == "ETH-USD"
    assert adapter.normalize_symbol("BTC-USDC") == "BTC-USDC"


def test_crypto_market_always_open():
    assert CoinbaseAdapter().is_market_open() is True


def test_universe_equity_default(monkeypatch):
    monkeypatch.delenv("EQUITY_UNIVERSE", raising=False)
    syms = get_universe_selector("equity").select()
    assert "AAPL" in syms


def test_universe_crypto_default(monkeypatch):
    monkeypatch.delenv("CRYPTO_UNIVERSE", raising=False)
    syms = get_universe_selector("crypto").select()
    assert any("-" in s for s in syms)


def test_paper_executor_fills_at_reference():
    px = 100.0
    order = OrderRequest(asset_class="crypto", symbol="BTC-USD", side="buy", qty=0.1, limit_px=px)
    fill = asyncio.run(PaperExecutor().place(order))
    assert fill.qty == 0.1
    assert fill.executor == "paper"
    assert fill.px > 0
    assert fill.fee >= 0


def test_paper_executor_requires_reference_px():
    order = OrderRequest(asset_class="crypto", symbol="BTC-USD", side="buy", qty=0.1)
    with pytest.raises(ValueError, match="reference price"):
        asyncio.run(PaperExecutor().place(order))


def test_paper_executor_zero_qty_returns_zero_fill():
    order = OrderRequest(asset_class="crypto", symbol="BTC-USD", side="buy", qty=0.0, limit_px=100.0)
    fill = asyncio.run(PaperExecutor().place(order))
    assert fill.qty == 0.0
    assert fill.fee == 0.0


def test_paper_executor_smallcap_uses_higher_slippage(monkeypatch):
    """Sub-$2 ref price should trigger smallcap_slippage_bps."""
    from config import settings as cfg
    monkeypatch.setattr(cfg, "smallcap_price_threshold_usd", 2.0)
    monkeypatch.setattr(cfg, "smallcap_slippage_bps", 100)
    monkeypatch.setattr(cfg, "base_slippage_bps", 5)

    order = OrderRequest(asset_class="crypto", symbol="PEPE-USD", side="buy", qty=10.0, limit_px=0.01)
    fill = asyncio.run(PaperExecutor().place(order))
    # smallcap path → 100 bps base; small order (notional < $1k) → ×0.5 → 50 bps
    assert fill.slippage_bps == 50.0


def test_paper_executor_sell_executes_below_ref():
    order = OrderRequest(asset_class="crypto", symbol="BTC-USD", side="sell", qty=0.1, limit_px=100.0)
    fill = asyncio.run(PaperExecutor().place(order))
    assert fill.px < 100.0
    assert fill.qty == 0.1


def test_coinbase_executor_requires_credentials(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "coinbase_api_key_name", "")
    monkeypatch.setattr(cfg, "coinbase_private_key", "")
    monkeypatch.setattr(cfg, "coinbase_api_key", "")
    monkeypatch.setattr(cfg, "coinbase_api_secret", "")

    from execution.coinbase import CoinbaseExecutor
    with pytest.raises(ValueError, match="Coinbase credentials missing"):
        CoinbaseExecutor()


def test_get_executor_default_paper(monkeypatch):
    monkeypatch.setattr("config.settings.executor_mode", "paper")
    assert isinstance(get_executor(), PaperExecutor)
