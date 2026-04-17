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

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from hvac_mcp.storage import License, LicenseStore, Tier

logger = logging.getLogger(__name__)

WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"
RESEND_API_KEY_ENV = "RESEND_API_KEY"
EMAIL_FROM_ENV = "HVAC_MCP_EMAIL_FROM"
EMAIL_FROM_DEFAULT = "hvac-mcp <noreply@nightfast.tech>"
LANDING_URL = "https://nightfast-app.github.io/hvac-mcp"

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
        logger.info(
            "Issued license (tier=%s, customer=%s, session=%s, key=%s)",
            lic.tier,
            lic.stripe_customer_id,
            lic.stripe_session_id,
            lic.key,
        )
        # Best-effort email delivery — webhook ACK doesn't depend on it.
        customer_email = _extract_customer_email(data_obj)
        email_status = await _email_license_key(customer_email, lic)
        return JSONResponse(
            {
                "received": True,
                "issued": True,
                "key": lic.key,
                "email_sent": email_status == "sent",
                "email_status": email_status,
            }
        )

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


def _extract_customer_email(session: dict[str, Any]) -> str | None:
    """Pull the buyer's email out of a Checkout Session payload.

    Stripe puts the email in different places depending on the flow:
      - customer_details.email (always, for guest + saved customers)
      - customer_email (legacy Checkout field)
    """
    details = session.get("customer_details") or {}
    email = details.get("email") or session.get("customer_email")
    return email if isinstance(email, str) and "@" in email else None


async def _email_license_key(to_email: str | None, lic: License) -> str:
    """Deliver the license key via Resend. Returns a status string for logging.

    Design:
    - No RESEND_API_KEY → "skipped_no_provider". Key still logged; customer
      can fetch via /license/lookup. Prevents launch from blocking on email.
    - No to_email on the session → "skipped_no_address".
    - HTTP error → "failed_<status>". Webhook still returns 200 so Stripe
      doesn't retry the event (license was already issued).
    """
    if not to_email:
        logger.warning("No email on session — key %s must be fetched manually", lic.key)
        return "skipped_no_address"

    api_key = os.environ.get(RESEND_API_KEY_ENV, "").strip()
    if not api_key:
        logger.info("RESEND_API_KEY unset — email delivery skipped for %s", to_email)
        return "skipped_no_provider"

    subject = f"Your hvac-mcp {lic.tier.title()} license key"
    html = _build_welcome_email_html(lic)
    text = _build_welcome_email_text(lic)
    from_addr = os.environ.get(EMAIL_FROM_ENV, EMAIL_FROM_DEFAULT)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": from_addr,
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                    "text": text,
                },
            )
    except httpx.HTTPError as e:
        logger.error("Resend request failed for %s: %s", to_email, e)
        return "failed_network"

    if r.status_code >= 400:
        logger.error("Resend rejected email to %s (%s): %s", to_email, r.status_code, r.text[:200])
        return f"failed_{r.status_code}"
    logger.info("Welcome email sent to %s (tier=%s)", to_email, lic.tier)
    return "sent"


def _build_welcome_email_text(lic: License) -> str:
    return (
        f"Welcome to hvac-mcp {lic.tier.title()}.\n\n"
        f"Your license key:\n\n"
        f"    {lic.key}\n\n"
        "Setup (Claude Desktop — add to claude_desktop_config.json):\n\n"
        "{\n"
        '  "mcpServers": {\n'
        '    "hvac": {\n'
        '      "command": "uvx",\n'
        '      "args": ["--from", "git+https://github.com/NightFast-app/hvac-mcp", "hvac-mcp"],\n'
        f'      "env": {{"HVAC_MCP_LICENSE_KEY": "{lic.key}"}}\n'
        "    }\n"
        "  }\n"
        "}\n\n"
        f"All client configs: {LANDING_URL}/#setup\n\n"
        "Any problems, reply to this email.\n"
        "— Kollin\n"
    )


def _build_welcome_email_html(lic: License) -> str:
    return f"""<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:24px auto;color:#0b1220">
<h2 style="margin:0 0 8px">Welcome to hvac-mcp {lic.tier.title()}</h2>
<p>Your license key:</p>
<pre style="background:#0b1220;color:#e6edf7;padding:14px 18px;border-radius:8px;font-size:14px;overflow-x:auto">{lic.key}</pre>
<p><strong>Quick setup</strong> — add this to your Claude Desktop config
(<code>~/Library/Application Support/Claude/claude_desktop_config.json</code>
on macOS, <code>%APPDATA%\\Claude\\claude_desktop_config.json</code> on Windows),
then restart Claude Desktop:</p>
<pre style="background:#0b1220;color:#e6edf7;padding:14px 18px;border-radius:8px;font-size:13px;overflow-x:auto">{{
  "mcpServers": {{
    "hvac": {{
      "command": "uvx",
      "args": ["--from", "git+https://github.com/NightFast-app/hvac-mcp", "hvac-mcp"],
      "env": {{ "HVAC_MCP_LICENSE_KEY": "{lic.key}" }}
    }}
  }}
}}</pre>
<p>Using Claude Code / ChatGPT / Cursor? Full configs at
<a href="{LANDING_URL}">{LANDING_URL.replace("https://", "")}</a>.</p>
<p>Any issues, just reply — I'll see it.<br>— Kollin</p>
</body></html>"""


# CORS on /license/lookup only. The success page lives on a different origin
# than the API (Pages vs. Fly / nightfast.tech), so the browser enforces CORS.
# Stripe-signed webhook POSTs aren't cross-origin (Stripe server → our server,
# no browser involved), so /stripe/webhook doesn't need these headers.
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


async def license_lookup(request: Request) -> JSONResponse:
    """Customer-facing endpoint to fetch a license key by Stripe session id.

    Usage: after checkout, Stripe redirects back with `?session_id=cs_...`.
    The landing page's success view can fetch /license/lookup?session_id=…
    to display the key immediately — no email dependency.

    Called cross-origin from the Pages-hosted success page, so responses
    carry CORS headers. OPTIONS preflight also supported.
    """
    if request.method == "OPTIONS":
        return JSONResponse({}, status_code=204, headers=_CORS_HEADERS)
    session_id = request.query_params.get("session_id", "").strip()
    if not session_id:
        return JSONResponse(
            {"error": "session_id required"}, status_code=400, headers=_CORS_HEADERS
        )
    lic = LicenseStore().get_by_session(session_id)
    if lic is None:
        # Might just be a race — webhook hasn't fired yet. 404 so the frontend
        # can back off and retry.
        return JSONResponse({"error": "not_found_yet"}, status_code=404, headers=_CORS_HEADERS)
    return JSONResponse(
        {
            "key": lic.key,
            "tier": lic.tier,
            "status": lic.status,
            "issued_at": lic.issued_at,
        },
        headers=_CORS_HEADERS,
    )


async def health(request: Request) -> JSONResponse:
    """Tiny health endpoint for Railway/Fly liveness probes."""
    return JSONResponse({"status": "ok", "service": "hvac-mcp"})


# Expose the route list for server.py to register.
# /license/lookup accepts OPTIONS for CORS preflight (the success page
# triggers one on first load from a different origin).
ROUTES = (
    ("/health", "GET", health),
    ("/stripe/webhook", "POST", stripe_webhook),
    ("/license/lookup", "GET", license_lookup),
    ("/license/lookup", "OPTIONS", license_lookup),
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
