---
name: prelaunch-check
description: Idempotent pre-deploy gate. Confirms all 6 production dependencies are healthy (CI, tests, Fly, Stripe webhook, license DB, CORS) before pushing code or flipping Stripe settings. Run this before every live change.
---

# /prelaunch-check — six gates, one command

Red/green report on every moving piece. Takes ~15 seconds.

## Procedure

Run each block and report PASS/FAIL + specifics. If any gate fails, STOP and diagnose before proceeding with whatever the operator was about to change.

### Gate 1 — CI green on `main`
```bash
gh run list --limit 1 --branch main --json status,conclusion,displayTitle,headSha \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)[0]
ok = r['status'] == 'completed' and r['conclusion'] == 'success'
print(('PASS' if ok else 'FAIL'), '—', r['displayTitle'][:60], r['headSha'][:7])"
```

### Gate 2 — Local tests green
```bash
uv run --no-project --with-editable . --with pytest --with pytest-asyncio --with pyyaml --with stripe pytest -q 2>&1 | tail -2
```
Expect `N passed in Xs`.

### Gate 3 — Fly app is serving traffic
```bash
curl -sf https://hvac-mcp.fly.dev/health \
  && echo 'PASS — /health responsive' \
  || echo 'FAIL — /health not responding (check flyctl status)'
```

### Gate 4 — Stripe webhook endpoints exist and are enabled
```bash
stripe webhook_endpoints list --limit 10 2>&1 | python3 -c "
import sys, json
eps = json.load(sys.stdin).get('data', [])
hvac = [e for e in eps if 'hvac-mcp.fly.dev' in e.get('url','')]
if not hvac:
    print('FAIL — no webhook endpoint points at hvac-mcp.fly.dev')
else:
    for e in hvac:
        status = 'PASS' if e.get('status') == 'enabled' else 'FAIL'
        print(f\"{status} — {e['id']} livemode={e['livemode']} events={len(e['enabled_events'])}\")"
```

### Gate 5 — License DB reachable + has rows
```bash
flyctl ssh console --app hvac-mcp --command "python3 -c \"
import sqlite3
c = sqlite3.connect('/data/licenses.db')
n = c.execute('SELECT COUNT(*) FROM licenses').fetchone()[0]
active = c.execute('SELECT COUNT(*) FROM licenses WHERE status=\\\"active\\\"').fetchone()[0]
print(f'PASS — {n} total licenses, {active} active')
\"" 2>&1 | tail -3
```

### Gate 6 — CORS serving the Pages origin
```bash
curl -s -o /dev/null -w "%{http_code} %{header_json}\n" \
  -H "Origin: https://nightfast-app.github.io" \
  -H "Access-Control-Request-Method: GET" \
  -X OPTIONS https://hvac-mcp.fly.dev/license/lookup \
  | grep -q "access-control-allow-origin" \
  && echo 'PASS — CORS preflight returns ACAO' \
  || echo 'FAIL — CORS header missing'
```

## Reporting

Output one line per gate, then a one-line summary.

```
Gate 1 (CI):        PASS — feat: flip to Stripe live mode cefa3ce
Gate 2 (pytest):    PASS — 118 passed in 0.5s
Gate 3 (Fly):       PASS — /health responsive
Gate 4 (webhooks):  PASS — we_1TNG4w… livemode=True events=5
                    PASS — we_1TNFdp… livemode=False events=5
Gate 5 (DB):        PASS — 4 total licenses, 2 active
Gate 6 (CORS):      PASS — CORS preflight returns ACAO

All 6 gates green. Safe to proceed.
```

Red gates mean STOP and report to Kollin. Never push through a failing gate.
