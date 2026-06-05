"""Execution control — current executor mode + manual `/run_cycle` trigger.

`/run_cycle` runs a single tick on demand for a given asset class. Useful
for ops/debugging without waiting for the worker's next scheduled cycle.

This router rejects non-internal callers — only the worker (or an operator
with the INTERNAL_SECRET) should be able to trigger live execution paths."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from cache.worker_status import read_pauses, set_pause
from config import settings
from middleware.auth import AuthContext, require_auth

router = APIRouter(prefix="/execution", tags=["execution"])
AuthDep = Annotated[AuthContext, Depends(require_auth)]

_ASSET_CLASS_PATTERN = "^(equity|crypto|option|forex)$"


class ExecutionStatus(BaseModel):
    executor_mode: str
    coinbase_sandbox: bool
    worker_asset_classes_default_crypto_seconds: int
    worker_asset_classes_default_equity_seconds: int
    worker_asset_classes_default_option_seconds: int
    worker_asset_classes_default_forex_seconds: int
    paused: list[str] = []


class RunCycleRequest(BaseModel):
    asset_class: str = Field(..., pattern=_ASSET_CLASS_PATTERN)


class RunCycleResponse(BaseModel):
    asset_class: str
    triggered: bool


class PauseRequest(BaseModel):
    asset_class: str = Field(..., pattern=_ASSET_CLASS_PATTERN)
    reason: str | None = None


class PauseResponse(BaseModel):
    asset_class: str
    paused: bool


@router.get("/status", response_model=ExecutionStatus)
async def execution_status(auth: AuthDep):
    paused = sorted((await read_pauses()).keys())
    return ExecutionStatus(
        executor_mode=settings.executor_mode,
        coinbase_sandbox=settings.coinbase_sandbox,
        worker_asset_classes_default_crypto_seconds=settings.worker_tick_seconds_crypto,
        worker_asset_classes_default_equity_seconds=settings.worker_tick_seconds_equity,
        worker_asset_classes_default_option_seconds=settings.worker_tick_seconds_option,
        worker_asset_classes_default_forex_seconds=settings.worker_tick_seconds_forex,
        paused=paused,
    )


@router.post("/run_cycle", response_model=RunCycleResponse)
async def run_cycle(body: RunCycleRequest, auth: AuthDep):
    if not auth.internal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="run_cycle requires X-Internal-Secret",
        )

    if body.asset_class == "option":
        # Options use the chain-based loop, not the OHLCV tick_once.
        from worker.options_tick import options_tick_once
        await options_tick_once()
    else:
        # Lazy import — pulls in worker.tick (which transitively imports the
        # whole signal stack). Keeping it lazy avoids paying that cost on a
        # stock api startup that doesn't run cycles.
        from worker.tick import tick_once
        await tick_once(body.asset_class)

    return RunCycleResponse(asset_class=body.asset_class, triggered=True)


@router.post("/pause", response_model=PauseResponse)
async def pause(body: PauseRequest, auth: AuthDep):
    """Halt one asset class's worker loop without redeploying. Internal-only."""
    _require_internal(auth)
    await set_pause(body.asset_class, True, reason=body.reason)
    return PauseResponse(asset_class=body.asset_class, paused=True)


@router.post("/resume", response_model=PauseResponse)
async def resume(body: PauseRequest, auth: AuthDep):
    """Resume a paused asset class. Internal-only."""
    _require_internal(auth)
    await set_pause(body.asset_class, False)
    return PauseResponse(asset_class=body.asset_class, paused=False)


class ApproveLiveRequest(BaseModel):
    reason: str | None = None


@router.get("/preflight")
async def preflight(auth: AuthDep):
    """Go-live readiness report (guardrail checks). Internal-only. Read-only —
    enables nothing; just reports whether the safety rails are in place."""
    _require_internal(auth)
    from execution.live_guard import preflight as _preflight
    return await _preflight()


@router.post("/approve_live")
async def approve_live(body: ApproveLiveRequest, auth: AuthDep):
    """Approve real-money trading for this session (the first-live-order gate).
    Internal-only. Live executors still require their own *_allow_live flags; this
    is the human go-ahead on top. Flipping flags + funding remain manual."""
    _require_internal(auth)
    from execution.live_guard import approve_live as _approve
    await _approve(reason=body.reason)
    return {"live_approved": True, "reason": body.reason}


@router.post("/revoke_live")
async def revoke_live(auth: AuthDep):
    """Revoke live approval immediately (back to paper-only). Internal-only."""
    _require_internal(auth)
    from execution.live_guard import revoke_live as _revoke
    await _revoke()
    return {"live_approved": False}


def _require_internal(auth: AuthContext) -> None:
    if not auth.internal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="pause/resume requires X-Internal-Secret",
        )
