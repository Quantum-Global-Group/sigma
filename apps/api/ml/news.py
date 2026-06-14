"""Historical news events from the Alpaca News API (Benzinga-sourced).

Extracted from scripts/sentiment_experiment_v2.py, where the fetch was proven to
work with our credentials, into a reusable + testable module. Returns discrete
*events* (the unit of analysis for event-driven research) rather than a daily
sentiment aggregate.

No new dependency: plain `requests`, on-disk cache per (symbol, window) so FinBERT
scoring downstream isn't re-run. The HTTP getter is injectable so the parser and
cache are unit-tested without network.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Callable, Optional

import requests

from config import settings

logger = logging.getLogger(__name__)

_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
_CACHE_DIR = os.environ.get("SIGMA_NEWS_CACHE", "/tmp/sigma_news_cache")


@dataclass(frozen=True)
class NewsEvent:
    symbol: str
    ts: str          # ISO created_at (UTC)
    headline: str
    summary: str
    source: str = ""

    @property
    def text(self) -> str:
        """Headline + summary — what the sentiment scorer consumes."""
        return (self.headline + ". " + self.summary).strip()


def _headers() -> dict:
    return {"APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret}


def parse_news(payload: dict, symbol: str) -> list[NewsEvent]:
    """Map one Alpaca /news page into NewsEvent rows. Pure."""
    out: list[NewsEvent] = []
    for a in payload.get("news", []):
        ts = a.get("created_at")
        if not ts:
            continue
        out.append(NewsEvent(
            symbol=symbol,
            ts=str(ts),
            headline=str(a.get("headline", "") or ""),
            summary=str(a.get("summary", "") or ""),
            source=str(a.get("source", "") or ""),
        ))
    return out


def fetch_news(
    symbol: str,
    start_iso: str,
    end_iso: Optional[str] = None,
    *,
    max_pages: int = 60,
    getter: Optional[Callable[[str, dict], dict]] = None,
) -> list[NewsEvent]:
    """All news for `symbol` in [start_iso, end_iso], paginated, oldest-first.

    `getter(url, params) -> json` is injectable for tests; defaults to a real
    GET. Never raises on a bad page — returns what it has."""
    get = getter or _default_get
    events: list[NewsEvent] = []
    token: Optional[str] = None
    for _ in range(max_pages):
        params = {"symbols": symbol, "start": start_iso, "limit": 50, "sort": "asc"}
        if end_iso:
            params["end"] = end_iso
        if token:
            params["page_token"] = token
        try:
            payload = get(_NEWS_URL, params)
        except Exception:
            logger.warning("news fetch failed for %s", symbol, exc_info=True)
            break
        events.extend(parse_news(payload, symbol))
        token = payload.get("next_page_token")
        if not token:
            break
    return events


def fetch_news_cached(symbol: str, start_iso: str, end_iso: Optional[str] = None,
                      **kw) -> list[NewsEvent]:
    """fetch_news with a JSON disk cache keyed by (symbol, start)."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f"{symbol}_{start_iso[:10]}.json")
    if os.path.exists(path):
        try:
            return [NewsEvent(**r) for r in json.load(open(path))]
        except Exception:
            pass
    events = fetch_news(symbol, start_iso, end_iso, **kw)
    try:
        json.dump([asdict(e) for e in events], open(path, "w"))
    except Exception:
        logger.warning("news cache write failed for %s", symbol, exc_info=True)
    return events


def _default_get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=_headers(), timeout=25)
    r.raise_for_status()
    return r.json()
