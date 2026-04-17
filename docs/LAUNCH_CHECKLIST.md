# v1 Launch Checklist

Everything shippable-by-code is done. This file tracks the human-in-the-loop
steps that remain before a public launch.

## ✅ Already done (in-repo, CI-verified)

- All 7 free-tier tools implemented, tested, and handshake-verified over both
  stdio and streamable-http transports.
- 89 pytest cases, all green. Ruff check + format clean across repo.
- `docs/CONNECTING.md` — Claude Desktop, Claude Code, Claude mobile app,
  ChatGPT, and Cursor configs.
- `docs/TOOL_CATALOG.md` — every tool's inputs/outputs.
- `docs/PRD.docx` in repo.
- `.github/workflows/ci.yml` — ruff + pytest + boot on 3.11/3.12.
- Streamable HTTP transport with `stateless_http=True` + `json_response=True`
  for horizontal scalability; binds `0.0.0.0` by default for containers.
- `HVAC_MCP_HOST` and `PORT` env vars honored (Railway/Fly friendly).

## ☐ Operator-only (ordered by prerequisite chain)

### 1. Smoke-test locally on a real phone workflow (30 min)
- [ ] `claude mcp add hvac -- uv run python -m hvac_mcp.server` (while repo
      lives on disk; switches to `uvx hvac-mcp` once PyPI is live).
- [ ] From the Claude CLI, ask: "What's the saturation temp for R-410A at
      118 psig?" — confirm tool is invoked and answers 40°F.
- [ ] Test at least one tool from each category: refrigerant, diagnostic,
      code, sizing.

### 2. Publish to GitHub (15 min)
- [ ] Create repo `NightFast-app/hvac-mcp`, public, MIT license.
- [ ] `git init && git add -A && git commit -m "chore: v1 free tier shipping"`.
- [ ] `gh repo create NightFast-app/hvac-mcp --public --source . --push`.
- [ ] Confirm CI turns green on the first push.
- [ ] Tag release: `git tag v0.1.0 && git push --tags`.

### 3. Publish to PyPI (20 min)
- [ ] Register the name `hvac-mcp` on pypi.org.
- [ ] Create an API token scoped to the project.
- [ ] Add `PYPI_API_TOKEN` as a GitHub Actions secret.
- [ ] Add a `release.yml` workflow that runs on tag push and executes
      `uv build && uv publish` (template below).
- [ ] Push tag `v0.1.0` → verify `uvx hvac-mcp --help` works from a fresh
      machine within 5 min.

Release workflow template:

```yaml
name: Release

on:
  push:
    tags: ['v*']

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv build
      - env:
          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_API_TOKEN }}
        run: uv publish
```

### 4. Container + hosted tier (60 min)
- [ ] Write `Dockerfile` — `python:3.11-slim`, copy repo, `pip install -e .`,
      `CMD ["hvac-mcp", "--http"]`.
- [ ] Deploy to Railway (or Fly) pointing at the repo. Railway injects `PORT`
      — we already honor it.
- [ ] Smoke test: `curl https://hvac-mcp.nightfast.tech/mcp` with an
      `initialize` payload.

### 5. Landing page + Stripe (90 min)
- [ ] Plain HTML at `hvac-mcp.nightfast.tech` — tool catalog, pricing tiers,
      Stripe Checkout button.
- [ ] Stripe: create three products (Starter $29/mo, Pro $79/mo,
      Lifetime $399 one-time).
- [ ] Webhook → license key issuance (stub: generate a random key, email via
      Resend). Premium license check in `licensing.py` already expects a
      `Bearer <key>` header for HTTP or an env var for stdio.

### 6. Marketing (per tasks/todo.md Phase 5, low-lift order)
- [ ] Record a 30-second Loom on a phone.
- [ ] Drop the Loom in the README (add to badges row).
- [ ] Post once in r/HVAC and once in r/mcp (value-first, not pitch — per
      CLAUDE.md Phase 5 rule).
- [ ] Submit PR to `awesome-mcp-servers`.

## Definition of "v1 shipped"

All of:
- `uvx hvac-mcp` works on a fresh machine.
- `https://hvac-mcp.nightfast.tech/mcp` returns a valid `initialize`.
- Landing page takes a payment and issues a key that unlocks the premium tool.
- One paying customer has actually used it on a real service call.
