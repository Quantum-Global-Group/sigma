"""Order idempotency helper tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from execution.idempotency import already_submitted


def _session_returning(value):
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    session.execute = AsyncMock(return_value=result)
    return session


def test_already_submitted_returns_existing_order():
    sentinel = object()
    session = _session_returning(sentinel)
    got = asyncio.run(already_submitted(session, "equity:AAPL:buy:1700000000"))
    assert got is sentinel
    session.execute.assert_awaited_once()


def test_already_submitted_returns_none_when_absent():
    session = _session_returning(None)
    got = asyncio.run(already_submitted(session, "equity:AAPL:buy:1700000000"))
    assert got is None


def test_already_submitted_short_circuits_on_empty_id():
    session = _session_returning(None)
    got = asyncio.run(already_submitted(session, ""))
    assert got is None
    # No query issued for an empty key.
    session.execute.assert_not_called()
