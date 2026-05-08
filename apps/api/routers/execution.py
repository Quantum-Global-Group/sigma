"""Execution control — current executor mode + manual `/run_cycle` trigger.

`/run_cycle` runs a single tick on demand for a given asset class. Useful
for ops/debugging without waiting for the worker's next scheduled cycle.

This router rejects non-internal callers — only the worker (or an operator
with the INTERNAL_SECRET) should be able to trigger live execution paths."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from config import settings
from middleware.auth import AuthContext, require_auth

router = APIRouter(prefix="/execution", tags=["execution"])
AuthDep = Annotated[AuthContext, Depends(require_auth)]


class ExecutionStatus(BaseModel):
    executor_mode: str
    coinbase_sandbox: bool
    worker_asset_classes_default_crypto_seconds: int
    worker_asset_classes_default_equity_seconds: int


class RunCycleRequest(BaseModel):
    asset_class: str = Field(..., pattern="^(equity|crypto)$")


class RunCycleResponse(BaseModel):
    asset_class: str
    triggered: bool


@router.get("/status", response_model=ExecutionStatus)
async def execution_status(auth: AuthDep):
    return ExecutionStatus(
        executor_mode=settings.executor_mode,
        coinbase_sandbox=settings.coinbase_sandbox,
        worker_asset_classes_default_crypto_seconds=settings.worker_tick_seconds_crypto,
        worker_asset_classes_default_equity_seconds=settings.worker_tick_seconds_equity,
    )


@router.post("/run_cycle", response_model=RunCycleResponse)
async def run_cycle(body: RunCycleRequest, auth: AuthDep):
    if not auth.internal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="run_cycle requires X-Internal-Secret",
        )

    # Lazy import — pulls in worker.tick (which transitively imports the
    # whole signal stack). Keeping it lazy avoids paying that cost on a
    # stock api startup that doesn't run cycles.
    from worker.tick import tick_once

    await tick_once(body.asset_class)
    return RunCycleResponse(asset_class=body.asset_class, triggered=True)
