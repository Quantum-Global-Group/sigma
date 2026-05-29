"""Moomoo options/equities executor (OpenD `OpenSecTradeContext`).

Paper-first, mirroring AlpacaExecutor's contract and guardrails: live trading
needs an explicit opt-in (moomoo_paper=False AND moomoo_allow_live=True). The
SDK is synchronous, so calls run in a thread executor; `trade_ctx` is injectable
for tests so CI needs no OpenD gateway.

OrderIntent.symbol carries the broker-native option/stock code (e.g.
"US.AAPL250117C250000"); get_account_equity reports the simulated/real balance
for sizing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from config import settings

from .base import (
    Executor,
    ExecutionReport,
    Fill,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Side,
    new_id,
)

logger = logging.getLogger(__name__)

_RET_OK = 0  # moomoo.RET_OK


class MoomooExecutor(Executor):
    name = "moomoo"

    def __init__(self, trade_ctx: Optional[object] = None) -> None:
        if not settings.moomoo_paper and not settings.moomoo_allow_live:
            raise ValueError(
                "Live Moomoo trading is disabled. Set MOOMOO_ALLOW_LIVE=true to enable "
                "(MOOMOO_PAPER=false)."
            )
        self._ctx = trade_ctx
        self._paper = settings.moomoo_paper

    @property
    def ctx(self):
        if self._ctx is None:
            from moomoo import OpenSecTradeContext, TrdMarket, SecurityFirm  # lazy
            firm = getattr(SecurityFirm, settings.moomoo_security_firm, SecurityFirm.FUTUINC)
            market = getattr(TrdMarket, settings.moomoo_trd_market, TrdMarket.US)
            self._ctx = OpenSecTradeContext(
                host=settings.moomoo_host, port=settings.moomoo_port,
                filter_trdmarket=market, security_firm=firm,
            )
        return self._ctx

    def _trd_env(self):
        from moomoo import TrdEnv
        return TrdEnv.SIMULATE if self._paper else TrdEnv.REAL

    async def place(self, intent: OrderIntent) -> ExecutionReport:
        order = Order(order_id=new_id("moo"), intent=intent, submitted_at=datetime.now(timezone.utc))

        rejection = self._precheck(intent)
        if rejection is not None:
            order.status = OrderStatus.REJECTED
            order.rejected_reason = rejection
            return ExecutionReport(order=order, fills=[])

        loop = asyncio.get_event_loop()
        try:
            ret, data = await loop.run_in_executor(None, lambda: self._submit(intent))
            if ret != _RET_OK:
                order.status = OrderStatus.REJECTED
                order.rejected_reason = str(data)
                logger.warning("[moomoo] place rejected %s: %s", intent.symbol, data)
                return ExecutionReport(order=order, fills=[])

            broker_id, status, filled_qty, avg_px = _parse_order_row(data)
            order.order_id = broker_id or order.order_id
            order.status = OrderStatus.SUBMITTED

            if filled_qty <= 0:
                filled = await self._poll_fill(broker_id)
                if filled is not None:
                    _, status, filled_qty, avg_px = _parse_order_row(filled)

            order.filled_qty = filled_qty
            order.avg_fill_price = avg_px or None
            order.status = OrderStatus.FILLED if filled_qty > 0 else OrderStatus.SUBMITTED
            order.updated_at = datetime.now(timezone.utc)

            fills = []
            if filled_qty > 0 and avg_px > 0:
                ref = intent.limit_px
                slip = abs(avg_px - ref) / ref * 10_000.0 if ref else None
                fills.append(Fill(
                    fill_id=new_id("fill"), order_id=order.order_id,
                    asset_class=intent.asset_class, symbol=intent.symbol,
                    side=intent.side, qty=filled_qty, price=avg_px,
                    timestamp=datetime.now(timezone.utc), commission=0.0,
                    slippage_bps=round(slip, 4) if slip is not None else None,
                    executor=self.name, external_id=order.order_id,
                ))
            return ExecutionReport(order=order, fills=fills)
        except Exception as exc:
            logger.exception("[moomoo] order failed for %s", intent.symbol)
            order.status = OrderStatus.REJECTED
            order.rejected_reason = str(exc)
            return ExecutionReport(order=order, fills=[])

    async def get_account_equity(self) -> Optional[float]:
        loop = asyncio.get_event_loop()
        try:
            ret, data = await loop.run_in_executor(
                None, lambda: self.ctx.accinfo_query(trd_env=self._trd_env())
            )
        except Exception:
            logger.exception("[moomoo] accinfo_query failed")
            return None
        if ret != _RET_OK or data is None or len(data) == 0:
            return None
        row = data.iloc[0]
        for key in ("total_assets", "net_cash_power", "cash"):
            try:
                val = row[key]
                if val is not None:
                    return float(val)
            except (KeyError, TypeError, ValueError):
                continue
        return None

    # ---- internal -------------------------------------------------------

    def _precheck(self, intent: OrderIntent) -> Optional[str]:
        if intent.qty is None or intent.qty <= 0:
            return "qty required and must be positive"
        return None

    def _submit(self, intent: OrderIntent):
        from moomoo import TrdSide, OrderType as MooOrderType
        side = TrdSide.BUY if intent.side == Side.BUY else TrdSide.SELL
        otype = MooOrderType.MARKET if intent.order_type == OrderType.MARKET else MooOrderType.NORMAL
        price = intent.limit_px or 0.0
        return self.ctx.place_order(
            price=price, qty=int(intent.qty), code=intent.symbol,
            trd_side=side, order_type=otype, trd_env=self._trd_env(),
        )

    async def _poll_fill(self, order_id: Optional[str]):
        if not order_id:
            return None
        timeout = settings.alpaca_order_timeout_seconds  # reuse the generic fill-poll budget
        deadline = datetime.now(timezone.utc).timestamp() + timeout
        loop = asyncio.get_event_loop()
        while datetime.now(timezone.utc).timestamp() < deadline:
            try:
                ret, data = await loop.run_in_executor(
                    None, lambda: self.ctx.order_list_query(order_id=order_id, trd_env=self._trd_env())
                )
            except Exception:
                logger.exception("[moomoo] poll error for %s", order_id)
                await asyncio.sleep(1.0)
                continue
            if ret == _RET_OK and data is not None and len(data) > 0:
                _, status, filled_qty, _ = _parse_order_row(data)
                if filled_qty > 0 or str(status).lower() in ("filled_all", "cancelled_all", "failed", "deleted"):
                    return data
            await asyncio.sleep(1.0)
        return None


def _parse_order_row(data):
    """Return (order_id, status, filled_qty, avg_price) from a Moomoo order DataFrame."""
    try:
        row = data.iloc[0]
    except (AttributeError, IndexError):
        return (None, "unknown", 0.0, 0.0)

    def g(key, default=None):
        try:
            v = row[key]
            return v if v is not None else default
        except (KeyError, TypeError):
            return default

    order_id = g("order_id")
    status = str(g("order_status", "unknown"))
    try:
        filled_qty = float(g("dealt_qty", 0) or 0)
    except (TypeError, ValueError):
        filled_qty = 0.0
    try:
        avg_px = float(g("dealt_avg_price", 0) or 0)
    except (TypeError, ValueError):
        avg_px = 0.0
    return (str(order_id) if order_id is not None else None, status, filled_qty, avg_px)
