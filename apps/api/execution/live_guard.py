"""First-live-order approval gate — a safety layer ABOVE the broker allow-live flags.

Each live executor already refuses to construct unless its `*_allow_live` flag is
set. This adds a second, runtime gate: even with allow-live on, no *real-money*
order places until a human explicitly approves (POST /execution/approve_live).
Paper orders are never gated.

Fail-safe by design: `live_approved()` returns **False** on any Redis error, so a
cache outage blocks live trading rather than silently allowing it. The approval is
short-lived (re-approve each session) and revocable.

NOTHING here enables live trading on its own — it only *blocks* until approved.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from cache.redis import cache_get, cache_set, get_redis
from config import settings

logger = logging.getLogger(__name__)

LIVE_APPROVAL_KEY = "worker:live_approved"
_APPROVAL_TTL = 24 * 3600   # re-approve daily — approval is not permanent

# Which per-venue paper flag governs each asset class. When the flag is True the
# venue is in paper/sandbox mode and orders are never "live".
_PAPER_FLAG = {
    "equity": lambda: settings.alpaca_paper,
    "option": lambda: settings.moomoo_paper,
    "forex": lambda: settings.oanda_paper,
    "forex_mt5": lambda: settings.mt5_paper,
    "crypto": lambda: settings.coinbase_sandbox,
}


def is_live_order(asset_class: str, executor) -> bool:
    """True only if this order would hit a real-money venue (non-paper executor
    AND the venue's paper flag is off)."""
    if getattr(executor, "name", "paper") == "paper":
        return False
    key = "forex_mt5" if asset_class == "forex" and getattr(executor, "name", "") == "mt5_bridge" else asset_class
    is_paper = _PAPER_FLAG.get(key, lambda: True)()
    return not is_paper


async def live_approved() -> bool:
    """Whether live trading has been approved this session. Fail-safe: False on
    any error (a cache outage must not silently permit real-money orders)."""
    try:
        return bool(await cache_get(LIVE_APPROVAL_KEY))
    except Exception:
        logger.warning("live_approved check failed — treating as NOT approved", exc_info=True)
        return False


async def approve_live(reason: Optional[str] = None, by: str = "human") -> None:
    """Approve live trading for the session (internal-gated endpoint calls this)."""
    payload = {"approved": True, "by": by, "reason": reason,
               "ts": datetime.now(timezone.utc).isoformat()}
    await cache_set(LIVE_APPROVAL_KEY, payload, ttl=_APPROVAL_TTL)
    logger.warning("LIVE TRADING APPROVED by %s (%s)", by, reason)


async def revoke_live() -> None:
    """Revoke live approval immediately (back to paper-only behavior)."""
    try:
        await get_redis().delete(LIVE_APPROVAL_KEY)
        logger.warning("live trading approval revoked")
    except Exception:
        logger.warning("revoke_live failed", exc_info=True)


async def block_reason(asset_class: str, executor) -> Optional[str]:
    """Return a reason to BLOCK this order, or None to allow it.

    Paper orders are always allowed; live orders are blocked until approved."""
    if not is_live_order(asset_class, executor):
        return None
    if await live_approved():
        return None
    return ("live order blocked — live trading not approved this session "
            "(POST /execution/approve_live with the internal secret)")


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"check": name, "passed": passed, "detail": detail}


async def preflight() -> dict:
    """Go-live readiness report — guardrail checks the runbook references. Does NOT
    enable anything; it only reports whether the safety rails are in place.

    `ready` requires the *critical* rails (order caps + an armed kill switch).
    Live approval itself is reported but expected to be granted at go-live time."""
    checks: list[dict] = []

    caps_ok = (
        settings.per_trade_notional_cap_usd > 0
        or settings.alpaca_max_order_notional > 0
        or settings.option_max_contracts > 0
    )
    checks.append(_check("order_caps_configured", caps_ok,
                         "at least one notional/contract cap is set" if caps_ok
                         else "no order caps set — configure a per-trade cap before live"))

    try:
        from risk.kill_switch import KillSwitch
        KillSwitch()
        checks.append(_check("kill_switch_available", True, "kill switch importable + armable"))
    except Exception as exc:
        checks.append(_check("kill_switch_available", False, f"kill switch unavailable: {exc}"))

    try:
        from ml.models.registry import resolve
        has_model = resolve("equity") is not None
        checks.append(_check("model_available", has_model,
                             "a trained model resolves" if has_model
                             else "no trained model — running on heuristic/technical signals"))
    except Exception as exc:
        checks.append(_check("model_available", False, f"registry error: {exc}"))

    approved = await live_approved()
    checks.append(_check("live_approved", approved,
                         "live trading approved for this session" if approved
                         else "not approved — POST /execution/approve_live to enable live orders"))

    venues = {
        "equity": ("alpaca", settings.alpaca_paper, settings.alpaca_allow_live),
        "option": ("moomoo", settings.moomoo_paper, settings.moomoo_allow_live),
        "forex": ("oanda", settings.oanda_paper, settings.oanda_allow_live),
        "forex_mt5": ("mt5_bridge", settings.mt5_paper, settings.mt5_allow_live),
    }
    modes = {ac: ("LIVE" if (not paper and allow) else "paper")
             for ac, (_v, paper, allow) in venues.items()}
    checks.append(_check("venue_modes", True, "; ".join(f"{ac}={m}" for ac, m in modes.items())))

    critical = ("order_caps_configured", "kill_switch_available")
    ready = all(c["passed"] for c in checks if c["check"] in critical)
    return {"ready": ready, "checks": checks, "venue_modes": modes}
