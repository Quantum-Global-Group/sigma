#!/usr/bin/env python
"""MT5 bridge connectivity check.

Run on DGX after EvoX2 has MT5 + the bridge running:
    MT5_BRIDGE_URL=http://192.168.x.x:8787 MT5_BRIDGE_SECRET=... \
      PYTHONPATH=. python scripts/check_mt5_bridge.py --symbol EUR_USD
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="EUR_USD")
    parser.add_argument("--timeframe", default="4h")
    args = parser.parse_args()

    if not settings.mt5_bridge_url:
        print("[FAIL] set MT5_BRIDGE_URL first")
        return 1

    ok = True
    print("=== MT5 bridge connectivity check ===")
    print(f"url = {settings.mt5_bridge_url}")

    try:
        from markets.mt5_bridge import Mt5BridgeAdapter
        from execution.mt5_bridge import Mt5BridgeExecutor

        equity = __import__("asyncio").run(Mt5BridgeExecutor().get_account_equity())
        if equity is None:
            print("[FAIL] account endpoint returned no equity")
            ok = False
        else:
            print(f"[PASS] account equity = {equity:.2f}")

        df = Mt5BridgeAdapter().fetch_ohlcv(args.symbol, args.timeframe)
        if df.empty:
            print("[FAIL] no candles returned")
            ok = False
        else:
            print(f"[PASS] {len(df)} {args.symbol} {args.timeframe} candles — "
                  f"latest close {df['close'].iloc[-1]:.5f} @ {df.index[-1].isoformat()}")
    except Exception as exc:
        print(f"[FAIL] bridge check error: {exc}")
        ok = False

    print("=== MT5 bridge OK ===" if ok else "=== MT5 bridge check FAILED ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
