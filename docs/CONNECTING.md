# Connecting hvac-mcp to your MCP client

Five clients, five copy-paste blocks. Pick yours.

> **Installing via `uvx`**: the repo is currently installed **directly from GitHub** (PyPI release coming soon). Every config below uses `uvx --from git+https://github.com/NightFast-app/hvac-mcp hvac-mcp` — first run clones + caches the repo (~10 seconds), every run after is instant.
>
> Prerequisite: install [uv](https://docs.astral.sh/uv/) once —
> ```bash
> curl -LsSf https://astral.sh/uv/install.sh | sh
> ```
>
> When PyPI goes live, you'll be able to shorten every command to just `uvx hvac-mcp`.

---

## 1. Claude Desktop (macOS / Windows)

Edit the config at:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "hvac": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/NightFast-app/hvac-mcp",
        "hvac-mcp"
      ],
      "env": {
        "HVAC_MCP_LICENSE_KEY": ""
      }
    }
  }
}
```

Leave `HVAC_MCP_LICENSE_KEY` blank for free-tier-only. Drop in your key from [hvac-mcp.nightfast.tech](https://hvac-mcp.nightfast.tech) for premium tools.

Restart Claude Desktop. You'll see the 🔌 hammer icon in the chat — click it, you should see seven `hvac_*` tools.

---

## 2. Claude Code (CLI)

```bash
claude mcp add hvac -- uvx --from git+https://github.com/NightFast-app/hvac-mcp hvac-mcp
```

Then set your license key in the environment if you have one:

```bash
export HVAC_MCP_LICENSE_KEY="your-key-here"
```

Verify:

```bash
claude mcp list
```

---

## 3. Claude mobile app (iOS / Android)

Claude's mobile app supports **hosted MCP connectors** — no install needed on your phone.

1. Buy a license at [hvac-mcp.nightfast.tech](https://hvac-mcp.nightfast.tech). You'll receive a connector URL and key by email.
2. In the Claude app, go to **Settings → Connectors → Add custom connector**.
3. Paste your URL (looks like `https://hvac-mcp.nightfast.tech/mcp`).
4. Add header: `Authorization: Bearer <your-license-key>`.
5. Save. The HVAC tools will be available in any chat.

---

## 4. ChatGPT (Custom Connectors)

ChatGPT Plus/Team/Enterprise supports custom MCP connectors on web and desktop.

1. Go to **Settings → Connectors → + Create**.
2. Paste the hosted URL: `https://hvac-mcp.nightfast.tech/mcp`.
3. Under Authentication, choose **Bearer token** and paste your license key.
4. Save and enable for relevant chats.

---

## 5. Cursor

Edit `~/.cursor/mcp.json` (create it if missing):

```json
{
  "mcpServers": {
    "hvac": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/NightFast-app/hvac-mcp",
        "hvac-mcp"
      ],
      "env": {
        "HVAC_MCP_LICENSE_KEY": ""
      }
    }
  }
}
```

Restart Cursor. Open the MCP panel to confirm the tools loaded.

---

## Troubleshooting

**`uvx: command not found`** — install [uv](https://docs.astral.sh/uv/) first: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

**"Server didn't respond"** — run this in your terminal and confirm it prints a usage message:
```bash
uvx --from git+https://github.com/NightFast-app/hvac-mcp hvac-mcp --help
```
If that works but your client fails, the issue is client config, not the server.

**First run is slow** — `uvx --from git+…` clones the repo once and caches it. Subsequent runs are instant. If you want to pre-warm the cache: run the `--help` command above once before you open your MCP client.

**Pinning to a specific version** — add `@v0.1.0` to the URL: `git+https://github.com/NightFast-app/hvac-mcp@v0.1.0`. Prevents unexpected updates when you restart your client.

**Premium tool says "license_required"** — double-check the key is set in the same environment the MCP server runs in. For Claude Desktop, the `env` block in the JSON config is how it gets passed.

**Want to self-host the hosted tier?** The repo is MIT. Clone it, deploy to your own Railway / Fly / Docker host, run with `hvac-mcp --http --port 8000`, and point your clients at your domain.
