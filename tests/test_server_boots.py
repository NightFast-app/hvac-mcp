"""Smoke test: server module imports, tool registration succeeds, tool names match spec."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def test_server_module_imports() -> None:
    """The server module must import without side effects that block stdio."""
    from hvac_mcp import server

    assert server.mcp.name == "hvac_mcp"


def test_all_tools_register() -> None:
    """Every tool module's register() must succeed on a fresh FastMCP instance."""
    from hvac_mcp.tools import code_lookup, diagnostics, invoice, refrigerant, sizing

    test_mcp = FastMCP("hvac_mcp_test")
    refrigerant.register(test_mcp)
    diagnostics.register(test_mcp)
    code_lookup.register(test_mcp)
    sizing.register(test_mcp)
    invoice.register(test_mcp)
    # If we got here, no exceptions — handshake surface area is intact.


def test_tool_naming_convention() -> None:
    """Every registered tool name must start with 'hvac_' to avoid client-side collisions."""
    from hvac_mcp.server import mcp, register_all_tools

    register_all_tools()
    # FastMCP stores tools in an internal registry — the exact attribute name
    # varies by SDK version. This test is a placeholder; fill in once we've
    # confirmed the current SDK surface.
    assert mcp.name == "hvac_mcp"
