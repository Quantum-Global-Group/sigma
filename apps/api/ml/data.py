"""Equity OHLCV fetch — thin shim over the equity MarketAdapter.

Historically this called yfinance directly. It now delegates to the unified,
multi-source equity adapter (Tiingo → Alpaca → yfinance) so that *training*
(train_models.py, backfill_signals.py, quantum/portfolio_optimizer.py) and
*serving* (ml/pipeline.py, the worker) pull from the exact same bars.

Kept as a function for back-compat with existing imports and test patches."""

from __future__ import annotations

import pandas as pd

from markets import get_market_adapter


def fetch_ohlcv(ticker: str, timeframe: str = "daily") -> pd.DataFrame:
    return get_market_adapter("equity").fetch_ohlcv(ticker, timeframe)
