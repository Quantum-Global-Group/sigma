"""MT5 bridge reachability probe."""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx


async def check_mt5_bridge(
    base_url: str,
    *,
    secret: str = "",
    timeout: float = 3.0,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[bool, str]:
    """Return (reachable, detail). Never raises; probe failures are the signal."""
    if not base_url:
        return False, "MT5_BRIDGE_URL not set"
    headers = {"X-MT5-Bridge-Secret": secret} if secret else {}
    own_client = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await c.get(f"{base_url.rstrip('/')}/health", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("connected") is False:
            return False, str(data)
        server = data.get("server") or "unknown server"
        account = data.get("login") or data.get("account") or "unknown account"
        return True, f"reachable ({server}, account={account})"
    except asyncio.TimeoutError:
        return False, f"timeout connecting to {base_url}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        if own_client:
            await c.aclose()
