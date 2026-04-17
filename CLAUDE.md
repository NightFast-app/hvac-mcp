# HVAC MCP Server

## What this is
A vertical Model Context Protocol server for HVAC and plumbing technicians. Exposes domain tools so any MCP client (Claude Desktop, Claude Code, ChatGPT connectors, Cursor) becomes a field-service-aware assistant. The operator is Kollin Croyle, EPA 608 Universal, 8+ years in the trades.

## Business model
- **Open core** on GitHub (MIT) — drives stars, SEO, Reddit credibility.
- **Hosted tier** at `https://hvac-mcp.nightfast.tech/mcp` — $29/mo per user via Stripe + ExtensionPay-style license keys. Open tools are free; premium tools (QuickBooks sync, PDF invoice gen, dispatch) gated behind a license check header.
- Target buyer: solo/2-5 tech HVAC+plumbing shops already using ChatGPT on phones.

## Non-negotiable principles (from operator preferences)
1. **Plan first.** Update `tasks/todo.md` before writing code. Verify the plan before implementing.
2. **Simplicity first.** Minimum surface area to solve the problem.
3. **No lazy fixes.** Find root causes. Senior standards.
4. **Verify before done.** Every tool has a test; server must boot and respond to MCP Inspector.
5. **Update `tasks/lessons.md` after any correction.** Prevent the same mistake twice.
6. **Subagents for research.** Keep main context clean.

## Repository layout
```
hvac_mcp/
├── CLAUDE.md                    # This file — Claude Code reads it on startup
├── README.md                    # Public-facing, GitHub landing
├── LICENSE                      # MIT
├── pyproject.toml               # uv / pip install target
├── .python-version              # 3.11
├── .env.example                 # Env var template (never commit real .env)
├── src/hvac_mcp/
│   ├── __init__.py
│   ├── server.py                # FastMCP entrypoint, tool registration
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── refrigerant.py       # PT charts, charge calcs, 608 lookup
│   │   ├── diagnostics.py       # Fault code lookup, symptom tree
│   │   ├── code_lookup.py       # IRC/IMC/IPC + FL-specific
│   │   ├── sizing.py            # Manual J light, pipe/duct sizing
│   │   ├── invoice.py           # (premium) Invoice/estimate draft
│   │   └── parts.py             # Part number cross-reference
│   ├── data/                    # Static reference data (PT tables, code snippets)
│   ├── licensing.py             # License key check for premium tools
│   └── utils/
│       ├── api.py               # Shared httpx client + error handler
│       └── formatting.py        # Markdown/JSON response helpers
├── tests/
│   ├── test_refrigerant.py
│   ├── test_diagnostics.py
│   └── test_server_boots.py
├── tasks/
│   ├── todo.md                  # Live plan, checkable items
│   └── lessons.md               # Patterns learned from corrections
├── docs/
│   ├── CONNECTING.md            # How to add this MCP to Claude Desktop / Code / ChatGPT
│   └── TOOL_CATALOG.md          # Every tool, its inputs, sample output
└── .github/workflows/
    └── ci.yml                   # Ruff + pytest + build check
```

## Tool catalog (v1 scope)
Tools are `{service}_{action}` — always prefixed `hvac_` so they don't collide with other MCPs the user has loaded.

### Free tier (open source)
- `hvac_refrigerant_pt_lookup` — Pressure/temp saturation for R-410A, R-32, R-454B, R-22, R-134a. Input: refrigerant + (pressure OR temp). Output: saturation pair + subcool/superheat hints.
- `hvac_refrigerant_charge_check` — Input: refrigerant, suction P, suction T, liquid P, liquid T, metering type (TXV/piston). Output: superheat, subcool, diagnosis (undercharged/overcharged/restriction).
- `hvac_diagnostic_symptom_tree` — Input: system type (split AC, heat pump, furnace, mini-split), symptom. Output: ranked probable causes with test procedure.
- `hvac_fault_code_lookup` — Input: brand (Carrier/Trane/Goodman/Lennox/Rheem/York/Mitsubishi/Daikin), code. Output: meaning, causes, fix.
- `hvac_code_lookup` — Input: topic, jurisdiction (default: Florida). Output: applicable IRC/IMC/IPC + FL amendment citation. Read-only, static dataset.
- `hvac_pipe_size` — Quick DWV and water supply sizing per IPC tables. Input: fixture units, material. Output: pipe size.
- `hvac_duct_size` — Friction-rate duct sizing. Input: CFM, friction rate, duct type. Output: round + rectangular equivalents.

### Premium tier (license key required)
- `hvac_invoice_draft` — Input: customer, job description, parts used, labor hours, tax rate. Output: formatted invoice markdown + PDF bytes (base64).
- `hvac_estimate_from_symptom` — Combines diagnostic + local labor rate + parts DB to spit out a customer-facing estimate.
- `hvac_parts_crossref` — OEM part → aftermarket equivalents, pricing from SupplyHouse/Grainger.
- `hvac_permit_lookup_fl` — Query FL county permit systems (Lee, Collier, Charlotte — home-turf first).

## Stack
- Python 3.11+
- FastMCP (MCP Python SDK high-level API)
- Pydantic v2 for all inputs
- httpx (async) for any HTTP calls
- pytest + pytest-asyncio for tests
- Ruff for lint/format
- uv for dependency management (faster than pip, handles lockfiles cleanly)

## Transport
- **Local dev / Claude Desktop**: stdio transport — user installs `uvx hvac-mcp` and points their config at it.
- **Hosted SaaS**: streamable HTTP on Railway/Fly, gated by `Authorization: Bearer <license_key>` header. Stateless JSON only.

## Licensing check pattern
Premium tools import `require_license` from `licensing.py`. If no/invalid key present in the request context, return an actionable error pointing to the purchase URL. Never silently no-op.

## Security / data boundaries
- No PII storage. License key → Stripe customer ID lookup only.
- Code lookups are static JSON bundled in the package; no external calls for free-tier tools.
- Every external API call uses the shared httpx client with a 10s timeout and `_handle_api_error`.

## How to work in this repo (for Claude Code)
1. Read `tasks/todo.md`. If a task is in progress, continue it. If all clear, pick the next unchecked item.
2. Before writing code, reply with your plan and wait for operator approval.
3. When making changes: touch only what's necessary. No drive-by refactors.
4. After any correction from the operator, append the lesson to `tasks/lessons.md` with a one-line rule.
5. Every tool needs: Pydantic input model, docstring, `annotations` block in `@mcp.tool`, and a test in `tests/`.
6. Run before handing off: `uv run ruff check . && uv run pytest && uv run python -m hvac_mcp.server --help`.
7. Use subagents for: researching API schemas, scraping reference data, writing long test suites.

## What "done" looks like for v1
- [ ] All 7 free-tier tools implemented with tests passing.
- [ ] `uvx hvac-mcp` runs the server over stdio locally.
- [ ] Streamable HTTP mode boots with `hvac-mcp --http --port 8000`.
- [ ] `docs/CONNECTING.md` shows copy-paste config for Claude Desktop, Claude Code, ChatGPT.
- [ ] README has a 30-second demo GIF.
- [ ] Repo published to GitHub, PyPI package live.
- [ ] Landing page at hvac-mcp.nightfast.tech with Stripe checkout.

## What is explicitly out of scope for v1
- Mobile app wrapper (ship MCP first, app is v2).
- Complex Manual J / Manual D full load calcs (hvac_sizing stays simple).
- QuickBooks OAuth (premium v2 — OAuth review is a multi-week drag).
- User accounts / web dashboard (Stripe + license key is enough).
