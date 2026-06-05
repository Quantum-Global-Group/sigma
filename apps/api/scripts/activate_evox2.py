#!/usr/bin/env python
"""Activate EvoX2 services (MT5 bridge + Moomoo OpenD) from the DGX.

Verifies both services are reachable, then updates apps/api/.env to:
  - FOREX_EXECUTOR=mt5
  - FOREX_MT5_SYMBOLS=XAUUSD,EURUSD,GBPUSD,AUDUSD,USDJPY,USDCAD
  - OPTION_EXECUTOR=moomoo

Run ONLY after completing docs/EVOX2_SETUP.md on the Windows machine.

Usage:
    cd apps/api
    PYTHONPATH=. .venv/bin/python scripts/activate_evox2.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

# Full symbol list to route through MT5 once bridge is verified
MT5_SYMBOLS_FULL = "XAUUSD,EURUSD,GBPUSD,AUDUSD,USDJPY,USDCAD"


def _header(msg: str) -> None:
    print(f"\n{'─'*50}\n{msg}\n{'─'*50}")


async def _check_mt5() -> tuple[bool, str]:
    """Returns (ok, detail)."""
    if not settings.mt5_bridge_url:
        return False, "MT5_BRIDGE_URL is not set"
    import httpx
    headers = {"X-MT5-Bridge-Secret": settings.mt5_bridge_secret} if settings.mt5_bridge_secret else {}
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(f"{settings.mt5_bridge_url.rstrip('/')}/health", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            connected = data.get("connected", False)
            equity = data.get("equity") or data.get("balance")
            if not connected:
                return False, f"bridge up but MT5 not connected: {data}"
            detail = f"MT5 connected — equity={float(equity):.2f}" if equity else "MT5 connected"
            return True, detail
    except Exception as exc:
        return False, str(exc)


async def _check_opend() -> tuple[bool, str]:
    """TCP reachability only — SDK check happens via check_moomoo_opend.py."""
    from markets.opend_health import check_opend
    ok, detail = await check_opend(settings.moomoo_host, settings.moomoo_port)
    return ok, detail


def _update_env(dry_run: bool) -> None:
    """Flip FOREX_EXECUTOR, OPTION_EXECUTOR, and FOREX_MT5_SYMBOLS in .env."""
    if not os.path.exists(ENV_PATH):
        print(f"[WARN] .env not found at {ENV_PATH} — skipping update")
        return

    with open(ENV_PATH) as f:
        content = f.read()

    changes: list[str] = []

    def _set(key: str, value: str) -> str:
        nonlocal content, changes
        pattern = rf"^({re.escape(key)}=).*$"
        new_line = f"{key}={value}"
        if re.search(pattern, content, re.MULTILINE):
            old_match = re.search(pattern, content, re.MULTILINE)
            if old_match and old_match.group(0) != new_line:
                changes.append(f"  {old_match.group(0)}  →  {new_line}")
                content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
        else:
            changes.append(f"  (new) {new_line}")
            content += f"\n{new_line}\n"
        return content

    _set("FOREX_EXECUTOR", "mt5")
    _set("FOREX_MT5_SYMBOLS", MT5_SYMBOLS_FULL)
    _set("OPTION_EXECUTOR", "moomoo")

    if not changes:
        print("  .env already up to date — nothing to change")
        return

    print("  Changes to apply:")
    for c in changes:
        print(c)

    if dry_run:
        print("  [dry-run] .env not written")
        return

    with open(ENV_PATH, "w") as f:
        f.write(content)
    print(f"  .env updated at {ENV_PATH}")


async def main(dry_run: bool) -> int:
    _header("1. MT5 bridge  (EvoX2 :8787)")
    mt5_ok, mt5_detail = await _check_mt5()
    print(f"{'[PASS]' if mt5_ok else '[FAIL]'} {mt5_detail}")
    if not mt5_ok:
        print(
            "\n  Bridge not reachable. Complete docs/EVOX2_SETUP.md §1 on EvoX2, then re-run.\n"
            "  Quick test from EvoX2 PowerShell:\n"
            f"    curl.exe -H \"X-MT5-Bridge-Secret: {settings.mt5_bridge_secret}\" "
            f"{settings.mt5_bridge_url}/health"
        )

    _header("2. Moomoo OpenD  (EvoX2 :11111)")
    opend_ok, opend_detail = await _check_opend()
    print(f"{'[PASS]' if opend_ok else '[FAIL]'} {opend_detail}")
    if not opend_ok:
        print(
            "\n  OpenD not reachable. Complete docs/EVOX2_SETUP.md §2 on EvoX2:\n"
            "  1. Launch Moomoo OpenD app\n"
            "  2. Log in with paper/simulate account\n"
            "  3. Confirm port 11111 is open (firewall rule in §3)"
        )

    _header("3. .env activation")
    if mt5_ok and opend_ok:
        _update_env(dry_run)
        print("\n  Both services verified.")
        if not dry_run:
            print("  Next: run scripts/check_mt5_bridge.py --symbol XAUUSD")
            print("        run scripts/check_moomoo_opend.py")
            print("  Then restart the worker: make restart-worker")
    else:
        services = []
        if not mt5_ok:
            services.append("MT5 bridge (§1)")
        if not opend_ok:
            services.append("Moomoo OpenD (§2)")
        print(f"  Skipping .env update — {' and '.join(services)} not ready yet.")

    return 0 if (mt5_ok and opend_ok) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="check only — do not modify .env")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))
