"""OANDA forex connector tests (PR-A) — fully mocked SDK; no live OANDA needed.

A fake `oandapyV20` package is injected into sys.modules so the lazy imports
inside the adapter/executor resolve, and a fake `api` (with a `.request` that
populates `req.response`) is injected so no network call is made.
"""

import sys
import types
from datetime import datetime, timezone

import asyncio
import pytest


# ---------------------------------------------------------------------------
# Fake oandapyV20 package: oandapyV20.API + endpoints.{instruments,orders,accounts}
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_oanda(monkeypatch):
    root = types.ModuleType("oandapyV20")

    class API:  # not used directly (we inject api=), but the lazy import needs it
        def __init__(self, *a, **k):
            pass

        def request(self, req):
            return getattr(req, "response", None)

    root.API = API

    endpoints = types.ModuleType("oandapyV20.endpoints")
    instruments = types.ModuleType("oandapyV20.endpoints.instruments")
    orders = types.ModuleType("oandapyV20.endpoints.orders")
    accounts = types.ModuleType("oandapyV20.endpoints.accounts")

    class InstrumentsCandles:
        def __init__(self, instrument, params=None):
            self.instrument = instrument
            self.params = params or {}
            self.response = None

    class OrderCreate:
        def __init__(self, accountID, data=None):
            self.accountID = accountID
            self.data = data or {}
            self.response = None

    class AccountSummary:
        def __init__(self, accountID):
            self.accountID = accountID
            self.response = None

    instruments.InstrumentsCandles = InstrumentsCandles
    orders.OrderCreate = OrderCreate
    accounts.AccountSummary = AccountSummary

    monkeypatch.setitem(sys.modules, "oandapyV20", root)
    monkeypatch.setitem(sys.modules, "oandapyV20.endpoints", endpoints)
    monkeypatch.setitem(sys.modules, "oandapyV20.endpoints.instruments", instruments)
    monkeypatch.setitem(sys.modules, "oandapyV20.endpoints.orders", orders)
    monkeypatch.setitem(sys.modules, "oandapyV20.endpoints.accounts", accounts)
    return root


# ---------------------------------------------------------------------------
# markets/oanda.py — OandaAdapter
# ---------------------------------------------------------------------------

class _FakeCandlesApi:
    """request() fills req.response with a canned 3-candle payload (+ 1 incomplete)."""

    def request(self, req):
        req.response = {
            "instrument": req.instrument,
            "granularity": req.params.get("granularity"),
            "candles": [
                {"complete": True, "time": "2026-01-02T00:00:00Z",
                 "mid": {"o": "1.1000", "h": "1.1050", "l": "1.0950", "c": "1.1020"}, "volume": 1000},
                {"complete": True, "time": "2026-01-02T04:00:00Z",
                 "mid": {"o": "1.1020", "h": "1.1080", "l": "1.1010", "c": "1.1075"}, "volume": 1200},
                {"complete": True, "time": "2026-01-02T08:00:00Z",
                 "mid": {"o": "1.1075", "h": "1.1090", "l": "1.1040", "c": "1.1060"}, "volume": 900},
                {"complete": False, "time": "2026-01-02T12:00:00Z",
                 "mid": {"o": "1.1060", "h": "1.1065", "l": "1.1055", "c": "1.1058"}, "volume": 50},
            ],
        }
        return req.response


def test_adapter_fetch_ohlcv_normalizes_and_skips_incomplete():
    from markets.oanda import OandaAdapter
    a = OandaAdapter(api=_FakeCandlesApi())
    df = a.fetch_ohlcv("EUR_USD", "4h")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "date"
    assert len(df) == 3                       # incomplete bar dropped
    assert df["close"].iloc[-1] == pytest.approx(1.1060)


