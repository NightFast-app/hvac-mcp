# HVAC MCP — Build Plan

## Phase 0 — Repo bootstrap (Day 1, ~2 hrs)
- [ ] `uv init` the project, confirm `pyproject.toml` deps resolve
- [ ] Add `fastmcp`, `pydantic>=2`, `httpx`, `pytest`, `pytest-asyncio`, `ruff` to deps
- [ ] `.env.example` with `HVAC_MCP_LICENSE_KEY=`, `STRIPE_SECRET=`, `LOG_LEVEL=INFO`
- [ ] Empty server.py that boots with `FastMCP("hvac_mcp")` and prints tool count on `--help`
- [ ] Commit: "chore: initial scaffold"
- [ ] Push to github.com/cybertec44/hvac-mcp, public, MIT

## Phase 1 — Free-tier tools (Day 1–3)
### Tool 1: hvac_refrigerant_pt_lookup ✅
- [x] Hand-curated JSON PT tables for R-410A, R-32, R-454B, R-22, R-134a in `src/hvac_mcp/data/pt_tables.json`
- [x] Pydantic input: `refrigerant: RefrigerantEnum`, `pressure_psig: float | None`, `temp_f: float | None`, one-of validator
- [x] Tool returns saturation temp/pressure pair + note about glide for zeotropic blends (bubble+dew for R-454B)
- [x] Test: known values (R-410A 40°F↔118.5 psig, R-22 40°F↔68.5 psig, R-454B glide ~3.5 psi at 40°F) — 15 tests green

### Tool 2: hvac_refrigerant_charge_check ✅
- [x] Input: refrigerant, suction_p, suction_t, liquid_p, liquid_t, metering (TXV|piston), optional target_superheat_f
- [x] Calc superheat = suction_t − sat_t(suction_p, dew); subcool = sat_t(liquid_p, bubble) − liquid_t
- [x] Diagnosis rules: TXV → subcool 8-12°F window, restriction-suspected on high SH + normal SC; piston → ±3°F of target (default 15°F)
- [x] Test: in-spec, undercharged, overcharged, restriction-suspected, piston in-spec, piston undercharged, impossible-reading guard — 7 tests green

### Tool 3: hvac_diagnostic_symptom_tree ✅
- [x] YAML-backed decision tree in `data/symptoms.yaml` (system_type → symptom → [probable_causes with test + fix])
- [x] Seeded 13 symptoms across split_ac, heat_pump, furnace, mini_split (covers no cool, ice, breaker trips, short cycle, compressor hum, water leak, no heat HP, aux heat, no ignition, rollout, mini-split error codes, comm errors)
- [x] Tool returns ranked causes with test + fix + probability, plus suggestions on no-match
- [x] Operator correction captured: float switch is always a top-tier no-cool cause (lessons.md 2026-04-17) — regression test enforces it

### Tool 4: hvac_fault_code_lookup ✅
- [x] `data/fault_codes.json` — seeded: Carrier (13/14/33/34), Trane (2/3/4 flash), Goodman (E1/E2/E6), Lennox (E200/E201/E223), Rheem (57/93), York (44/88), Mitsubishi (E0/E5/P4), Daikin (A1/A3/U4)
- [x] Every entry cites OEM service manual source
- [x] Tool: brand (with alias matching — Bryant→Carrier, Ruud→Rheem, etc.) + code (case/whitespace normalized) → meaning, causes, fix
- [x] 10 tests covering exact match, aliases, case-insensitive, whitespace, unknown code, unknown brand, schema integrity — all green (47 total now)

### Tool 5: hvac_code_lookup ✅
- [x] `data/code_snippets.json` — 14 entries: IMC 304/306/307/401-403/501/602-603, IRC M1411/M1502, IPC 604/709/906, FBC-M HVHZ, FBC-M outdoor anchor, FBC-P condensate (FL amendments)
- [x] Tool: keyword-score ranking (keyword hits 2x weighted), jurisdiction filter (FL = FL+national, national = national-only)
- [x] Disclaimer + source citation + edition year in every response; "AHJ" verification string always present
- [x] 13 tests: input validation, schema integrity, ranking, jurisdiction filtering, disclaimer enforcement — all green (61 total now)

