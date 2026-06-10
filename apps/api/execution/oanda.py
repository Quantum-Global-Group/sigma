"""OANDA forex executor (v20 REST via oandapyV20).

Paper-first, mirroring AlpacaExecutor's contract and guardrails: live trading
needs an explicit opt-in (oanda_paper=False AND oanda_allow_live=True). The SDK
is synchronous, so calls run in a thread executor; `api` is injectable for tests
so CI needs no live OANDA account.

Forex trades in *units* of the base currency (signed: BUY=+units, SELL=−units;
1 standard lot = 100,000 units). OANDA market orders fill immediately, so the
fill price + units come straight back in the OrderCreate response's
`orderFillTransaction` — no polling needed (a light fallback handles the rare
pending case). PnL is exact for USD-quote pairs (EUR_USD…); for USD-base/cross
pairs it's denominated in the quote currency (accepted paper-MVP simplification).
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
    Side,
    new_id,
)

logger = logging.getLogger(__name__)


class OandaExecutor(Executor):
    name = "oanda"

    def __init__(self, api: Optional[object] = None) -> None:
        if not (settings.oanda_api_token and settings.oanda_account_id):
            raise ValueError(
                "OANDA credentials missing — set OANDA_API_TOKEN and OANDA_ACCOUNT_ID."
            )
        if not settings.oanda_paper and not settings.oanda_allow_live:
            raise ValueError(
                "Live OANDA trading is disabled. Set OANDA_ALLOW_LIVE=true to enable "
                "(OANDA_PAPER=false)."
            )
        self._api = api
        self._account = settings.oanda_account_id

    @property
    def api(self):
        if self._api is None:
            from oandapyV20 import API  # lazy
            env = "live" if (not settings.oanda_paper and settings.oanda_allow_live) else "practice"
            self._api = API(access_token=settings.oanda_api_token, environment=env)
            logger.info("OANDA client ready (env=%s)", env)
        return self._api

    async def place(self, intent: OrderIntent) -> ExecutionReport:
        order = Order(order_id=new_id("oanda"), intent=intent, submitted_at=datetime.now(timezone.utc))

        rejection = self._precheck(intent)
        if rejection is not None:
            order.status = OrderStatus.REJECTED
            order.rejected_reason = rejection
            return ExecutionReport(order=order, fills=[])

        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(None, lambda: self._submit(intent))
        except Exception as exc:
            logger.exception("[oanda] order failed for %s", intent.symbol)
            order.status = OrderStatus.REJECTED
            order.rejected_reason = str(exc)
            return ExecutionReport(order=order, fills=[])

        fill_txn = (resp or {}).get("orderFillTransaction")
        if fill_txn is None:
            # Order accepted but not yet filled (rare for market orders), or rejected.
            reject = (resp or {}).get("orderRejectTransaction") or (resp or {}).get("orderCancelTransaction")
            if reject is not None:
                order.status = OrderStatus.REJECTED
                order.rejected_reason = str(reject.get("reason", reject))
                logger.warning("[oanda] order rejected %s: %s", intent.symbol, order.rejected_reason)
                return ExecutionReport(order=order, fills=[])
            create_txn = (resp or {}).get("orderCreateTransaction", {})
            order.order_id = str(create_txn.get("id", order.order_id))
            order.status = OrderStatus.SUBMITTED
            return ExecutionReport(order=order, fills=[])

        broker_id = str(fill_txn.get("id", order.order_id))
        units = abs(float(fill_txn.get("units", intent.qty or 0)))
        price = float(fill_txn.get("price", intent.limit_px or 0) or 0)
        now = datetime.now(timezone.utc)

        order.order_id = broker_id
        order.filled_qty = units
        order.avg_fill_price = price or None
        order.status = OrderStatus.FILLED if units > 0 else OrderStatus.SUBMITTED
        order.updated_at = now

        fills = []
        if units > 0 and price > 0:
            ref = intent.limit_px
            slippage_bps = abs(price - ref) / ref * 10_000.0 if ref else None
            commission = abs(float(fill_txn.get("commission", 0) or 0))
            fills.append(Fill(
                fill_id=new_id("fill"), order_id=broker_id,
                asset_class=intent.asset_class, symbol=intent.symbol,
                side=intent.side, qty=units, price=price, timestamp=now,
                commission=commission,
                slippage_bps=round(slippage_bps, 4) if slippage_bps is not None else None,
                executor=self.name, external_id=broker_id,
            ))
        return ExecutionReport(order=order, fills=fills)

    async def get_account_equity(self) -> Optional[float]:
        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(None, self._account_summary)
        except Exception:
            logger.exception("[oanda] account summary failed")
            return None
        acct = (resp or {}).get("account", {})
        for key in ("NAV", "balance"):
            val = acct.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return None

    # ---- internal -------------------------------------------------------

    def _precheck(self, intent: OrderIntent) -> Optional[str]:
        if intent.qty is None or intent.qty <= 0:
            return "qty (units) required and must be positive"
        return None

    def _submit(self, intent: OrderIntent):
        from oandapyV20.endpoints.orders import OrderCreate

        instrument = intent.symbol.upper().replace("/", "_").replace("-", "_")
        if "_" not in instrument and len(instrument) == 6:
            instrument = f"{instrument[:3]}_{instrument[3:]}"
        # Signed units: BUY positive, SELL negative. OANDA wants whole units.
        signed = int(intent.qty) if intent.side == Side.BUY else -int(intent.qty)
        data = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(signed),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "clientExtensions": {"id": intent.normalized_client_order_id()[:128]},
            }
        }
        req = OrderCreate(accountID=self._account, data=data)
        self.api.request(req)
        return req.response

    def _account_summary(self):
        from oandapyV20.endpoints.accounts import AccountSummary
        req = AccountSummary(accountID=self._account)
        self.api.request(req)
        return req.response