def test_adapter_instrument_format():
    from markets.oanda import OandaAdapter
    a = OandaAdapter(api=_FakeCandlesApi())
    assert a.normalize_symbol("eur/usd") == "EUR_USD"
    assert a.normalize_symbol("GBPUSD") == "GBP_USD"
    assert a.normalize_symbol("USD-CAD") == "USD_CAD"


def test_adapter_granularity_mapping():
    from markets.oanda import OandaAdapter
    a = OandaAdapter(api=_FakeCandlesApi())
    assert a._granularity("4h") == "H4"
    assert a._granularity("daily") == "D"
    assert a._granularity("unknown") == "H4"   # default


def test_adapter_raises_on_empty():
    class Empty:
        def request(self, req):
            req.response = {"candles": []}
            return req.response

    from markets.oanda import OandaAdapter
    a = OandaAdapter(api=Empty())
    with pytest.raises(ValueError):
        a.fetch_ohlcv("EUR_USD", "4h")


def test_adapter_market_hours():
    from markets.oanda import OandaAdapter
    a = OandaAdapter(api=_FakeCandlesApi())
    sat = datetime(2026, 1, 17, 12, 0, tzinfo=timezone.utc)        # Saturday → closed
    assert a.is_market_open(sat) is False
    sun_early = datetime(2026, 1, 18, 12, 0, tzinfo=timezone.utc)  # Sunday 12:00 → still closed
    assert a.is_market_open(sun_early) is False
    sun_open = datetime(2026, 1, 18, 22, 0, tzinfo=timezone.utc)   # Sunday 22:00 → open
    assert a.is_market_open(sun_open) is True
    wed = datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc)        # Wednesday → open
    assert a.is_market_open(wed) is True
    fri_late = datetime(2026, 1, 16, 22, 0, tzinfo=timezone.utc)   # Friday 22:00 → closed
    assert a.is_market_open(fri_late) is False


# ---------------------------------------------------------------------------
# execution/oanda.py — OandaExecutor
# ---------------------------------------------------------------------------

def _intent(qty=1000, side=None):
    from execution.base import OrderIntent, OrderType, Side, TimeInForce
    return OrderIntent(
        asset_class="forex", symbol="EUR_USD", side=side or Side.BUY,
        order_type=OrderType.MARKET, qty=qty, limit_px=1.1050,
        time_in_force=TimeInForce.FOK, client_order_id="forex:EUR_USD:buy:1",
    )


class _FakeTradeApi:
    def __init__(self, fill=True, price="1.1051", units="1000"):
        self._fill, self._price, self._units = fill, price, units

    def request(self, req):
        if type(req).__name__ == "OrderCreate":
            if self._fill:
                req.response = {
                    "orderCreateTransaction": {"id": "100"},
                    "orderFillTransaction": {
                        "id": "101", "price": self._price, "units": self._units, "commission": "0",
                    },
                }
            else:
                req.response = {"orderCreateTransaction": {"id": "100"}}
        elif type(req).__name__ == "AccountSummary":
            req.response = {"account": {"NAV": "10250.50", "balance": "10000.0"}}
        return req.response


@pytest.fixture(autouse=True)
def _oanda_creds(monkeypatch):
    monkeypatch.setattr("config.settings.oanda_api_token", "fake-token")
    monkeypatch.setattr("config.settings.oanda_account_id", "001-001-1234567-001")
    monkeypatch.setattr("config.settings.oanda_paper", True)
    monkeypatch.setattr("config.settings.oanda_allow_live", False)


def test_executor_live_guardrail(monkeypatch):
    monkeypatch.setattr("config.settings.oanda_paper", False)
    monkeypatch.setattr("config.settings.oanda_allow_live", False)
    from execution.oanda import OandaExecutor
    with pytest.raises(ValueError, match="Live OANDA trading is disabled"):
        OandaExecutor(api=_FakeTradeApi())


def test_executor_missing_creds(monkeypatch):
    monkeypatch.setattr("config.settings.oanda_api_token", "")
    from execution.oanda import OandaExecutor
    with pytest.raises(ValueError, match="credentials missing"):
        OandaExecutor(api=_FakeTradeApi())


