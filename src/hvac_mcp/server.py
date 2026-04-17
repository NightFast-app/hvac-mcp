"""HVAC MCP Server — FastMCP entrypoint.

Boots a Model Context Protocol server exposing HVAC/plumbing domain tools.
Supports stdio transport (default, for Claude Desktop / Claude Code) and
streamable HTTP transport (for the hosted SaaS tier).

Run locally:
    uv run python -m hvac_mcp.server           # stdio
    uv run python -m hvac_mcp.server --http    # HTTP on :8000
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from hvac_mcp import webhook
from hvac_mcp.tools import (
    code_lookup,
    diagnostics,
    invoice,
    parts,
    refrigerant,
    sizing,
)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_HTTP_PORT = 8000
DEFAULT_HTTP_HOST = "0.0.0.0"  # bind all interfaces for container deploys

logger = logging.getLogger("hvac_mcp")

# Server instance — name follows {service}_mcp convention from MCP best practices.
# Transport settings (port/host/stateless) are configured at runtime in main()
# via mcp.settings before calling mcp.run().
mcp = FastMCP("hvac_mcp")


def register_all_tools() -> None:
    """Register every tool module's tools on the shared mcp instance.

    Each tool module exposes a `register(mcp)` function that wires its tools
    onto the server. This keeps server.py a thin orchestrator and tool modules
    independently testable.
    """
    refrigerant.register(mcp)
    diagnostics.register(mcp)
    code_lookup.register(mcp)
    sizing.register(mcp)
    parts.register(mcp)  # free-tier: capacitor cross-ref
    invoice.register(mcp)  # premium: invoice_draft, quote_from_diagnosis
    logger.info("All tool modules registered")


def register_http_routes() -> None:
    """Register HTTP-only routes (health, Stripe webhook, license lookup).

    These only matter for streamable-http transport. FastMCP's stdio mode
    ignores them, so there's no harm registering them unconditionally.
    """
    for path, method, handler in webhook.ROUTES:
        # FastMCP's @custom_route decorator is equivalent to calling the
        # decorator form with the method list.
        mcp.custom_route(path, methods=[method])(handler)
    logger.info("HTTP routes registered (%d)", len(webhook.ROUTES))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="hvac-mcp",
        description="HVAC/Plumbing MCP server for field technicians",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use streamable HTTP transport instead of stdio",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HVAC_MCP_HOST", DEFAULT_HTTP_HOST),
        help=f"HTTP bind host (default: {DEFAULT_HTTP_HOST}, env: HVAC_MCP_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", DEFAULT_HTTP_PORT)),
        help=f"HTTP port (default: {DEFAULT_HTTP_PORT}, env: PORT)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format=LOG_FORMAT, stream=sys.stderr)
    register_all_tools()
    register_http_routes()

    if args.http:
        # Streamable HTTP path: configure via mcp.settings, then run().
        # stateless_http + json_response are recommended for scalable hosted
        # deployments (per MCP python-sdk docs).
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.settings.stateless_http = True
        mcp.settings.json_response = True

        # DNS rebinding protection: FastMCP defaults to localhost-only for the
        # Host header. In a hosted deploy we need to whitelist our public
        # hostnames. Comma-separated via HVAC_MCP_ALLOWED_HOSTS.
        raw_allowed = os.environ.get("HVAC_MCP_ALLOWED_HOSTS", "").strip()
        allowed_hosts = [h.strip() for h in raw_allowed.split(",") if h.strip()]
        if allowed_hosts:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=allowed_hosts,
                # Browser CORS isn't our threat model (MCP clients aren't
                # browsers); leaving allowed_origins empty is fine.
            )
            logger.info("Allowed Host headers: %s", ", ".join(allowed_hosts))

        logger.info(
            "Starting HVAC MCP server on HTTP %s:%d (streamable-http, stateless)",
            args.host,
            args.port,
        )
        mcp.run(transport="streamable-http")
    else:
        logger.info("Starting HVAC MCP server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
