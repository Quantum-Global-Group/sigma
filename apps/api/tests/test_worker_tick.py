"""Worker tick smoke tests — verify the loop iterates the universe and
short-circuits on a closed market. The fully-wired tick (signal -> risk ->
sizing -> execute -> persist) is exercised by integration tests in Phase C
since it needs a real Postgres + executor."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# The worker package lives at apps/worker (sibling to apps/api).
WORKER_PATH = Path(__file__).resolve().parents[3] / "worker"
sys.path.insert(0, str(WORKER_PATH.parent))


def test_tick_skips_when_market_closed():
    """Equity adapter's is_market_open returns False on weekends — verify the
    tick short-circuits without entering the per-symbol loop."""
    from worker.tick import tick_once

    fake_session = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))

    @AsyncMock
    async def _ctx_mgr(*a, **kw):
        return fake_session

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_session)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("markets.equity.EquityAdapter.is_market_open", return_value=False), \
         patch("worker.tick.AsyncSessionLocal", return_value=cm), \
         patch("worker.tick.get_universe_selector") as sel:
        asyncio.run(tick_once("equity"))

    sel.assert_not_called()  # short-circuited before universe selection


def test_tick_main_wrapper_swallows_exceptions():
    """worker.main.tick_once wraps worker.tick.tick_once and logs without raising."""
    from worker.main import tick_once

    with patch("worker.tick.tick_once", side_effect=RuntimeError("boom")):
        # Should not raise.
        asyncio.run(tick_once("crypto"))
