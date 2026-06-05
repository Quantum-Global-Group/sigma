#!/usr/bin/env python
"""Alpaca paper account connectivity check.

Validates the equity path end-to-end: (a) account summary (proves API key +
paper flag), and (b) a few AAPL daily bars (proves market data feed).
Reuses the real AlpacaExecutor / EquityDataAdapter.

Usage:
    cd apps/api
    PYTHONPATH=. python scripts/check_alpaca.py
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("ALPACA_PAPER", "true")
os.environ.setdefault("ALPACA_ALLOW_LIVE", "false")
os.environ.setdefault("EQUITY_EXECUTOR", "alpaca")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402


async def _run() -> int:
    if not settings.alpaca_api_key or not settings.alpaca_secret:
        print("[FAIL] set ALPACA_API_KEY and ALPACA_SECRET first")
        return 1

    print("=== Alpaca paper connectivity check ===")
    print(f"paper={settings.alpaca_paper}  feed={settings.alpaca_data_feed}")

    ok = True

    # (a) account summary — validates key + paper flag
    try:
        from execution.alpaca import AlpacaExecutor
        equity = await AlpacaExecutor().get_account_equity()
        if equity is None:
            print("[FAIL] account equity returned None (check API key + ALPACA_PAPER)")
            ok = False
        else:
            print(f"[PASS] account equity = ${equity:,.2f}")
    except Exception as exc:
        print(f"[FAIL] account summary error: {exc}")
        ok = False

    # (b) AAPL daily bars — validates market data
    try:
        from markets.equity import EquityAdapter
        df = EquityAdapter().fetch_ohlcv("AAPL", "daily")
        if df is None or df.empty:
            print("[FAIL] no AAPL daily bars returned")
            ok = False
        else:
            print(f"[PASS] {len(df)} AAPL daily bars — "
                  f"latest close ${df['close'].iloc[-1]:.2f} @ {df.index[-1].date()}")
    except Exception as exc:
        print(f"[FAIL] market data error: {exc}")
        ok = False

    print("=== Alpaca OK ===" if ok else "=== Alpaca check FAILED ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