### Tool 6: hvac_pipe_size ✅
- [x] IPC Table 710.1 (DWV horizontal branch) + simplified Hunter's-curve lookup for water supply
- [x] Input: fixture_units (DFU or WSFU), material (PVC|CPVC|copper|PEX|cast_iron), application (DWV|supply)
- [x] Material/application validator rejects illegal combos (PEX in DWV, PVC in supply, cast iron in supply)
- [x] PEX supply recommendations step up one nominal size vs copper (smaller effective ID)
- [x] Water closet 3" minimum note surfaces when DFU suggests smaller
- [x] Output includes code ref, notes, AHJ disclaimer
- [x] 16 tests — input validation, DWV ladder, supply Hunter's, PEX bump, out-of-range — all green (77 total now)

### Tool 7: hvac_duct_size ✅
- [x] Friction-rate method. Input: CFM, friction_rate (default 0.08 in.wc/100ft), duct_shape (round|rectangular)
- [x] ASHRAE friction chart equation: D = (0.109136·Q^1.9 / f)^(1/5.02); velocity V = Q/A
- [x] Huebscher equation for round-to-rectangular equivalence, bisection solver for width given joist-friendly heights (6, 8, 10, 12, 14 in)
- [x] Output: equivalent round + up to 3 rectangular options, velocity with high/low warnings, aggressive-friction warning
- [x] Cites ACCA Manual D and ASHRAE friction chart in source/disclaimer
- [x] 12 tests covering math accuracy, Huebscher round-trip consistency, warnings, input validation — all green (89 total)

## Phase 2 — Infra & transport (Day 3)
- [x] stdio transport works end-to-end (JSON-RPC initialize + tools/list + tools/call verified in-session)
- [x] streamable HTTP mode boots on :8000 with `--http` flag — fixed FastMCP API (transport="streamable-http", settings on mcp.settings), stateless_http + json_response enabled, 0.0.0.0 bind, honors PORT env var. Tested end-to-end via curl initialize/tools/list.
- [x] GitHub Actions: ruff + pytest + boot on 3.11/3.12 (`.github/workflows/ci.yml`)
- [ ] Dockerfile for Railway deploy (operator step — see docs/LAUNCH_CHECKLIST.md §4)
- [ ] railway.toml with env vars (operator step — PORT and HVAC_MCP_HOST already honored in code)

## Phase 3 — Premium tier skeleton (Day 4–5)
- [ ] `licensing.py` — verifies license key against Stripe customer metadata or local dev allow-list
- [ ] `@require_license` decorator on premium tools; returns actionable error with purchase URL when missing
- [ ] Stub `hvac_invoice_draft` with simple markdown template (no PDF yet — v1.1)
- [ ] Stripe payment link created, saved to `docs/PRICING.md`

## Phase 4 — Launch prep (Day 5–6)
- [ ] `docs/CONNECTING.md` — copy-paste config for Claude Desktop, Claude Code CLI, ChatGPT custom connectors, Cursor
- [ ] Record 30-second Loom: techs using it on a phone via Claude app
- [ ] README with: badges, install, one-line demo, tool catalog, license, pricing
- [ ] Publish to PyPI as `hvac-mcp`
- [ ] Landing page at hvac-mcp.nightfast.tech — plain HTML, Stripe Checkout button, connector URL reveal after purchase

## Phase 5 — Distribution (Day 7+)
- [ ] Post in r/HVAC, r/Plumbing, r/hvacadvice (don't sell — share the free tool)
- [ ] Post in r/mcp and r/ClaudeAI showing "first vertical MCP for a real trade"
- [ ] Submit to awesome-mcp-servers lists on GitHub
- [ ] DM 10 HVAC YouTubers with a free license + the ask: if useful, mention it
- [ ] Cross-post to FieldPulse / ServiceTitan / Jobber Facebook groups (value-first post, not pitch)

## Verification gates (don't mark Phase N done until all pass)
- Server boots: `uv run python -m hvac_mcp.server --help`
- MCP Inspector handshake: `npx @modelcontextprotocol/inspector uv run python -m hvac_mcp.server`
- All tests green: `uv run pytest -v`
- Lint clean: `uv run ruff check . && uv run ruff format --check .`
- Real tool call via Claude Desktop succeeds end-to-end

## Review section (filled in at the end of each phase)
_To be populated as phases complete._
