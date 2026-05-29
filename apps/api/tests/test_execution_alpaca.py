"""AlpacaExecutor tests.

Guardrail tests run everywhere (they trip before the SDK is imported). The
fill-path test needs alpaca-py installed (present in CI via requirements) and
is skipped otherwise."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from execution.base import OrderIntent, OrderType, Side, TimeInForce


def _intent(**kw) -> OrderIntent:
    base = dict(
        asset_class="equity", symbol="AAPL", side=Side.BUY,
        order_type=OrderType.MARKET, qty=1, limit_px=100.0,
        time_in_force=TimeInForce.DAY, client_order_id="equity:AAPL:buy:1",
    )
    base.update(kw)
    return OrderIntent(**base)


def test_alpaca_requires_credentials(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "alpaca_api_key", "")
    monkeypatch.setattr(cfg, "alpaca_secret", "")
    from execution.alpaca import AlpacaExecutor
    with pytest.raises(ValueError, match="Alpaca credentials missing"):
        AlpacaExecutor()


def test_alpaca_live_requires_explicit_optin(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "alpaca_api_key", "k")
    monkeypatch.setattr(cfg, "alpaca_secret", "s")
    monkeypatch.setattr(cfg, "alpaca_paper", False)
    monkeypatch.setattr(cfg, "alpaca_allow_live", False)
    from execution.alpaca import AlpacaExecutor
    with pytest.raises(ValueError, match="Live Alpaca trading is disabled"):
        AlpacaExecutor()


def test_alpaca_place_fills(monkeypatch):
    pytest.importorskip("alpaca")  # needs alpaca-py (CI has it)
    from config import settings as cfg
    monkeypatch.setattr(cfg, "alpaca_api_key", "k")
    monkeypatch.setattr(cfg, "alpaca_secret", "s")
    monkeypatch.setattr(cfg, "alpaca_paper", True)
    monkeypatch.setattr(cfg, "alpaca_allow_fractional", False)

    fake_client = MagicMock()
    fake_client.submit_order.return_value = MagicMock(id="order-123")
    filled = MagicMock()
    filled.status = "filled"
    filled.filled_qty = "1"
    filled.filled_avg_price = "100.50"
    fake_client.get_order_by_id.return_value = filled

    with patch("alpaca.trading.client.TradingClient", return_value=fake_client):
        from execution.alpaca import AlpacaExecutor
        ex = AlpacaExecutor()
        report = asyncio.run(ex.place(_intent(qty=1, limit_px=100.0)))

    assert report.order.order_id == "order-123"
    assert report.filled_qty == 1.0
    assert report.fills and report.fills[0].price == 100.50
    assert report.fills[0].executor == "alpaca"


def test_alpaca_buy_without_qty_or_notional_rejected(monkeypatch):
    pytest.importorskip("alpaca")
    from config import settings as cfg
    monkeypatch.setattr(cfg, "alpaca_api_key", "k")
    monkeypatch.setattr(cfg, "alpaca_secret", "s")
    monkeypatch.setattr(cfg, "alpaca_paper", True)

    with patch("alpaca.trading.client.TradingClient", return_value=MagicMock()):
        from execution.alpaca import AlpacaExecutor
        ex = AlpacaExecutor()
        report = asyncio.run(ex.place(_intent(qty=None, notional=None)))

    assert report.order.status.value == "rejected"
    assert "qty or notional" in (report.order.rejected_reason or "")


# ---------------------------------------------------------------------------
# get_account_equity (A8)
# ---------------------------------------------------------------------------

def _executor_with_account(monkeypatch, account):
    pytest.importorskip("alpaca")
    from config import settings as cfg
    monkeypatch.setattr(cfg, "alpaca_api_key", "k")
    monkeypatch.setattr(cfg, "alpaca_secret", "s")
    monkeypatch.setattr(cfg, "alpaca_paper", True)
    fake_client = MagicMock()
    if isinstance(account, Exception):
        fake_client.get_account.side_effect = account
    else:
        fake_client.get_account.return_value = account
    with patch("alpaca.trading.client.TradingClient", return_value=fake_client):
        from execution.alpaca import AlpacaExecutor
        return AlpacaExecutor()


def test_get_account_equity_returns_float(monkeypatch):
    ex = _executor_with_account(monkeypatch, MagicMock(equity="25123.45", cash="100.0"))
    assert asyncio.run(ex.get_account_equity()) == pytest.approx(25123.45)


def test_get_account_equity_falls_back_to_cash(monkeypatch):
    acct = MagicMock(equity=None)
    acct.cash = "777.0"
    ex = _executor_with_account(monkeypatch, acct)
    assert asyncio.run(ex.get_account_equity()) == pytest.approx(777.0)


def test_get_account_equity_none_on_error(monkeypatch):
    ex = _executor_with_account(monkeypatch, RuntimeError("api down"))
    assert asyncio.run(ex.get_account_equity()) is None
