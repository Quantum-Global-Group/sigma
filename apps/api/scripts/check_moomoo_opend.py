#!/usr/bin/env python
"""Verify Moomoo OpenD gateway + paper account connectivity.

OpenD must be running and logged in before options trading works. This script
checks TCP reachability, quote API, and simulate-account balance via the SDK.

Usage:
    cd apps/api
    PYTHONPATH=. python scripts/check_moomoo_opend.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from markets.opend_health import check_opend


def _header(msg: str) -> None:
    print(f"\n=== {msg} ===")


async def main() -> int:
    host = settings.moomoo_host
    port = settings.moomoo_port
    print(f"OpenD target: {host}:{port}")
    print(f"Paper mode:   MOOMOO_PAPER={settings.moomoo_paper}")
    print(f"Market/firm:  {settings.moomoo_trd_market} / {settings.moomoo_security_firm}")

    _header("1. TCP reachability")
    ok, detail = await check_opend(host, port)
    print(f"{'OK' if ok else 'FAIL'}: {detail}")
    if not ok:
        print(
            "\nOpenD is not listening. Start the Moomoo OpenD app, log into your "
            "paper/simulate account, and confirm port 11111 is open.\n"
            "Docs: docs/DEPLOY_OPTIONS.md"
        )
        return 1

    from moomoo import OpenQuoteContext, OpenSecTradeContext, SecurityFirm, TrdEnv, TrdMarket

    firm = getattr(SecurityFirm, settings.moomoo_security_firm, SecurityFirm.FUTUINC)
    market = getattr(TrdMarket, settings.moomoo_trd_market, TrdMarket.US)

    _header("2. Quote API (OpenQuoteContext)")
    quote = OpenQuoteContext(host=host, port=port)
    try:
        ret, data = quote.get_global_state()
        if ret == 0:
            print("OK: global_state")
            if data is not None and len(data) > 0:
                row = data.iloc[0]
                for key in ("market_sz", "market_us", "market_hk", "server_ver"):
                    if key in data.columns:
                        print(f"  {key}: {row[key]}")
        else:
            print(f"FAIL: get_global_state ret={ret} data={data}")
            return 1
    finally:
        quote.close()

    _header("3. Paper account (OpenSecTradeContext / SIMULATE)")
    trade = OpenSecTradeContext(
        host=host, port=port, filter_trdmarket=market, security_firm=firm,
    )
    try:
        ret, data = trade.accinfo_query(trd_env=TrdEnv.SIMULATE)
        if ret != 0 or data is None or len(data) == 0:
            print(f"FAIL: accinfo_query SIMULATE ret={ret} data={data}")
            print(
                "Ensure you logged into OpenD with a paper/simulate trading account enabled."
            )
            return 1
        row = data.iloc[0]
        print("OK: simulate account")
        for key in ("total_assets", "cash", "market_val", "unrealized_pl"):
            if key in data.columns:
                print(f"  {key}: {row[key]}")
    finally:
        trade.close()

    _header("4. Sample option chain (AAPL expiries)")
    quote = OpenQuoteContext(host=host, port=port)
    try:
        from markets.options import MoomooOptionData

        od = MoomooOptionData(quote_ctx=quote)
        expiries = od.list_expiries("AAPL")
        print(f"OK: {len(expiries)} expiries for AAPL")
        if expiries:
            print(f"  nearest: {expiries[0]}")
    except Exception as exc:
        print(f"WARN: option chain probe failed: {exc}")
    finally:
        quote.close()

    print("\nAll checks passed — ready for OPTION_EXECUTOR=moomoo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
