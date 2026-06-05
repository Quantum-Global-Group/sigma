"""OpenD gateway reachability check (Moomoo options supervision).

The local/VPS options worker depends on a Moomoo OpenD daemon listening on a
local TCP port. This is a lightweight reachability probe (TCP connect) the
worker runs before each options tick — separate from the SDK so a hung gateway
surfaces as "unreachable" rather than a long SDK timeout. The connector is
injectable so tests need no real socket.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# (host, port, timeout) -> opens a connection; raises on failure.
Connector = Callable[[str, int, float], Awaitable[None]]


async def _tcp_connect(host: str, port: int, timeout: float) -> None:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def check_opend(
    host: str, port: int, *, timeout: float = 3.0, connector: Optional[Connector] = None,
) -> tuple[bool, str]:
    """Return (reachable, detail). Never raises — a probe failure is the signal."""
    connect = connector or _tcp_connect
    try:
        await connect(host, port, timeout)
        return True, f"reachable at {host}:{port}"
    except asyncio.TimeoutError:
        return False, f"timeout connecting to {host}:{port}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
