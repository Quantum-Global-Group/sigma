"""Option data interface — chains, contracts, and per-contract quotes.

Option chains aren't OHLCV-shaped, so they live behind their own
`OptionDataProvider` protocol rather than `MarketAdapter.fetch_ohlcv`. The
Moomoo implementation talks to a local OpenD gateway via the `moomoo`/`futu`
SDK (lazy-imported); tests inject a fake quote context so CI needs no gateway.

Normalized return types (`OptionContract`, `OptionQuote`) keep the rest of the
options stack broker-agnostic — Phases 3-6 consume these, not Moomoo objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional, Protocol, runtime_checkable

from config import settings

logger = logging.getLogger(__name__)

Right = str  # "call" | "put"


@dataclass(frozen=True)
class OptionContract:
    underlying: str
    expiry: date
    strike: float
    right: Right                 # "call" | "put"
    code: str                    # broker-native code (e.g. "US.AAPL250117C250000")
    multiplier: int = 100

    @property
    def occ(self) -> str:
        """OCC-style symbol, e.g. AAPL  250117C00250000 → 'AAPL250117C00250000'."""
        ymd = self.expiry.strftime("%y%m%d")
        cp = "C" if self.right == "call" else "P"
        strike_mils = int(round(self.strike * 1000))
        return f"{self.underlying}{ymd}{cp}{strike_mils:08d}"


@dataclass(frozen=True)
class OptionQuote:
    contract: OptionContract
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_vol: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    ts: Optional[datetime] = None

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last


@runtime_checkable
class OptionDataProvider(Protocol):
    """What the options stack needs from any option-data source."""

    def list_expiries(self, underlying: str) -> list[date]: ...
    def get_chain(self, underlying: str, expiry: date) -> list[OptionContract]: ...
    def get_quote(self, contract: OptionContract) -> Optional[OptionQuote]: ...
    def get_quotes(self, contracts: list[OptionContract]) -> list[OptionQuote]: ...


# ---------------------------------------------------------------------------
# Moomoo implementation
# ---------------------------------------------------------------------------

_RET_OK = 0  # moomoo.RET_OK


class MoomooOptionData:
    """OptionDataProvider backed by Moomoo OpenD (`OpenQuoteContext`).

    `quote_ctx` is injectable for tests; in production it's lazily created from
    settings.moomoo_host/port. All SDK calls return (ret_code, data) where data
    is a pandas DataFrame; parsing is defensive so partial fields degrade to None.
    """

    def __init__(self, quote_ctx: Optional[object] = None) -> None:
        self._ctx = quote_ctx

    @property
    def ctx(self):
        if self._ctx is None:
            from moomoo import OpenQuoteContext  # lazy: SDK not on the API boot path
            self._ctx = OpenQuoteContext(host=settings.moomoo_host, port=settings.moomoo_port)
        return self._ctx

    @staticmethod
    def _code(underlying: str) -> str:
        return underlying if "." in underlying else f"US.{underlying}"

    def list_expiries(self, underlying: str) -> list[date]:
        ret, data = self.ctx.get_option_expiration_date(code=self._code(underlying))
        if ret != _RET_OK:
            logger.warning("[moomoo] expiry query failed for %s: %s", underlying, data)
            return []
        out: list[date] = []
        for _, row in data.iterrows():
            try:
                out.append(datetime.strptime(str(row["strike_time"]), "%Y-%m-%d").date())
            except (KeyError, ValueError):
                continue
        return sorted(out)

    def get_chain(self, underlying: str, expiry: date) -> list[OptionContract]:
        ds = expiry.strftime("%Y-%m-%d")
        ret, data = self.ctx.get_option_chain(code=self._code(underlying), start=ds, end=ds)
        if ret != _RET_OK:
            logger.warning("[moomoo] chain query failed for %s %s: %s", underlying, ds, data)
            return []
        contracts: list[OptionContract] = []
        for _, row in data.iterrows():
            try:
                otype = str(row.get("option_type", "")).lower()
                right = "call" if otype.startswith("c") else "put"
                contracts.append(OptionContract(
                    underlying=underlying.split(".")[-1],
                    expiry=expiry,
                    strike=float(row["strike_price"]),
                    right=right,
                    code=str(row["code"]),
                ))
            except (KeyError, ValueError, TypeError):
                continue
        return contracts

    def get_quotes(self, contracts: list[OptionContract]) -> list[OptionQuote]:
        if not contracts:
            return []
        codes = [c.code for c in contracts]
        ret, data = self.ctx.get_market_snapshot(codes)
        if ret != _RET_OK:
            logger.warning("[moomoo] snapshot failed: %s", data)
            return []
        by_code = {str(row["code"]): row for _, row in data.iterrows()}
        out: list[OptionQuote] = []
        for c in contracts:
            row = by_code.get(c.code)
            if row is None:
                continue
            out.append(_quote_from_row(c, row))
        return out

    def get_quote(self, contract: OptionContract) -> Optional[OptionQuote]:
        quotes = self.get_quotes([contract])
        return quotes[0] if quotes else None


def _fnum(row, key, default=None):
    try:
        v = row[key]
        return float(v) if v is not None else default
    except (KeyError, TypeError, ValueError):
        return default


def _quote_from_row(contract: OptionContract, row) -> OptionQuote:
    return OptionQuote(
        contract=contract,
        bid=_fnum(row, "bid_price", 0.0) or 0.0,
        ask=_fnum(row, "ask_price", 0.0) or 0.0,
        last=_fnum(row, "last_price", 0.0) or 0.0,
        volume=int(_fnum(row, "volume", 0) or 0),
        open_interest=int(_fnum(row, "option_open_interest", 0) or 0),
        implied_vol=_fnum(row, "option_implied_volatility"),
        delta=_fnum(row, "option_delta"),
        gamma=_fnum(row, "option_gamma"),
        theta=_fnum(row, "option_theta"),
        vega=_fnum(row, "option_vega"),
        ts=datetime.now(timezone.utc),
    )


def get_option_data_provider() -> OptionDataProvider:
    """Factory — currently Moomoo-only; mirrors get_market_adapter's shape."""
    return MoomooOptionData()
