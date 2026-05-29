"""Moomoo connector tests (P1) — fully mocked SDK; no live OpenD needed.

A fake `moomoo` module is injected into sys.modules so the lazy enum imports
inside the adapter/executor resolve, and fake quote/trade contexts are injected
so no gateway is contacted.
"""

import sys
import types
from datetime import date, datetime, timezone

import asyncio
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def fake_moomoo(monkeypatch):
    m = types.ModuleType("moomoo")
    m.RET_OK = 0

    class TrdEnv:
        SIMULATE = "SIMULATE"
        REAL = "REAL"

    class TrdSide:
        BUY = "BUY"
        SELL = "SELL"

    class OrderType:
        MARKET = "MARKET"
        NORMAL = "NORMAL"

    class KLType:
        K_DAY = "K_DAY"
        K_5M = "K_5M"
        K_60M = "K_60M"
        K_1M = "K_1M"

    class TrdMarket:
        US = "US"

    class SecurityFirm:
        FUTUINC = "FUTUINC"

    m.TrdEnv, m.TrdSide, m.OrderType = TrdEnv, TrdSide, OrderType
    m.KLType, m.TrdMarket, m.SecurityFirm = KLType, TrdMarket, SecurityFirm
    m.OpenQuoteContext = object
    m.OpenSecTradeContext = object
    monkeypatch.setitem(sys.modules, "moomoo", m)
    return m


# ---------------------------------------------------------------------------
# markets/options.py — OptionDataProvider
# ---------------------------------------------------------------------------

class _FakeQuoteCtx:
    def get_option_expiration_date(self, code):
        return (0, pd.DataFrame({"strike_time": ["2026-01-16", "2026-02-20"]}))

    def get_option_chain(self, code, start, end):
        return (0, pd.DataFrame({
            "code": ["US.AAPL260116C00250000", "US.AAPL260116P00250000"],
            "strike_price": [250.0, 250.0],
            "option_type": ["CALL", "PUT"],
        }))

    def get_market_snapshot(self, codes):
        return (0, pd.DataFrame({
            "code": codes,
            "bid_price": [3.0] * len(codes),
            "ask_price": [3.2] * len(codes),
            "last_price": [3.1] * len(codes),
            "volume": [500] * len(codes),
            "option_open_interest": [1200] * len(codes),
            "option_implied_volatility": [28.5] * len(codes),
            "option_delta": [0.45] * len(codes),
            "option_gamma": [0.03] * len(codes),
            "option_theta": [-0.05] * len(codes),
            "option_vega": [0.12] * len(codes),
        }))


def test_option_contract_occ_symbol():
    from markets.options import OptionContract
    c = OptionContract(underlying="AAPL", expiry=date(2026, 1, 16), strike=250.0, right="call", code="x")
    assert c.occ == "AAPL260116C00250000"


def test_list_expiries():
    from markets.options import MoomooOptionData
    prov = MoomooOptionData(quote_ctx=_FakeQuoteCtx())
    exps = prov.list_expiries("AAPL")
    assert exps == [date(2026, 1, 16), date(2026, 2, 20)]


def test_get_chain_parses_calls_and_puts():
    from markets.options import MoomooOptionData
    prov = MoomooOptionData(quote_ctx=_FakeQuoteCtx())
    chain = prov.get_chain("AAPL", date(2026, 1, 16))
    assert len(chain) == 2
    assert {c.right for c in chain} == {"call", "put"}
    assert all(c.strike == 250.0 for c in chain)


def test_get_quotes_normalizes_greeks_and_mid():
    from markets.options import MoomooOptionData, OptionContract
    prov = MoomooOptionData(quote_ctx=_FakeQuoteCtx())
    c = OptionContract("AAPL", date(2026, 1, 16), 250.0, "call", "US.AAPL260116C00250000")
    q = prov.get_quote(c)
    assert q is not None
    assert q.mid == pytest.approx(3.1)
    assert q.open_interest == 1200
    assert q.delta == pytest.approx(0.45)


def test_chain_query_failure_returns_empty():
    class Bad(_FakeQuoteCtx):
        def get_option_chain(self, code, start, end):
            return (-1, "error")

    from markets.options import MoomooOptionData
    prov = MoomooOptionData(quote_ctx=Bad())
    assert prov.get_chain("AAPL", date(2026, 1, 16)) == []


# ---------------------------------------------------------------------------
# markets/moomoo.py — MoomooAdapter (underlying OHLCV)
# ---------------------------------------------------------------------------

class _FakeKlineCtx:
    def request_history_kline(self, code, start, end, ktype):
        df = pd.DataFrame({
            "time_key": ["2026-01-02", "2026-01-03", "2026-01-04"],
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [1e6, 1.1e6, 1.2e6],
        })
        return (0, df)


