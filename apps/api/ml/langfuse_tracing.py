"""
Optional Langfuse tracing for the signal pipeline.

When ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are both set, this
module exposes context managers that emit a Langfuse trace per pipeline run
with nested spans for each step. When either key is missing, the helpers
become no-ops so local development and CI do not require network access or
credentials.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from config import settings

logger = logging.getLogger(__name__)

_client: Any | None = None
_init_attempted = False


def is_enabled() -> bool:
    """Both Langfuse keys must be set for tracing to be active."""
    return bool(settings.langfuse_public_key) and bool(settings.langfuse_secret_key)


def get_client() -> Any | None:
    """Lazy singleton Langfuse client. Returns None when disabled or on error."""
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True

    if not is_enabled():
        return None

    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host or None,
        )
        logger.info("Langfuse tracing enabled (host=%s)", settings.langfuse_host)
    except Exception as exc:
        logger.warning("Failed to initialize Langfuse client: %s", exc)
        _client = None
    return _client


def flush() -> None:
    """Flush pending events. Safe to call even when disabled."""
    client = get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        logger.warning("Langfuse flush failed: %s", exc)


class _NoopSpan:
    """Drop-in replacement when tracing is disabled — accepts any update call."""

    def update(self, **_: Any) -> None:
        return None


@contextmanager
def trace_pipeline(ticker: str, timeframe: str) -> Iterator[Any]:
    """Root span for one signal pipeline invocation.

    Yields a span-like object that supports ``.update(input=..., output=...,
    metadata=...)``. Errors inside the ``with`` block are recorded on the span
    and re-raised. Returns a no-op span when Langfuse is not configured.
    """
    client = get_client()
    if client is None:
        yield _NoopSpan()
        return

    cm = client.start_as_current_observation(
        as_type="span",
        name="signal_pipeline",
        input={"ticker": ticker, "timeframe": timeframe},
    )
    try:
        with cm as span:
            try:
                yield span
            except Exception as exc:
                try:
                    span.update(level="ERROR", status_message=str(exc))
                except Exception:
                    pass
                raise
    except Exception:
        raise


@contextmanager
def child_span(name: str, **input_metadata: Any) -> Iterator[Any]:
    """Nested span inside the active pipeline trace."""
    client = get_client()
    if client is None:
        yield _NoopSpan()
        return

    cm = client.start_as_current_observation(
        as_type="span",
        name=name,
        input=input_metadata or None,
    )
    try:
        with cm as span:
            try:
                yield span
            except Exception as exc:
                try:
                    span.update(level="ERROR", status_message=str(exc))
                except Exception:
                    pass
                raise
    except Exception:
        raise


def reset_for_tests() -> None:
    """Test helper: clear cached client so settings changes take effect."""
    global _client, _init_attempted
    _client = None
    _init_attempted = False
