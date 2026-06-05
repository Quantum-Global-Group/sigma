"""Equity market-data providers — Alpaca, Tiingo.

Each `fetch_*` returns a normalized OHLCV DataFrame (lowercase
`open/high/low/close/volume`, `date` index) or `None` when the provider has no
credentials, returns nothing, or errors. `EquityAdapter.fetch_ohlcv` tries them
in `settings.equity_data_providers` order and takes the first non-empty result.

Alpaca is the primary source (reuses execution creds); Tiingo is the fallback.
Crypto has its own reliable Coinbase path and does not use this module."""

from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd

from config import settings
from .base import MarketAdapter  # noqa: F401  (kept for type/context locality)

logger = logging.getLogger(__name__)

# Lookback window per timeframe (how far back to request).
_LOOKBACK: dict[str, timedelta] = {
    "daily": timedelta(days=180),
    "1d": timedelta(days=180),
    "hourly": timedelta(days=14),
    "1h": timedelta(days=14),
    "4h": timedelta(days=60),
    "5m": timedelta(days=5),
    "1m": timedelta(hours=8),
}

_REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def _finalize(df: pd.DataFrame) -> pd.DataFrame | None:
    """Lowercase, validate, sort, and project to the standard OHLCV contract."""
    if df is None or df.empty:
        return None
    df = df.rename(columns=str.lower)
    if not set(_REQUIRED_COLS).issubset(df.columns):
        return None
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    out = df[_REQUIRED_COLS].astype(float)
    out.index.name = "date"
    if out.empty:
        return None
    return out


# ---------------------------------------------------------------------------
# Tiingo — REST via httpx
# ---------------------------------------------------------------------------

def fetch_tiingo(
    symbol: str,
    timeframe: str,
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame | None:
    if not settings.tiingo_api_key:
        return None
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return None

    if start:
        start_str = start
    else:
        lookback = _LOOKBACK.get(timeframe, timedelta(days=180))
        start_str = (pd.Timestamp.now("UTC") - lookback).strftime("%Y-%m-%d")
    headers = {"Content-Type": "application/json",
               "Authorization": f"Token {settings.tiingo_api_key}"}

    daily = timeframe in ("daily", "1d")
    if daily:
        url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
        params: dict[str, str] = {"startDate": start_str}
    else:
        freq = {"5m": "5min", "1m": "1min", "hourly": "1hour", "1h": "1hour", "4h": "4hour"}.get(timeframe, "5min")
        url = f"https://api.tiingo.com/iex/{symbol}/prices"
        params = {"startDate": start_str, "resampleFreq": freq}
    if end:
        params["endDate"] = end

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, params=params, headers=headers)
            r.raise_for_status()
            rows = r.json()
    except Exception:
        logger.warning("[tiingo] fetch failed for %s", symbol, exc_info=True)
        return None
    if not isinstance(rows, list) or not rows:
        return None

    df = pd.DataFrame(rows)
    if "date" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date")
    # Tiingo's daily endpoint returns BOTH raw (open/high/low/close/volume) and
    # split/dividend-adjusted (adjOpen/…/adjVolume) columns. Prefer adjusted and
    # select *only* those (renaming positionally) to avoid duplicate columns.
    cols = {c.lower(): c for c in df.columns}
    adj = ("adjopen", "adjhigh", "adjlow", "adjclose", "adjvolume")
    if daily and all(a in cols for a in adj):
        df = df[[cols[a] for a in adj]]
        df.columns = ["open", "high", "low", "close", "volume"]
    return _finalize(df)


# ---------------------------------------------------------------------------
# Alpaca — alpaca-py StockHistoricalDataClient (reuses execution creds)
# ---------------------------------------------------------------------------

def fetch_alpaca(
    symbol: str,
    timeframe: str,
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame | None:
    if not (settings.alpaca_api_key and settings.alpaca_secret):
        return None
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    except ImportError:  # pragma: no cover
        return None

    tf = {
        "daily": TimeFrame.Day, "1d": TimeFrame.Day,
        "hourly": TimeFrame.Hour, "1h": TimeFrame.Hour,
        "5m": TimeFrame(5, TimeFrameUnit.Minute),
        "1m": TimeFrame(1, TimeFrameUnit.Minute),
        "4h": TimeFrame(4, TimeFrameUnit.Hour),
    }.get(timeframe, TimeFrame.Day)

    if start:
        start_ts = pd.Timestamp(start, tz="UTC")
    else:
        lookback = _LOOKBACK.get(timeframe, timedelta(days=180))
        start_ts = pd.Timestamp.now("UTC") - lookback
    end_ts = pd.Timestamp(end, tz="UTC") if end else None

    try:
        client = StockHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_secret)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start_ts.to_pydatetime(),
            end=end_ts.to_pydatetime() if end_ts is not None else None,
            feed=settings.alpaca_data_feed,
        )
        bars = client.get_stock_bars(req)
    except Exception:
        logger.warning("[alpaca-data] fetch failed for %s", symbol, exc_info=True)
        return None

    df = getattr(bars, "df", None)
    if df is None or df.empty:
        return None
    # bars.df is MultiIndex (symbol, timestamp) — drop the symbol level.
    if isinstance(df.index, pd.MultiIndex):
        try:
            df = df.xs(symbol, level=0)
        except (KeyError, TypeError):
            df = df.droplevel(0)
    return _finalize(df)


_PROVIDERS = {
    "tiingo": fetch_tiingo,
    "alpaca": fetch_alpaca,
}


def fetch_equity_ohlcv(
    symbol: str,
    timeframe: str,
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Try providers in settings.equity_data_providers order; first non-empty wins."""
    names = [n.strip().lower() for n in settings.equity_data_providers.split(",") if n.strip()]
    if not names:
        names = ["tiingo"]
    tried: list[str] = []
    for name in names:
        fn = _PROVIDERS.get(name)
        if fn is None:
            logger.warning("Unknown equity data provider %r — skipping", name)
            continue
        tried.append(name)
        df = fn(symbol, timeframe, start=start, end=end)
        if df is not None and not df.empty:
            logger.info("[equity-data] %s served %s (%d rows)", name, symbol, len(df))
            return df
    raise ValueError(f"No equity data for {symbol!r} from providers {tried}")