def test_adapter_fetch_ohlcv_normalizes():
    from markets.moomoo import MoomooAdapter
    a = MoomooAdapter(quote_ctx=_FakeKlineCtx())
    df = a.fetch_ohlcv("AAPL", "daily")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "date"
    assert len(df) == 3
    assert df["close"].iloc[-1] == pytest.approx(102.5)


def test_adapter_fetch_ohlcv_raises_on_empty():
    class Empty:
        def request_history_kline(self, **k):
            return (-1, "no data")

    from markets.moomoo import MoomooAdapter
    a = MoomooAdapter(quote_ctx=Empty())
    with pytest.raises(ValueError):
        a.fetch_ohlcv("AAPL", "daily")


def test_adapter_market_hours():
    from markets.moomoo import MoomooAdapter
    a = MoomooAdapter(quote_ctx=_FakeKlineCtx())
    sat = datetime(2026, 1, 17, 15, 0, tzinfo=timezone.utc)        # Saturday
    assert a.is_market_open(sat) is False
    wed_open = datetime(2026, 1, 14, 15, 0, tzinfo=timezone.utc)   # Wed 10:00 ET
    assert a.is_market_open(wed_open) is True


# ---------------------------------------------------------------------------
# execution/moomoo.py — MoomooExecutor
# ---------------------------------------------------------------------------

def _intent(qty=1):
    from execution.base import OrderIntent, OrderType, Side, TimeInForce
    return OrderIntent(
        asset_class="option", symbol="US.AAPL260116C00250000", side=Side.BUY,
        order_type=OrderType.MARKET, qty=qty, limit_px=3.10,
        time_in_force=TimeInForce.DAY, client_order_id="option:AAPL:buy:1",
    )


class _FakeTradeCtx:
    def __init__(self, status="FILLED_ALL", dealt_qty=1, avg=3.11):
        self._status, self._qty, self._avg = status, dealt_qty, avg

    def place_order(self, **kwargs):
        return (0, pd.DataFrame({
            "order_id": ["ORD-1"], "order_status": [self._status],
            "dealt_qty": [self._qty], "dealt_avg_price": [self._avg],
        }))

    def order_list_query(self, **kwargs):
        return (0, pd.DataFrame({
            "order_id": ["ORD-1"], "order_status": [self._status],
            "dealt_qty": [self._qty], "dealt_avg_price": [self._avg],
        }))

    def accinfo_query(self, **kwargs):
        return (0, pd.DataFrame({"total_assets": [25000.0], "cash": [10000.0]}))


def test_executor_live_guardrail(monkeypatch):
    monkeypatch.setattr("config.settings.moomoo_paper", False)
    monkeypatch.setattr("config.settings.moomoo_allow_live", False)
    from execution.moomoo import MoomooExecutor
    with pytest.raises(ValueError, match="Live Moomoo trading is disabled"):
        MoomooExecutor(trade_ctx=_FakeTradeCtx())


def test_executor_place_fills():
    from execution.moomoo import MoomooExecutor
    from execution.base import OrderStatus
    ex = MoomooExecutor(trade_ctx=_FakeTradeCtx())
    report = asyncio.run(ex.place(_intent()))
    assert report.order.status == OrderStatus.FILLED
    assert report.filled_qty == 1.0
    assert report.fills and report.fills[0].price == pytest.approx(3.11)
    assert report.fills[0].executor == "moomoo"


def test_executor_rejects_zero_qty():
    from execution.moomoo import MoomooExecutor
    from execution.base import OrderStatus
    ex = MoomooExecutor(trade_ctx=_FakeTradeCtx())
    report = asyncio.run(ex.place(_intent(qty=0)))
    assert report.order.status == OrderStatus.REJECTED


def test_executor_place_broker_error():
    class Bad(_FakeTradeCtx):
        def place_order(self, **k):
            return (-1, "insufficient buying power")

    from execution.moomoo import MoomooExecutor
    from execution.base import OrderStatus
    ex = MoomooExecutor(trade_ctx=Bad())
    report = asyncio.run(ex.place(_intent()))
    assert report.order.status == OrderStatus.REJECTED
    assert "insufficient" in (report.order.rejected_reason or "")


def test_executor_get_account_equity():
    from execution.moomoo import MoomooExecutor
    ex = MoomooExecutor(trade_ctx=_FakeTradeCtx())
    assert asyncio.run(ex.get_account_equity()) == pytest.approx(25000.0)


def test_get_executor_routes_option_to_paper(monkeypatch):
    monkeypatch.setattr("config.settings.option_executor", "paper")
    monkeypatch.setattr("config.settings.executor_mode", "paper")
    from execution import get_executor
    from execution.paper import PaperExecutor
    assert isinstance(get_executor("option"), PaperExecutor)
