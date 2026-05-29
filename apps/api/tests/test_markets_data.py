"""Equity data provider-chain tests (A6) — all offline (no HTTP/SDK calls).

Verifies markets.equity_data.fetch_equity_ohlcv honors provider order, skips
providers that return None (missing creds / empty / error), and raises when
every provider yields nothing. Also checks the credential short-circuits in the
individual provider fns.
"""

import pandas as pd
import pytest

from markets import equity_data


def _sample_df(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1e6},
        index=idx,
    )


def _stub_providers(monkeypatch, mapping, calls):
    """Rebind equity_data._PROVIDERS with call-recording stubs."""
    def make(name, result):
        def _fn(symbol, timeframe):
            calls.append(name)
            return result() if callable(result) else result
        return _fn
    monkeypatch.setattr(equity_data, "_PROVIDERS", {n: make(n, r) for n, r in mapping.items()})


def test_provider_order_first_wins(monkeypatch):
    calls = []
    _stub_providers(monkeypatch, {
        "tiingo": _sample_df, "alpaca": None, "yfinance": None,
    }, calls)
    monkeypatch.setattr("config.settings.equity_data_providers", "tiingo,alpaca,yfinance")
    df = equity_data.fetch_equity_ohlcv("AAPL", "daily")
    assert not df.empty
    assert calls == ["tiingo"]  # short-circuits on first hit


def test_provider_falls_through_to_next(monkeypatch):
    calls = []
    _stub_providers(monkeypatch, {
        "tiingo": None, "alpaca": _sample_df, "yfinance": None,
    }, calls)
    monkeypatch.setattr("config.settings.equity_data_providers", "tiingo,alpaca,yfinance")
    df = equity_data.fetch_equity_ohlcv("AAPL", "daily")
    assert not df.empty
    assert calls == ["tiingo", "alpaca"]  # tiingo skipped, alpaca served


def test_all_providers_empty_raises(monkeypatch):
    calls = []
    _stub_providers(monkeypatch, {
        "tiingo": None, "alpaca": None, "yfinance": None,
    }, calls)
    monkeypatch.setattr("config.settings.equity_data_providers", "tiingo,alpaca,yfinance")
    with pytest.raises(ValueError, match="No equity data"):
        equity_data.fetch_equity_ohlcv("AAPL", "daily")


def test_unknown_provider_skipped(monkeypatch):
    calls = []
    _stub_providers(monkeypatch, {"yfinance": _sample_df}, calls)
    monkeypatch.setattr("config.settings.equity_data_providers", "bogus,yfinance")
    df = equity_data.fetch_equity_ohlcv("AAPL", "daily")
    assert not df.empty
    assert calls == ["yfinance"]


def test_tiingo_no_key_returns_none(monkeypatch):
    monkeypatch.setattr("config.settings.tiingo_api_key", "")
    assert equity_data.fetch_tiingo("AAPL", "daily") is None


def test_tiingo_daily_prefers_adjusted_and_dedups(monkeypatch):
    """Tiingo daily returns raw AND adjusted columns; we must keep a single,
    adjusted OHLCV set (regression for the duplicate-`close` bug)."""
    monkeypatch.setattr("config.settings.tiingo_api_key", "k")
    rows = [
        {"date": "2024-01-01T00:00:00.000Z",
         "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100,
         "adjOpen": 5, "adjHigh": 5.5, "adjLow": 4.5, "adjClose": 5.25, "adjVolume": 200},
        {"date": "2024-01-02T00:00:00.000Z",
         "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 110,
         "adjOpen": 5.5, "adjHigh": 6, "adjLow": 5, "adjClose": 5.75, "adjVolume": 220},
    ]

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return rows

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): return _Resp()

    monkeypatch.setattr("httpx.Client", lambda *a, **k: _Client())
    df = equity_data.fetch_tiingo("AAPL", "daily")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert list(df.columns).count("close") == 1
    # adjusted values were chosen, not the raw ones
    assert df["close"].iloc[-1] == pytest.approx(5.75)
    assert df["volume"].iloc[0] == pytest.approx(200)


def test_alpaca_no_creds_returns_none(monkeypatch):
    monkeypatch.setattr("config.settings.alpaca_api_key", "")
    monkeypatch.setattr("config.settings.alpaca_secret", "")
    assert equity_data.fetch_alpaca("AAPL", "daily") is None


def test_finalize_rejects_missing_columns():
    bad = pd.DataFrame({"open": [1.0], "close": [2.0]})  # no high/low/volume
    assert equity_data._finalize(bad) is None


def test_finalize_projects_and_sorts():
    idx = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"], utc=True)
    df = pd.DataFrame(
        {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10,
         "extra": 99},
        index=idx,
    )
    out = equity_data._finalize(df)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out.index.is_monotonic_increasing
    assert out.index.name == "date"


def test_equity_adapter_delegates(monkeypatch):
    from markets.equity import EquityAdapter
    monkeypatch.setattr("markets.equity.fetch_equity_ohlcv", lambda s, t: _sample_df())
    df = EquityAdapter().fetch_ohlcv("AAPL", "daily")
    assert not df.empty
