# HVAC MCP Server

## Current state (2026-04-17, post-launch)

**v1 is shipped and taking live payments.** 118 tests, CI green.

- **Repo**: https://github.com/NightFast-app/hvac-mcp (public, MIT)
- **Landing page**: https://nightfast-app.github.io/hvac-mcp/
- **API (production)**: https://hvac-mcp.fly.dev
  - Deployed on Fly.io (`iad`, 256 MB, auto-suspend on idle)
  - `/data` SQLite volume for the license store
  - Health: `/health` → 200 OK
  - MCP: `/mcp` (streamable HTTP, stateless, JSON responses)
  - Webhook: `/stripe/webhook` (multi-secret verifier; test + live both active)
  - Customer self-serve: `/license/lookup?session_id=…`
- **Payments**: Stripe **live mode** wired end-to-end
  - Starter $29/mo, Pro $79/mo, Lifetime $399 one-time
  - Payment Links redirect to `landing/success.html` which auto-polls `/license/lookup`
  - Premium gating enforced in `is_licensed()` against the SQLite store
- **No custom domain yet** — shipping on `hvac-mcp.fly.dev`. `nightfast.tech` is Kollin's Apple-app site and stays untouched. Vanity domain (e.g. `hvac-mcp.app`) is a future nice-to-have.
- **No welcome email yet** — keys appear on the success page and are logged on Fly. Wiring Resend is a 15-min task when Kollin has an API key.

The live deploy runbook: [`docs/DEPLOY_RUNBOOK.md`](docs/DEPLOY_RUNBOOK.md).

## What this is

A vertical Model Context Protocol server for HVAC and plumbing technicians. Exposes domain tools so any MCP client (Claude Desktop, Claude Code, ChatGPT connectors, Cursor) becomes a field-service-aware assistant. The operator is Kollin Croyle, EPA 608 Universal, 8+ years in the trades.

## Business model

- **Open core** on GitHub (MIT) — drives stars, SEO, Reddit credibility.
- **Hosted tier** at `https://hvac-mcp.fly.dev/mcp` — $29/mo per user via Stripe + license keys. Open tools are free; premium tools (invoice drafting, parts cross-ref, permit lookup) gated behind a license check.
- Target buyer: solo / 2-5 tech HVAC+plumbing shops already using ChatGPT on phones.

## Non-negotiable principles (from operator preferences)

1. **Plan first.** Update `tasks/todo.md` before writing code. Verify the plan before implementing.
2. **Simplicity first.** Minimum surface area to solve the problem.
3. **No lazy fixes.** Find root causes. Senior standards.
4. **Verify before done.** Every tool has a test; server must boot and respond to MCP Inspector.
5. **Update `tasks/lessons.md` after any correction.** Prevent the same mistake twice.
6. **Subagents for research.** Keep main context clean.

## Repository layout (current)

