# HVAC MCP — Lessons Learned

This file grows whenever the operator corrects Claude Code. Each lesson is a one-line rule that prevents the same mistake. Review at session start.

## Seed rules (before any correction — baked in from operator preferences)

1. Never claim a task is complete without running `uv run pytest` and the MCP Inspector handshake.
2. Never refactor code that isn't on the current `tasks/todo.md` item. Minimal impact only.
3. Every new tool must have: Pydantic input model with `model_config`, `@mcp.tool(annotations={...})`, docstring with Args/Returns, and a test file.
4. PT-table / code-lookup data is bundled, not fetched — zero network calls in the free-tier hot path.
5. Premium tools must call `require_license(ctx)` on the first line of the function body. No exceptions.
6. When unsure about a refrigerant property or code citation, refuse to guess — return a structured "unknown, verify with manufacturer/AHJ" response.
7. Refrigerant blends (R-410A, R-454B, R-32) are near-azeotropic but have glide — output must indicate dew vs bubble point where relevant.
8. If a correction happens, append the rule here BEFORE continuing the task that caused it.

## Corrections log

## 2026-04-17 — FastMCP run() does not accept port kwarg; set via mcp.settings
- **Miss:** `server.py` called `mcp.run(transport="streamable_http", port=args.port)` which raised `TypeError: FastMCP.run() got an unexpected keyword argument 'port'`. Also used underscore transport name.
- **Rule:** With the modelcontextprotocol/python-sdk FastMCP API:
  - Transport string is **`"streamable-http"`** (hyphen), not `"streamable_http"`.
  - `run()` only accepts `transport` and `mount_path`. Configure host/port/stateless/json via `mcp.settings.host`, `mcp.settings.port`, `mcp.settings.stateless_http`, `mcp.settings.json_response` **before** calling `run()`.
  - For hosted deploys, set `stateless_http=True` and `json_response=True` (per SDK docs).
  - Bind `0.0.0.0` (not `127.0.0.1`) when running inside a container so Railway/Fly/Docker health checks can reach it.
- **Why it matters:** An HTTP transport that looks configured but never boots means the premium tier would silently fail to start. Always test `--http` end-to-end with a real `curl initialize` request, not just `--help`.

## 2026-04-17 — Float switch belongs in every "no cooling" tree
- **Miss:** Seeded split_ac "no cooling" symptom without listing the condensate safety / float switch as a probable cause.
- **Rule:** For any "no cooling with blower running" symptom on residential split systems, the float switch / clogged drain is a top-tier cause — must always appear. Especially true in humid climates (FL is operator's home turf). Also apply to heat_pump cooling-mode trees as they get seeded.
- **Why it matters:** Operator is EPA 608 Universal with 8 yrs in FL — drain backups from algae/biofilm are among the most common summer service calls. Missing this makes the tool look like it was written by someone who's never turned a wrench.
