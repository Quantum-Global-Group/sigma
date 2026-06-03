import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest


def _sync_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_mt5_adapter_fetch_ohlcv_and_symbol_normalization(monkeypatch):
    monkeypatch.setattr("config.settings.mt5_bridge_url", "http://mt5.local:8787")
    monkeypatch.setattr("config.settings.mt5_bridge_secret", "secret")

    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["secret"] = req.headers.get("x-mt5-bridge-secret")
        return httpx.Response(200, json={
            "candles": [
                {"date": "2026-01-02T00:00:00Z", "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 10},
                {"time": "2026-01-02T04:00:00Z", "open": "1.15", "high": "1.22", "low": "1.1", "close": "1.2", "volume": "12"},
            ]
        })

    from markets.mt5_bridge import Mt5BridgeAdapter
    a = Mt5BridgeAdapter(client=_sync_client(handler))
    df = a.fetch_ohlcv("EUR_USD", "4h")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "date"
    assert len(df) == 2
    assert df["close"].iloc[-1] == pytest.approx(1.2)
    assert "symbol=EURUSD" in captured["url"]
    assert captured["secret"] == "secret"
    assert a.normalize_symbol("GBPUSD") == "GBP_USD"


def test_mt5_adapter_market_hours():
    from markets.mt5_bridge import Mt5BridgeAdapter
    a = Mt5BridgeAdapter(base_url="http://mt5.local")
    sat = datetime(2026, 1, 17, 12, 0, tzinfo=timezone.utc)
    wed = datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc)
    assert a.is_market_open(sat) is False
    assert a.is_market_open(wed) is True


def _intent(qty=1000, side=None):
    from execution.base import OrderIntent, OrderType, Side, TimeInForce
    return OrderIntent(
        asset_class="forex",
        symbol="EUR_USD",
        side=side or Side.BUY,
        order_type=OrderType.MARKET,
        qty=qty,
        limit_px=1.105,
        time_in_force=TimeInForce.DAY,
        client_order_id="forex:EUR_USD:buy:1",
    )


@pytest.fixture(autouse=True)
def _mt5_settings(monkeypatch):
    monkeypatch.setattr("config.settings.mt5_bridge_url", "http://mt5.local:8787")
    monkeypatch.setattr("config.settings.mt5_bridge_secret", "secret")
    monkeypatch.setattr("config.settings.mt5_paper", True)
    monkeypatch.setattr("config.settings.mt5_allow_live", False)
    monkeypatch.setattr("config.settings.mt5_qty_is_lots", False)
    monkeypatch.setattr("config.settings.mt5_units_per_lot", 100_000.0)
    monkeypatch.setattr("config.settings.mt5_deviation_points", 20)


def test_mt5_executor_place_converts_units_to_lots():
    captured = {}

    def handler(req):
        if req.url.path == "/orders":
            captured.update(json.loads(req.content.decode()))
            return httpx.Response(200, json={
                "ticket": "123",
                "status": "filled",
                "volume": 0.01,
                "price": 1.106,
                "commission": 0,
            })
        if req.url.path == "/account":
            return httpx.Response(200, json={"equity": 10000})
        return httpx.Response(404)

    from execution.mt5_bridge import Mt5BridgeExecutor
    from execution.base import OrderStatus
    ex = Mt5BridgeExecutor(client=_sync_client(handler))
    report = asyncio.run(ex.place(_intent(qty=1000)))
    assert captured["symbol"] == "EURUSD"
    assert captured["volume"] == pytest.approx(0.01)
    assert report.order.status == OrderStatus.FILLED
    assert report.fills[0].executor == "mt5_bridge"


def test_mt5_executor_live_guardrail(monkeypatch):
    monkeypatch.setattr("config.settings.mt5_paper", False)
    monkeypatch.setattr("config.settings.mt5_allow_live", False)
    from execution.mt5_bridge import Mt5BridgeExecutor
    with pytest.raises(ValueError, match="Live MT5 trading is disabled"):
        Mt5BridgeExecutor(client=_sync_client(lambda req: httpx.Response(200, json={})))


def test_mt5_executor_get_account_equity():
    def handler(req):
        return httpx.Response(200, json={"balance": 9000, "equity": 9123.45})

    from execution.mt5_bridge import Mt5BridgeExecutor
    ex = Mt5BridgeExecutor(client=_sync_client(handler))
    assert asyncio.run(ex.get_account_equity()) == pytest.approx(9123.45)


def test_forex_routing_selects_mt5_symbols(monkeypatch):
    monkeypatch.setattr("config.settings.forex_mt5_symbols", "EURUSD,XAU_USD")
    from markets.forex_routing import compact_forex_symbol, is_mt5_symbol
    assert compact_forex_symbol("EUR_USD") == "EURUSD"
    assert is_mt5_symbol("EUR_USD")
    assert is_mt5_symbol("XAUUSD")
    assert not is_mt5_symbol("GBP_USD")