```
hvac_mcp/
├── CLAUDE.md                    # This file — Claude Code reads it on startup
├── README.md                    # Public-facing, GitHub landing
├── LICENSE                      # MIT
├── pyproject.toml               # deps: mcp[cli], pydantic, httpx, pyyaml, stripe
├── .python-version              # 3.11
├── .env.example                 # Env var template (never commit real .env)
├── Dockerfile                   # Slim py3.11, runs `hvac-mcp --http`
├── .dockerignore
├── fly.toml                     # Fly.io deploy config (iad, 256MB, /data volume)
├── railway.toml                 # Alternate deploy target (unused; kept for option B)
├── .mcp.json                    # context7 MCP shared w/ team
├── src/hvac_mcp/
│   ├── __init__.py
│   ├── server.py                # FastMCP entrypoint, tool + custom-route registration
│   ├── licensing.py             # is_licensed() / require_license / @premium
│   ├── storage.py               # SQLite LicenseStore (licenses.db)
│   ├── webhook.py               # Stripe webhook + /license/lookup + /health + Resend email
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── refrigerant.py       # PT charts, charge calcs
│   │   ├── diagnostics.py       # Symptom tree + fault code lookup (2 tools)
│   │   ├── code_lookup.py       # IRC/IMC/IPC + FL amendments
│   │   ├── sizing.py            # pipe_size + duct_size (2 tools)
│   │   └── invoice.py           # Premium: hvac_invoice_draft
│   ├── data/                    # Static reference data
│   │   ├── pt_tables.json       # 5 refrigerants, bubble+dew for blends
│   │   ├── symptoms.yaml        # 13 symptoms across 4 system types
│   │   ├── fault_codes.json     # 8 brands, 25 codes, alias-aware
│   │   ├── code_snippets.json   # 14 IRC/IMC/IPC + FL entries
│   │   └── pipe_sizing.json     # DWV + supply ladders
│   └── utils/
│       ├── api.py               # (placeholder) Shared httpx client
│       └── formatting.py        # Markdown/JSON response helpers
├── tests/                       # 118 tests, 100% pass
│   ├── test_refrigerant.py      # 22 tests
│   ├── test_diagnostics.py      # 22 tests (symptom + fault code)
│   ├── test_code_lookup.py      # 14 tests
│   ├── test_sizing.py           # 28 tests (pipe + duct)
│   ├── test_storage_and_webhook.py  # 30 tests (license store + Stripe)
│   └── test_server_boots.py
├── tasks/
│   ├── todo.md                  # Live plan, checkable items
│   └── lessons.md               # Patterns learned from corrections
├── docs/
│   ├── CONNECTING.md            # Claude Desktop, Claude Code, mobile, ChatGPT, Cursor
│   ├── TOOL_CATALOG.md          # Every tool, inputs, sample output
│   ├── DEPLOY_RUNBOOK.md        # Fly.io + Cloudflare + Stripe + Resend runbook
│   ├── STRIPE_LINKS.md          # Source of truth for live+test Stripe objects
│   ├── LAUNCH_CHECKLIST.md
│   ├── MARKETING_POSTS.md       # r/HVAC, r/mcp, r/ClaudeAI, FB group drafts
│   ├── stripe-links.live.json   # Machine-readable live product/price/link IDs
│   └── stripe-links.test.json   # Same for test mode
├── landing/
│   ├── index.html               # Single-page site on GitHub Pages
│   ├── success.html             # Post-checkout page — polls /license/lookup
│   └── README.md                # How to deploy (already auto-deploys via CI)
├── scripts/
│   └── create_stripe_products.sh  # Idempotent Stripe provisioning (test/live)
├── .claude/                     # Project-local Claude Code config
│   ├── settings.json            # Hooks (auto-ruff, guard_data)
│   ├── agents/hvac-data-verifier.md
│   ├── hooks/auto_ruff.sh, guard_data.sh
│   └── skills/verify/, add-tool/, inspect/
└── .github/workflows/
    ├── ci.yml                   # Ruff + pytest + boot on py3.11/3.12
    ├── release.yml              # Tag push → build + publish to PyPI
    └── pages.yml                # Auto-deploy landing page
```

## Tool catalog (shipped)

Tools are `{service}_{action}` — always prefixed `hvac_` so they don't collide with other MCPs the user has loaded.

### Free tier (open source) — 8 tools

