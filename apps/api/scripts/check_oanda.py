#!/usr/bin/env python
"""OANDA practice connectivity check — run with YOUR practice token.

Validates the forex path end-to-end against the live OANDA practice API (no orders
placed): (a) the account summary (proves the token + account id), and (b) a few
EUR_USD candles (proves market data). Reuses the real OandaExecutor/OandaAdapter.

Setup:
    pip install oandapyV20            # in apps/api/requirements.txt, may not be in the venv yet
    export OANDA_API_TOKEN=...        # OANDA practice token
    export OANDA_ACCOUNT_ID=101-001-1234567-001
    export OANDA_ENVIRONMENT=practice
    export OANDA_PAPER=true
    PYTHONPATH=. python scripts/check_oanda.py
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("OANDA_ENVIRONMENT", "practice")
os.environ.setdefault("OANDA_PAPER", "true")
os.environ.setdefault("OANDA_ALLOW_LIVE", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # apps/api

from config import settings  # noqa: E402


async def _run() -> int:
    if not settings.oanda_api_token or not settings.oanda_account_id:
        print("[FAIL] set OANDA_API_TOKEN and OANDA_ACCOUNT_ID first")
        return 1

    print("=== OANDA practice connectivity check ===")
    print(f"environment = {settings.oanda_environment}, account = {settings.oanda_account_id}")

    ok = True

    # (a) account summary — validates token + account id
    try:
        from execution.oanda import OandaExecutor
        equity = await OandaExecutor().get_account_equity()
        if equity is None:
            print("[FAIL] account summary returned no equity (check token/account permissions)")
            ok = False
        else:
            print(f"[PASS] account NAV/balance = {equity:.2f}")
    except Exception as exc:
        print(f"[FAIL] account summary error: {exc}")
        ok = False

    # (b) EUR_USD candles — validates market data
    try:
        from markets.oanda import OandaAdapter
        df = OandaAdapter().fetch_ohlcv("EUR_USD", "4h")
        if df is None or df.empty:
            print("[FAIL] no EUR_USD candles returned")
            ok = False
        else:
            print(f"[PASS] {len(df)} EUR_USD H4 candles — latest close {df['close'].iloc[-1]:.5f} "
                  f"@ {df.index[-1].isoformat()}")
    except Exception as exc:
        print(f"[FAIL] candle fetch error: {exc}")
        ok = False

    print("=== OANDA connectivity OK ===" if ok else "=== OANDA check FAILED ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
