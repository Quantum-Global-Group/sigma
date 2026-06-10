"""Smoke tests for markets/, universe/, and the execution layer (OrderIntent)."""

import asyncio

import pytest

from execution import get_executor
from execution.base import ExecutionReport, OrderIntent, Side
from execution.paper import PaperExecutor
from markets import get_market_adapter
from markets.crypto import CoinbaseAdapter
from markets.equity import EquityAdapter
from universe import get_universe_selector


def _intent(**kw) -> OrderIntent:
    base = dict(asset_class="crypto", symbol="BTC-USD", side=Side.BUY, qty=0.1, limit_px=100.0)
    base.update(kw)
    return OrderIntent(**base)


# ─── markets / universe ───────────────────────────────────────────────────────

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


# ─── paper executor (OrderIntent -> ExecutionReport) ──────────────────────────

def test_paper_executor_fills_at_reference():
    report = asyncio.run(PaperExecutor().place(_intent(qty=0.1, limit_px=100.0)))
    assert isinstance(report, ExecutionReport)
    assert report.filled_qty == 0.1
    assert len(report.fills) == 1
    f = report.fills[0]
    assert f.executor == "paper"
    assert f.price > 0
    assert f.commission >= 0


def test_paper_executor_requires_reference_px():
    with pytest.raises(ValueError, match="reference price"):
        asyncio.run(PaperExecutor().place(_intent(limit_px=None)))


def test_paper_executor_zero_qty_rejected():
    report = asyncio.run(PaperExecutor().place(_intent(qty=0.0, limit_px=100.0)))
    assert report.filled_qty == 0.0
    assert report.fills == []
    assert report.order.status.value == "rejected"


def test_paper_executor_smallcap_uses_higher_slippage(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "smallcap_price_threshold_usd", 2.0)
    monkeypatch.setattr(cfg, "smallcap_slippage_bps", 100)
    monkeypatch.setattr(cfg, "base_slippage_bps", 5)

    report = asyncio.run(PaperExecutor().place(_intent(symbol="PEPE-USD", qty=10.0, limit_px=0.01)))
    # smallcap (sub-$2) → 100 bps; small notional (<$1k) → ×0.5 → 50 bps
    assert report.fills[0].slippage_bps == 50.0


def test_paper_executor_sell_executes_below_ref():
    report = asyncio.run(PaperExecutor().place(_intent(side=Side.SELL, qty=0.1, limit_px=100.0)))
    assert report.fills[0].price < 100.0
    assert report.filled_qty == 0.1


# ─── coinbase + alpaca guardrails ─────────────────────────────────────────────

def test_coinbase_executor_requires_credentials(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "coinbase_api_key_name", "")
    monkeypatch.setattr(cfg, "coinbase_private_key", "")
    monkeypatch.setattr(cfg, "coinbase_api_key", "")
    monkeypatch.setattr(cfg, "coinbase_api_secret", "")
    from execution.coinbase import CoinbaseExecutor
    with pytest.raises(ValueError, match="Coinbase credentials missing"):
        CoinbaseExecutor()


# ─── per-asset-class executor selection ───────────────────────────────────────

def test_get_executor_crypto_paper(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "executor_mode", "paper")
    monkeypatch.setattr(cfg, "crypto_executor", "paper")
    assert isinstance(get_executor("crypto"), PaperExecutor)


def test_get_executor_equity_paper(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "executor_mode", "paper")
    monkeypatch.setattr(cfg, "equity_executor", "paper")
    assert isinstance(get_executor("equity"), PaperExecutor)


def test_get_executor_unknown_mode(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "executor_mode", "paper")
    monkeypatch.setattr(cfg, "equity_executor", "bogus")
    with pytest.raises(ValueError, match="Unknown executor mode"):
        get_executor("equity")


# ─── legacy executor_mode override is crypto-only ─────────────────────────────

def test_legacy_executor_mode_does_not_hijack_equity(monkeypatch):
    """EXECUTOR_MODE=coinbase must never route equity to the Coinbase executor."""
    from config import settings as cfg
    monkeypatch.setattr(cfg, "executor_mode", "coinbase")
    monkeypatch.setattr(cfg, "equity_executor", "paper")
    assert isinstance(get_executor("equity"), PaperExecutor)


def test_legacy_executor_mode_does_not_hijack_forex_or_option(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "executor_mode", "coinbase")
    monkeypatch.setattr(cfg, "forex_executor", "paper")
    monkeypatch.setattr(cfg, "option_executor", "paper")
    assert isinstance(get_executor("forex"), PaperExecutor)
    assert isinstance(get_executor("option"), PaperExecutor)


def test_legacy_executor_mode_still_overrides_crypto(monkeypatch):
    """Back-compat: a non-paper executor_mode keeps selecting the crypto venue."""
    from execution import _resolve_mode
    from config import settings as cfg
    monkeypatch.setattr(cfg, "executor_mode", "coinbase")
    monkeypatch.setattr(cfg, "crypto_executor", "paper")
    assert _resolve_mode("crypto") == "coinbase"


def test_legacy_executor_mode_paper_defers_to_crypto_executor(monkeypatch):
    from execution import _resolve_mode
    from config import settings as cfg
    monkeypatch.setattr(cfg, "executor_mode", "paper")
    monkeypatch.setattr(cfg, "crypto_executor", "coinbase")
    assert _resolve_mode("crypto") == "coinbase"