def test_executor_place_buy_fills():
    from execution.oanda import OandaExecutor
    from execution.base import OrderStatus
    ex = OandaExecutor(api=_FakeTradeApi())
    report = asyncio.run(ex.place(_intent()))
    assert report.order.status == OrderStatus.FILLED
    assert report.filled_qty == 1000.0
    assert report.fills and report.fills[0].price == pytest.approx(1.1051)
    assert report.fills[0].executor == "oanda"


def test_executor_place_sell_signs_units():
    from execution.oanda import OandaExecutor
    from execution.base import Side
    captured = {}

    class CapApi(_FakeTradeApi):
        def request(self, req):
            if type(req).__name__ == "OrderCreate":
                captured["units"] = req.data["order"]["units"]
            return super().request(req)

    ex = OandaExecutor(api=CapApi(units="500"))
    asyncio.run(ex.place(_intent(qty=500, side=Side.SELL)))
    assert captured["units"] == "-500"        # SELL → negative units


def test_executor_rejects_zero_qty():
    from execution.oanda import OandaExecutor
    from execution.base import OrderStatus
    ex = OandaExecutor(api=_FakeTradeApi())
    report = asyncio.run(ex.place(_intent(qty=0)))
    assert report.order.status == OrderStatus.REJECTED


def test_executor_unfilled_order_submitted():
    from execution.oanda import OandaExecutor
    from execution.base import OrderStatus
    ex = OandaExecutor(api=_FakeTradeApi(fill=False))
    report = asyncio.run(ex.place(_intent()))
    assert report.order.status == OrderStatus.SUBMITTED
    assert report.fills == []


def test_executor_get_account_equity():
    from execution.oanda import OandaExecutor
    ex = OandaExecutor(api=_FakeTradeApi())
    assert asyncio.run(ex.get_account_equity()) == pytest.approx(10250.50)


# ---------------------------------------------------------------------------
# registration wiring
# ---------------------------------------------------------------------------

def test_get_market_adapter_forex():
    from markets import get_market_adapter
    from markets.oanda import OandaAdapter
    assert isinstance(get_market_adapter("forex"), OandaAdapter)


def test_get_universe_selector_forex(monkeypatch):
    monkeypatch.delenv("FOREX_UNIVERSE", raising=False)
    from universe import get_universe_selector
    sel = get_universe_selector("forex")
    pairs = sel.select()
    assert "EUR_USD" in pairs and all("_" in p for p in pairs)


def test_get_executor_routes_forex_to_paper(monkeypatch):
    monkeypatch.setattr("config.settings.forex_executor", "paper")
    monkeypatch.setattr("config.settings.executor_mode", "paper")
    from execution import get_executor
    from execution.paper import PaperExecutor
    assert isinstance(get_executor("forex"), PaperExecutor)


def test_get_executor_routes_forex_to_oanda(monkeypatch):
    monkeypatch.setattr("config.settings.forex_executor", "oanda")
    monkeypatch.setattr("config.settings.executor_mode", "paper")
    from execution import get_executor
    ex = get_executor("forex")
    assert ex.name == "oanda"


def test_forex_strategies_exclude_sde(monkeypatch):
    monkeypatch.setattr("config.settings.forex_strategies",
                        "momentum,mean_reversion,breakout,regime,ml,macd,fourier")
    from ml.strategies import build_default_combiner
    combiner = build_default_combiner("forex")
    names = set(combiner.strategies.keys())
    assert "gbm" not in names and "ou" not in names and "heston" not in names
    assert "momentum" in names


def test_default_timeframe_forex():
    import sys
    from pathlib import Path
    wd = Path(__file__).parents[2] / "worker"
    if str(wd) not in sys.path:
        sys.path.insert(0, str(wd))
    from tick import _default_timeframe
    assert _default_timeframe("forex") == "4h"