- `hvac_refrigerant_pt_lookup` — R-410A, R-32, R-454B, R-22, R-134a with bubble+dew for zeotropic blends.
- `hvac_refrigerant_charge_check` — TXV / piston diagnosis with restriction detection.
- `hvac_diagnostic_symptom_tree` — 13 seeded symptoms across 4 system types. Float-switch regression-locked.
- `hvac_fault_code_lookup` — Carrier / Bryant, Trane, Goodman, Lennox, Rheem / Ruud, York, Mitsubishi, Daikin — alias-aware.
- `hvac_code_lookup` — IRC / IMC / IPC + FL amendments (HVHZ, condensate, wind anchor). AHJ disclaimer hard-coded.
- `hvac_pipe_size` — DWV (IPC Table 710.1) + supply (Hunter's). Rejects illegal material combos at input layer.
- `hvac_duct_size` — ASHRAE friction chart + Huebscher round-to-rect. Velocity warnings.
- `hvac_capacitor_crossref` — substitution verdict (ok / marginal / no_go) + suggestions from stocked sizes. Run / start / dual-run. ±6% run tolerance, ±20% start, voltage ≥ spec rule enforced.

### Premium tier (license key required) — 2 live, 2 stubs

- `hvac_invoice_draft` ✅ formatted invoice with parts + labor + tax.
- `hvac_quote_from_diagnosis` ✅ customer-ready quote with FL defaults ($120/hr, 50% markup, 6.5% parts-only tax), minimum-charge floor, SMS-safe plain-text variant.
- `hvac_estimate_from_symptom` — stub for v1.1.
- `hvac_permit_lookup_fl` — stub for v1.1.

## Stack

- Python 3.11+
- FastMCP (MCP Python SDK high-level API)
- Pydantic v2 for all inputs, `ConfigDict(extra="forbid")` everywhere
- httpx (async) for Resend + any outbound HTTP
- `stripe` SDK for webhook signature verification
- SQLite (stdlib) for the license store — no SQLAlchemy
- pytest + pytest-asyncio
- Ruff for lint/format
- uv for deps
- Fly.io (Docker) for the hosted tier

## Transport

- **Local / stdio**: `uvx --from git+https://github.com/NightFast-app/hvac-mcp hvac-mcp` (PyPI release pending)
- **Hosted / streamable HTTP**: `https://hvac-mcp.fly.dev/mcp` — stateless JSON, multi-tenant via Bearer-style license keys

## Licensing check pattern

- `is_licensed()` reads `HVAC_MCP_LICENSE_KEY` env var, checks the SQLite store for an active row
- `@premium` decorator on tool fns returns a structured `license_required` error if absent — never silently succeeds
- Dev allow-list (`DEV-LOCAL-KEY-DO-NOT-SHIP`) bypasses the store for local testing

## Security / data boundaries

- No PII storage beyond Stripe customer ID + issued-at timestamp
- Free-tier tools make zero external network calls — all reference data is bundled JSON/YAML
- Stripe webhook signature verified on every POST via comma-separated multi-secret list
- `/license/lookup` returns CORS headers so the GitHub Pages success page can fetch cross-origin
- FastMCP `transport_security` restricts the Host header to an explicit allowlist (currently `hvac-mcp.fly.dev`)

## How to work in this repo (for Claude Code)

1. Read `tasks/todo.md`. If a task is in progress, continue it. If all clear, pick the next unchecked item.
2. Before writing code, reply with your plan and wait for operator approval.
3. When making changes: touch only what's necessary. No drive-by refactors.
4. After any correction from the operator, append the lesson to `tasks/lessons.md` with a one-line rule.
5. Every tool needs: Pydantic input model, docstring, `annotations` block in `@mcp.tool`, and a test in `tests/`.
6. Run before handing off: `uv run --no-project --with-editable . --with ruff --with pytest --with pytest-asyncio --with pyyaml --with stripe bash -c "ruff check src/ tests/ && pytest -q"` (or use the `/verify` skill).
7. Use subagents for: researching API schemas, scraping reference data, writing long test suites, auditing bundled reference data (`hvac-data-verifier` agent).

## Shipped v1 definition

- [x] All 7 free-tier tools implemented with tests passing. **(118 tests green)**
- [x] `uvx --from git+…hvac-mcp` runs the server over stdio locally. **(PyPI pending 429 unblock)**
- [x] Streamable HTTP mode boots with `hvac-mcp --http`, deployed live to Fly.
- [x] `docs/CONNECTING.md` shows copy-paste config for Claude Desktop, Claude Code, Claude app, ChatGPT, Cursor.
- [x] Repo published to GitHub, public, MIT.
- [x] Landing page live (GitHub Pages).
- [x] Stripe live-mode Payment Links wired to the landing page with post-checkout redirect.
- [x] Webhook signature verification + license issuance end-to-end on production.
- [x] Premium gating (`is_licensed()` against SQLite store).
- [ ] PyPI package live — blocked on rate limit (429) at registration. `uvx --from git+…` works as workaround.
- [ ] 30-second demo GIF — needs human to record.
- [ ] Welcome email via Resend — wired in code, needs API key.
- [ ] Vanity domain — optional; `hvac-mcp.fly.dev` works today.

## What is explicitly out of scope for v1

- Mobile app wrapper (ship MCP first, app is v2).
- Complex Manual J / Manual D full load calcs (hvac_sizing stays simple).
- QuickBooks OAuth (premium v2 — OAuth review is a multi-week drag).
- User accounts / web dashboard (Stripe + license key is enough).
