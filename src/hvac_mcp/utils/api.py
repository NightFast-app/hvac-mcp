"""Shared async HTTP client for premium-tier external API calls.

Free-tier tools MUST NOT use this — they rely on bundled data only. Premium
tools that hit external services (permit lookups, parts cross-reference) share
one client with a consistent timeout and error-handling contract.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0
USER_AGENT = "hvac-mcp/0.1.0 (+https://hvac-mcp.nightfast.tech)"


def make_client(timeout: float = DEFAULT_TIMEOUT_S) -> httpx.AsyncClient:
    """Construct a configured async client. Caller is responsible for closing.

    Prefer `async with make_client() as client: ...` over storing a module-level
    client — FastMCP's lifespan isn't guaranteed to cover all transports.
    """
    return httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def handle_api_error(e: Exception) -> dict[str, Any]:
    """Format any network error into an actionable structured response.

    The MCP client sees a dict, not an exception, so the LLM can explain the
    failure to the user and (if applicable) retry or suggest next steps.
    """
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            return {"error": "not_found", "message": "Resource not found. Check the ID."}
        if status == 403:
            return {"error": "forbidden", "message": "Permission denied for this resource."}
        if status == 429:
            return {
                "error": "rate_limited",
                "message": "Rate limit exceeded. Try again in a few seconds.",
            }
        return {"error": "http_error", "status": status, "message": f"Upstream returned {status}."}

    if isinstance(e, httpx.TimeoutException):
        return {"error": "timeout", "message": f"Request timed out after {DEFAULT_TIMEOUT_S}s."}

    if isinstance(e, httpx.RequestError):
        return {"error": "network_error", "message": f"Network error: {type(e).__name__}"}

    logger.exception("Unexpected error in api call")
    return {"error": "unexpected", "message": f"{type(e).__name__}: {e}"}
