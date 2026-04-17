# hvac-mcp

> The first Model Context Protocol server built by an HVAC tech, for HVAC techs.

Turn Claude, ChatGPT, Cursor, or any MCP-compatible client into a field-service-aware assistant. Free, open-source, MIT.

[![CI](https://github.com/NightFast-app/hvac-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/NightFast-app/hvac-mcp/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## What this is

A vertical MCP server exposing trade-specific tools — refrigerant PT lookup, superheat/subcool diagnosis, fault-code decoding, code citations, pipe & duct sizing — that a working tech actually needs on a call.

Built and maintained by Kollin Croyle (EPA 608 Universal, 8+ years in the field).

## Quick start

Install directly from GitHub with [uv](https://docs.astral.sh/uv/) (recommended — no PyPI account or pip needed):

```bash
uvx --from git+https://github.com/NightFast-app/hvac-mcp hvac-mcp --help
```

Or clone and run with `uv`:

```bash
git clone https://github.com/NightFast-app/hvac-mcp.git
cd hvac-mcp
uv run python -m hvac_mcp.server --help
```

PyPI release coming soon — once it's up, `uvx hvac-mcp` will work with no URL.

Point your MCP client at it — see [docs/CONNECTING.md](docs/CONNECTING.md) for Claude Desktop, Claude Code, the Claude mobile app, ChatGPT, and Cursor configs.

## Free tier (open source)

| Tool | What it does |
|---|---|
| `hvac_refrigerant_pt_lookup` | PT saturation for R-410A, R-32, R-454B, R-22, R-134a |
| `hvac_refrigerant_charge_check` | Superheat/subcool + diagnosis (TXV vs piston) |
| `hvac_diagnostic_symptom_tree` | Ranked probable causes for a reported symptom |
| `hvac_fault_code_lookup` | Carrier, Trane, Goodman, Lennox, Rheem, York, Mitsubishi, Daikin |
| `hvac_code_lookup` | IRC/IMC/IPC + FL amendments, with AHJ disclaimer |
| `hvac_pipe_size` | DWV (IPC Table 709.1) and supply (Hunter's curve) |
| `hvac_duct_size` | Friction-rate method (ACCA Manual D basis) |

See [docs/TOOL_CATALOG.md](docs/TOOL_CATALOG.md) for inputs, outputs, and example calls.

## Hosted / Premium tier

No install, no configuration. Plug a URL into your MCP client and go.

- **Starter — $29/mo** — free tools + invoice drafting, estimate generation, parts cross-reference
- **Pro — $79/mo** — everything in Starter + Florida county permit lookup
- **Lifetime — $399 one-time** — first 50 customers only

👉 [hvac-mcp.nightfast.tech](https://hvac-mcp.nightfast.tech)

## Disclaimer

Code and sizing outputs are **informational only**. Always verify with the Authority Having Jurisdiction (AHJ) before acting on them for permit or installation decisions. This tool doesn't replace your license, your engineer, or your common sense.

## License

MIT. Do whatever you want with the code. Credit is appreciated, not required.

## Contributing

PRs welcome, especially for:
- Additional refrigerants (R-290, R-600a, R-1234yf, R-448A, R-449A)
- Regional code amendments beyond Florida
- New brand fault code datasets
- Bug reports from real field use (the best kind)

Open an issue first if you're adding a new tool so we can talk through scope.
