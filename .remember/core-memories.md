# hvac-mcp — core memories

This file is the persistent "where were we" record across Claude Code sessions. Read it at session start; update it when meaningful state changes.

## Who / why

- **Operator**: Kollin Croyle (kollinkiller4@ymail.com). EPA 608 Universal, 8+ years HVAC & plumbing in Florida.
- **Company**: `nightfast.tech` is Kollin's Apple app site — *separate* business. Do not pollute that brand with hvac-mcp.
- **hvac-mcp business**: vertical MCP server for HVAC/plumbing techs. Open core (MIT) + $29/mo hosted premium tier. One paying customer covers infra for a year.

## Current production stack (as of 2026-04-17)

| Piece | URL / ID | Host |
|---|---|---|
| Repo (public) | https://github.com/NightFast-app/hvac-mcp | GitHub |
| Landing + success page | https://nightfast-app.github.io/hvac-mcp/ | GitHub Pages |
| MCP API + webhook + /license/lookup | https://hvac-mcp.fly.dev | Fly.io `iad`, 256 MB, auto-suspend |
| SQLite license store | `/data/licenses.db` on Fly volume `hvac_mcp_data` | Fly volume, 1 GB |
| Stripe (both modes active) | acct_1R1ZVXIbaOFvY0LH | |
| Stripe live webhook endpoint | `we_1TNG4wIbaOFvY0LHQ8tDG6el` → `https://hvac-mcp.fly.dev/stripe/webhook` | |
| Stripe test webhook endpoint | `we_1TNFdpIbaOFvY0LHCcJsAQ4L` → same URL | |

Secrets live in Fly (`flyctl secrets list`):
- `STRIPE_WEBHOOK_SECRET` = `<test_whsec>,<live_whsec>` — multi-secret verifier tries each
- `HVAC_MCP_DATA_DIR=/data` — points SQLite at the volume
- `HVAC_MCP_HOST=0.0.0.0` — bind all interfaces
- `HVAC_MCP_ALLOWED_HOSTS=hvac-mcp.fly.dev` — DNS-rebinding protection whitelist

## Stripe live products (the real money ones)

| Tier | Product | Price | Payment Link |
|---|---|---|---|
| Starter $29/mo | `prod_ULy09YgGzrf834` | `price_1TNG4lIbaOFvY0LH7NCH8ilF` | https://buy.stripe.com/4gMeVd10BcSd4x57Q0gQE03 |
| Pro $79/mo | `prod_ULy0oudHc85SjF` | `price_1TNG4oIbaOFvY0LHKlnqUNAo` | https://buy.stripe.com/00wfZhbFf19ve7F0nygQE04 |
| Lifetime $399 | `prod_ULy0WtMXk8J5aX` | `price_1TNG4sIbaOFvY0LHPBONtxu5` | https://buy.stripe.com/dRmbJ18t3bO90gPb2cgQE05 |

`scripts/create_stripe_products.sh --live` is idempotent — matches on `metadata[tier]`, re-runs return `(reuse)` for all three tiers.

## Launch-day verified facts

- End-to-end customer flow tested via real browser purchase (2026-04-17 17:05 UTC). License `hvac_2NafdjiLOEDcXw9g5PEqGLbU` was issued on the live Fly volume from Kollin's own Stripe test purchase.
- Multi-secret verifier confirmed live on production (live whsec + test whsec + bogus → 200/200/400).
- Idempotency verified — same Stripe session id returns same license key on retry.
- CORS verified — `/license/lookup` accepts `nightfast-app.github.io` origin.
- 118 tests green in CI.

## Open todos (what's left for true launch)

1. **Revoke** the `rk_live_…` deploy token Kollin pasted on 2026-04-17. Was scoped to Products / Prices / Payment Links / Webhook Endpoints Write.
2. **PyPI publish** — blocked by 429 rate limit at pypi.org signup. When unblocked: register `hvac-mcp`, add `PYPI_API_TOKEN` secret, `git tag v0.1.1 && git push --tags`.
3. **Resend** for welcome emails — operator task: sign up, verify domain, paste `re_...` → `flyctl secrets set RESEND_API_KEY=...`.
4. **Vanity domain** — optional; shipping on `hvac-mcp.fly.dev`. `nightfast.tech` is OFF LIMITS (Apple-app brand).
5. **Demo GIF** — human task, 30 sec of actual field use.
6. **Reddit / marketing launch** — drafts in `docs/MARKETING_POSTS.md` ready.

## Lessons locked in (see `tasks/lessons.md` for details)

- **Float switch is always a top-tier "no cooling" cause** in humid climates. Regression test enforces it.
- **FastMCP `run()` doesn't accept port** — set `mcp.settings.host/port/stateless_http/json_response` before `run(transport="streamable-http")`. Transport string uses hyphen.
- **FastMCP streamable-http enforces DNS-rebinding protection by default** — must set `TransportSecuritySettings(allowed_hosts=[...])` for every hostname the server answers on.
- **Stripe CLI restricted key (rk_live_…) from `stripe login`** has narrow scopes — products/prices/webhook creation require a dashboard-generated scoped key.
- **Stripe CLI `--live` flag goes AFTER the subcommand**, not before: `stripe products list --live` ✓, `stripe --live products list` ✗.

## How to resume work

- Read `CLAUDE.md` (current state at top)
- Read `tasks/todo.md` (active plan)
- Read `tasks/lessons.md` (don't re-hit the same wall)
- Run `/verify` skill to confirm gates are green
- If deploying: follow `docs/DEPLOY_RUNBOOK.md`
