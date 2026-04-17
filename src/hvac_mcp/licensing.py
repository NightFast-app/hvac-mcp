"""License key enforcement for premium tools.

Design: license key is passed via an environment variable for stdio transport
(set in the MCP client config), or via the `Authorization: Bearer <key>` header
for HTTP transport. Validation is a cheap local check for dev; production
verifies against Stripe customer metadata.

Free-tier tools NEVER call these helpers — they are always available.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

LICENSE_ENV_VAR = "HVAC_MCP_LICENSE_KEY"
PURCHASE_URL = "https://hvac-mcp.nightfast.tech/pricing"

# Dev-mode allow-list. In production, replace with a Stripe metadata lookup
# (cached to avoid hitting Stripe on every tool call).
_DEV_ALLOWED_KEYS: set[str] = {
    "DEV-LOCAL-KEY-DO-NOT-SHIP",
}


class LicenseError(Exception):
    """Raised when a premium tool is called without a valid license."""


def _current_license_key() -> str | None:
    """Read the license key from the environment. Returns None if unset/empty."""
    key = os.environ.get(LICENSE_ENV_VAR, "").strip()
    return key or None


def is_licensed() -> bool:
    """Return True if a valid license is present in the current context.

    Resolution order:
      1. Dev allow-list (for local testing, never ship keys from this set).
      2. Key present in the local LicenseStore with status='active'
         (populated by Stripe webhooks — see webhook.py).
    """
    key = _current_license_key()
    if not key:
        return False
    if key in _DEV_ALLOWED_KEYS:
        return True
    try:
        from hvac_mcp.storage import LicenseStore  # lazy: storage is optional

        return LicenseStore().is_active(key)
    except Exception as e:
        logger.warning("License store unavailable, denying: %s", e)
        return False


def require_license() -> None:
    """Raise LicenseError if no valid license is active. Call at the top of every premium tool."""
    if not is_licensed():
        raise LicenseError(
            "This is a premium tool. Set a valid license key via the "
            f"{LICENSE_ENV_VAR} environment variable. "
            f"Purchase at {PURCHASE_URL}."
        )


def premium(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Decorator that gates an async tool behind a license check.

    Returns an actionable error string to the MCP client rather than raising,
    so the LLM sees a clear next step ("tell the user to go buy a license").
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            require_license()
        except LicenseError as e:
            logger.info("Premium tool %s blocked: no license", func.__name__)
            return {
                "error": "license_required",
                "message": str(e),
                "purchase_url": PURCHASE_URL,
            }
        return await func(*args, **kwargs)

    return wrapper
