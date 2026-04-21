"""
Stripe billing helpers.
All functions no-op gracefully when STRIPE_SECRET_KEY is blank so local
dev works without real credentials.
"""

from __future__ import annotations

import logging

from config import settings

logger = logging.getLogger(__name__)


def _client():
    if not settings.stripe_secret_key:
        return None
    import stripe  # lazy import — not installed in minimal dev env

    stripe.api_key = settings.stripe_secret_key
    return stripe


async def create_customer(email: str, clerk_id: str) -> str | None:
    """Create a Stripe customer and return the customer ID, or None if unconfigured."""
    stripe = _client()
    if stripe is None:
        logger.debug("Stripe not configured — skipping create_customer")
        return None
    try:
        customer = stripe.Customer.create(
            email=email,
            metadata={"clerk_id": clerk_id},
        )
        return customer.id
    except Exception as exc:
        logger.warning("Stripe create_customer failed: %s", exc)
        return None


async def record_usage(customer_id: str | None, quantity: int = 1) -> None:
    """Report a metered usage event to Stripe. No-ops if unconfigured."""
    if not customer_id or not settings.stripe_secret_key or not settings.stripe_meter_id:
        return
    stripe = _client()
    if stripe is None:
        return
    try:
        stripe.billing.MeterEvent.create(
            event_name=settings.stripe_meter_id,
            payload={"stripe_customer_id": customer_id, "value": str(quantity)},
        )
    except Exception as exc:
        logger.warning("Stripe record_usage failed: %s", exc)


async def create_subscription(customer_id: str, price_id: str) -> str | None:
    """Create a Stripe subscription and return the subscription ID, or None if unconfigured."""
    stripe = _client()
    if stripe is None:
        logger.debug("Stripe not configured — skipping create_subscription")
        return None
    try:
        sub = stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id}],
        )
        return sub.id
    except Exception as exc:
        logger.warning("Stripe create_subscription failed: %s", exc)
        return None


async def create_billing_portal_session(customer_id: str, return_url: str) -> str | None:
    """Return a Stripe billing portal URL for the customer."""
    stripe = _client()
    if stripe is None:
        return None
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return session.url
    except Exception as exc:
        logger.warning("Stripe create_billing_portal_session failed: %s", exc)
        return None
