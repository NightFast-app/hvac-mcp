---
name: inspect
description: Launch the MCP Inspector against the local hvac_mcp server for interactive tool testing. Satisfies the Phase 2 verification gate "MCP Inspector handshake."
---

# inspect — MCP Inspector handshake

Launches the official Model Context Protocol inspector against the local server so you can exercise tools interactively in a browser UI.

## Command
```bash
npx -y @modelcontextprotocol/inspector uv run python -m hvac_mcp.server
```

## Use when
- Closing Phase 2 verification ("MCP Inspector handshake" gate).
- Debugging a tool's schema — inspector shows exact JSON the server publishes.
- Testing error responses without wiring Claude Desktop.

## Notes
- The inspector runs on localhost, no data leaves the machine.
- Close the browser tab when done; ctrl-C kills the server process.
- If it hangs on startup, check that stdio isn't being consumed by another process.
