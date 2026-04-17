"""Stripe webhook handler + license-lookup routes.

Mounted onto the FastMCP streamable-HTTP server via `@mcp.custom_route` in
server.py when HTTP mode is active.

Endpoints
---------
- GET  /health                    — Railway/Fly health probe
- POST /stripe/webhook            — Stripe event receiver
- GET  /license/lookup?session_id — customer self-serve key retrieval
                                    (fallback if the welcome email fails)

Security
--------
- Webhook payloads are verified via Stripe's signing secret
  (`STRIPE_WEBHOOK_SECRET`). No signature = 400.
- License lookup is session-id based — someone would need the exact
  `cs_test_*` / `cs_live_*` string from their redirect URL, which isn't
  enumerable.
- Nothing here mutates Stripe state; we only read events and write our
  own license store.

Dependencies
------------
- Requires the `stripe` package (added to pyproject.toml).
- Requires `STRIPE_WEBHOOK_SECRET` env var in HTTP mode. Missing secret →
  the webhook route returns 503 on every call rather than silently
  accepting unsigned payloads.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from hvac_mcp.storage import LicenseStore, Tier

logger = logging.getLogger(__name__)

WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"

# Map Stripe Product metadata[tier] values to our Tier literal.
_VALID_TIERS: set[str] = {"starter", "pro", "lifetime"}


def _tier_from_session(session: dict[str, Any]) -> Tier | None:
    """Extract our tier from a Checkout Session.

    Preferred path: the Price has metadata[tier] set by our creation script.
    Fallback: match by unit_amount (29/79/399 → starter/pro/lifetime).
    """
    line_items = session.get("line_items", {}).get("data", []) or []
    for item in line_items:
        price = item.get("price", {}) or {}
        tier = (price.get("metadata") or {}).get("tier")
        if tier in _VALID_TIERS:
            return tier  # type: ignore[return-value]
        product = price.get("product") or {}
        if isinstance(product, dict):
            tier = (product.get("metadata") or {}).get("tier")
            if tier in _VALID_TIERS:
                return tier  # type: ignore[return-value]
    # Amount-based fallback (cents)
    amount_total = session.get("amount_total")
    return {2900: "starter", 7900: "pro", 39900: "lifetime"}.get(amount_total)  # type: ignore[return-value]


def _verify_and_parse(request_body: bytes, sig_header: str | None) -> dict[str, Any]:
    """Verify the Stripe signature and return the parsed event dict.

    Raises ValueError on any verification or parse failure — caller maps to 400.
    """
    secret = os.environ.get(WEBHOOK_SECRET_ENV, "").strip()
    if not secret:
        raise RuntimeError(f"{WEBHOOK_SECRET_ENV} not configured")
    if not sig_header:
        raise ValueError("missing Stripe-Signature header")

    # Import lazily so import-time doesn't fail for stdio-only deployments.
    import stripe  # type: ignore[import-untyped]

    try:
        event = stripe.Webhook.construct_event(request_body, sig_header, secret)
    except (stripe.error.SignatureVerificationError, ValueError) as e:  # type: ignore[attr-defined]
        raise ValueError(f"signature verification failed: {e}") from e
    return event if isinstance(event, dict) else event.to_dict()  # type: ignore[no-any-return]


async def stripe_webhook(request: Request) -> JSONResponse:
    """Handle a Stripe event. Returns 200 on success, 4xx on bad input."""
    body = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = _verify_and_parse(body, sig)
    except RuntimeError as e:
        logger.error("Webhook misconfigured: %s", e)
        return JSONResponse({"error": "webhook_not_configured"}, status_code=503)
    except ValueError as e:
        logger.warning("Rejected webhook: %s", e)
        return JSONResponse({"error": "invalid_signature"}, status_code=400)

    event_type = event.get("type", "")
    data_obj: dict[str, Any] = event.get("data", {}).get("object", {})
    store = LicenseStore()

    if event_type == "checkout.session.completed":
        tier = _tier_from_session(data_obj)
        if tier is None:
            logger.warning("checkout.session.completed with unknown tier: %s", data_obj.get("id"))
            return JSONResponse({"received": True, "issued": False, "reason": "unknown_tier"})
        customer_id = data_obj.get("customer") or ""
        session_id = data_obj.get("id") or ""
        if not session_id:
            return JSONResponse({"error": "missing_session_id"}, status_code=400)
        lic = store.issue(
            tier=tier,
            stripe_customer_id=str(customer_id),
            stripe_session_id=str(session_id),
        )
        # In v1 we log the key; Phase 3.1 wires Resend/SMTP here.
        logger.info(
            "Issued license (tier=%s, customer=%s, session=%s, key=%s)",
            lic.tier,
            lic.stripe_customer_id,
            lic.stripe_session_id,
            lic.key,
        )
        return JSONResponse({"received": True, "issued": True, "key": lic.key})

    if event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        customer_id = data_obj.get("customer") or ""
        n = store.set_status_for_customer(str(customer_id), "cancelled")
        logger.info("Cancelled %d license(s) for customer %s", n, customer_id)
        return JSONResponse({"received": True, "cancelled": n})

    if event_type == "invoice.payment_failed":
        customer_id = data_obj.get("customer") or ""
        n = store.set_status_for_customer(str(customer_id), "past_due")
        logger.info("Marked %d license(s) past_due for customer %s", n, customer_id)
        return JSONResponse({"received": True, "past_due": n})

    if event_type == "charge.refunded":
        # For one-time (lifetime) refunds. Subscription refunds still fire
        # customer.subscription.deleted in the normal flow.
        customer_id = data_obj.get("customer") or ""
        n = store.set_status_for_customer(str(customer_id), "refunded")
        logger.info("Refunded %d license(s) for customer %s", n, customer_id)
        return JSONResponse({"received": True, "refunded": n})

    # Unhandled events are fine — acknowledge so Stripe doesn't retry.
    logger.debug("Ignored webhook event: %s", event_type)
    return JSONResponse({"received": True, "ignored": event_type})


async def license_lookup(request: Request) -> JSONResponse:
    """Customer-facing endpoint to fetch a license key by Stripe session id.

    Usage: after checkout, Stripe redirects back with `?session_id=cs_...`.
    The landing page's success view can fetch /license/lookup?session_id=…
    to display the key immediately — no email dependency.
    """
    session_id = request.query_params.get("session_id", "").strip()
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    lic = LicenseStore().get_by_session(session_id)
    if lic is None:
        # Might just be a race — webhook hasn't fired yet. 404 so the frontend
        # can back off and retry.
        return JSONResponse({"error": "not_found_yet"}, status_code=404)
    return JSONResponse(
        {
            "key": lic.key,
            "tier": lic.tier,
            "status": lic.status,
            "issued_at": lic.issued_at,
        }
    )


async def health(request: Request) -> JSONResponse:
    """Tiny health endpoint for Railway/Fly liveness probes."""
    return JSONResponse({"status": "ok", "service": "hvac-mcp"})


# Expose the route list for server.py to register.
ROUTES = (
    ("/health", "GET", health),
    ("/stripe/webhook", "POST", stripe_webhook),
    ("/license/lookup", "GET", license_lookup),
)


# Re-exported so tests can reach the internal parser without a real request.
__all__ = [
    "ROUTES",
    "WEBHOOK_SECRET_ENV",
    "_tier_from_session",
    "_verify_and_parse",
    "health",
    "license_lookup",
    "stripe_webhook",
]

# Preserve the json import for typing (the webhook body is JSON, Stripe SDK
# handles parsing; this is just to keep stdlib json visible for test helpers).
_ = json
