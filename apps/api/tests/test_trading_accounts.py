"""Tests for the Tier-3 multi-account foundation (migration 013 application layer):
TradingAccount ORM, account-aware executor factory, account-scoped idempotency,
and the worker's house-account threading.
"""

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_api = Path(__file__).parents[1]
_worker = _api.parent / "worker"
sys.path.insert(0, str(_api))
sys.path.insert(0, str(_worker))

from config import settings
from db.models import Order, Position, TradingAccount, _house_account_id
from execution import get_executor, resolve_account_mode
from execution.paper import PaperExecutor
from execution.idempotency import already_submitted


HOUSE = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _Account:
    def __init__(self, broker: str):
        self.broker = broker


# ---------------------------------------------------------------------------
# resolve_account_mode
# ---------------------------------------------------------------------------

def test_none_account_resolves_to_legacy():
    assert resolve_account_mode(None) is None


def test_house_sentinel_resolves_to_legacy():
    assert resolve_account_mode(_Account("house")) is None
    assert resolve_account_mode(_Account("")) is None


def test_real_broker_maps_directly_and_lowercases():
    assert resolve_account_mode(_Account("ALPACA")) == "alpaca"
    assert resolve_account_mode(_Account("paper")) == "paper"


# ---------------------------------------------------------------------------
# get_executor(asset_class, account)
# ---------------------------------------------------------------------------

def test_account_broker_overrides_asset_class_env(monkeypatch):
    """A paper account gets the paper executor even when the env routes the
    asset class to a live venue — accounts pin their own broker."""
    monkeypatch.setattr(settings, "crypto_executor", "coinbase")
    ex = get_executor("crypto", account=_Account("paper"))
    assert isinstance(ex, PaperExecutor)


def test_house_account_uses_legacy_resolution(monkeypatch):
    monkeypatch.setattr(settings, "executor_mode", "paper")
    monkeypatch.setattr(settings, "equity_executor", "paper")
    ex = get_executor("equity", account=_Account("house"))
    assert isinstance(ex, PaperExecutor)


def test_no_account_is_byte_identical_legacy(monkeypatch):
    monkeypatch.setattr(settings, "executor_mode", "paper")
    monkeypatch.setattr(settings, "crypto_executor", "paper")
    assert isinstance(get_executor("crypto"), PaperExecutor)


def test_unknown_account_broker_raises():
    with pytest.raises(ValueError, match="Unknown executor mode"):
        get_executor("equity", account=_Account("bogus"))


# ---------------------------------------------------------------------------
# already_submitted account scoping
# ---------------------------------------------------------------------------

def _session_returning(value):
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    session.execute = AsyncMock(return_value=result)
    return session


def _where_clause(session) -> str:
    stmt = str(session.execute.await_args.args[0])
    # Only the filter matters — the SELECT list always renders every column.
    return stmt.split("WHERE", 1)[1] if "WHERE" in stmt else ""


def test_already_submitted_scoped_to_account():
    sentinel = object()
    session = _session_returning(sentinel)
    got = asyncio.run(already_submitted(session, "equity:AAPL:buy:1700000000", account_id=HOUSE))
    assert got is sentinel
    assert "account_id" in _where_clause(session)


def test_already_submitted_unscoped_stays_global():
    session = _session_returning(None)
    got = asyncio.run(already_submitted(session, "equity:AAPL:buy:1700000000"))
    assert got is None
    assert "account_id" not in _where_clause(session)


# ---------------------------------------------------------------------------
# ORM shape
# ---------------------------------------------------------------------------

def test_house_account_default_matches_settings():
    assert _house_account_id() == uuid.UUID(settings.system_account_id) == HOUSE


def test_trading_account_columns():
    cols = {c.name for c in TradingAccount.__table__.columns}
    assert {"id", "user_id", "broker", "label", "paper",
            "enabled_asset_classes", "status"} <= cols


def test_positions_and_orders_carry_account_id():
    assert "account_id" in {c.name for c in Position.__table__.columns}
    assert "account_id" in {c.name for c in Order.__table__.columns}


def test_order_idempotency_unique_is_composite():
    constraints = {c.name for c in Order.__table__.constraints if c.name}
    assert "uq_orders_account_client_order_id" in constraints
    # The legacy single-column unique on client_order_id must be gone.
    coid = Order.__table__.columns["client_order_id"]
    assert not coid.unique


# ---------------------------------------------------------------------------
# worker house-account threading
# ---------------------------------------------------------------------------

def test_tick_house_account_matches_settings():
    from tick import _HOUSE_ACCOUNT
    assert _HOUSE_ACCOUNT == HOUSE
