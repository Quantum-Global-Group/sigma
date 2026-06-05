"""Candle persistence tests (PR-B) — pure helper + statement-level upsert.

No live DB: rows_from_df is pure, and upsert_candles is exercised against an
AsyncMock session so we verify it builds and dispatches a statement without a
real Postgres connection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pandas as pd
import pytest


def _ohlcv(n=30, tz="UTC"):
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz=tz)
    df = pd.DataFrame({
        "open": range(100, 100 + n),
        "high": range(101, 101 + n),
        "low": range(99, 99 + n),
        "close": range(100, 100 + n),
        "volume": [1_000_000] * n,
    }, index=idx)
    df.index.name = "date"
    return df


# ---------------------------------------------------------------------------
# rows_from_df (pure)
# ---------------------------------------------------------------------------

def test_rows_from_df_takes_tail_only():
    from db.candle_store import rows_from_df
    rows = rows_from_df("equity", "AAPL", "daily", _ohlcv(50), "test", tail=10)
    assert len(rows) == 10
    # Tail = most recent rows.
    assert rows[-1]["close"] == float(149)        # 100 + 49
    assert rows[0]["asset_class"] == "equity"
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["timeframe"] == "daily"
    assert rows[0]["source"] == "test"


def test_rows_from_df_ts_is_utc_aware():
    from db.candle_store import rows_from_df
    rows = rows_from_df("forex", "EUR_USD", "4h", _ohlcv(5), "oanda", tail=20)
    assert len(rows) == 5
    for r in rows:
        assert isinstance(r["ts"], datetime)
        assert r["ts"].tzinfo is not None
        assert r["ts"].utcoffset() == timezone.utc.utcoffset(None)


def test_rows_from_df_localizes_naive_index():
    from db.candle_store import rows_from_df
    df = _ohlcv(5, tz=None)                         # tz-naive index
    rows = rows_from_df("crypto", "BTC-USD", "5m", df, "coinbase", tail=20)
    assert len(rows) == 5
    assert all(r["ts"].tzinfo is not None for r in rows)


def test_rows_from_df_empty_returns_empty():
    from db.candle_store import rows_from_df
    assert rows_from_df("equity", "AAPL", "daily", pd.DataFrame(), "t", tail=10) == []


def test_rows_from_df_missing_columns_returns_empty():
    from db.candle_store import rows_from_df
    bad = pd.DataFrame({"open": [1], "close": [1]}, index=pd.date_range("2026-01-01", periods=1))
    assert rows_from_df("equity", "AAPL", "daily", bad, "t", tail=10) == []


def test_rows_from_df_values_are_floats():
    from db.candle_store import rows_from_df
    rows = rows_from_df("equity", "AAPL", "daily", _ohlcv(3), "t", tail=10)
    r = rows[0]
    for k in ("open", "high", "low", "close", "volume"):
        assert isinstance(r[k], float)


# ---------------------------------------------------------------------------
# upsert_candles (statement-level, mock session)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_candles_executes_and_counts():
    from db.candle_store import upsert_candles
    session = AsyncMock()
    written = await upsert_candles(
        session, asset_class="forex", symbol="EUR_USD",
        timeframe="4h", df=_ohlcv(25), tail=20,
    )
    assert written == 20
    session.execute.assert_awaited_once()
    # The dispatched object is a postgresql Insert with an ON CONFLICT clause.
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(dialect=__import__("sqlalchemy.dialects.postgresql",
                                                   fromlist=["dialect"]).dialect()))
    assert "ON CONFLICT" in compiled.upper()
    assert "candles" in compiled.lower()


@pytest.mark.asyncio
async def test_upsert_candles_empty_is_noop():
    from db.candle_store import upsert_candles
    session = AsyncMock()
    written = await upsert_candles(
        session, asset_class="equity", symbol="AAPL",
        timeframe="daily", df=pd.DataFrame(), tail=20,
    )
    assert written == 0
    session.execute.assert_not_awaited()
