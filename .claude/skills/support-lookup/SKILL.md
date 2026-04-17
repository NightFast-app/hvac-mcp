---
name: support-lookup
description: Look up a hvac-mcp customer by email or Stripe session_id and report their license key + status. Use for any "my license isn't working / I paid but didn't get a key / am I still active" support ticket.
---

# /support-lookup — resolve a customer's license in ~10 seconds

## When to use
Any inbound support signal about license state:
- "I paid but didn't get a key"
- "My subscription was cancelled — can I still use it?"
- "Why is my premium tool saying license_required?"

## Inputs (one of)
- Customer email (from the ticket)
- Stripe session id (if the customer forwarded their receipt — starts with `cs_live_` or `cs_test_`)
- Stripe customer id (if the ticket already has one)

## Procedure

### 1. Resolve Stripe customer
```bash
# By email
stripe customers list --email="<email>" --limit 1

# By session_id
stripe checkout sessions retrieve <cs_id>     # returns the customer id
```

Grab the `cus_...` id.

### 2. Look up their licenses on the live Fly volume
```bash
flyctl ssh console --app hvac-mcp --command "python3 -c \"
import sqlite3, datetime
c = sqlite3.connect('/data/licenses.db')
c.row_factory = sqlite3.Row
rows = list(c.execute('SELECT * FROM licenses WHERE stripe_customer_id=?', ('<cus_id>',)))
if not rows:
    print('NO_LICENSE_FOUND')
for r in rows:
    ts = datetime.datetime.fromtimestamp(r['issued_at']).isoformat(timespec='seconds')
    print(f\\\"{r['key']}  tier={r['tier']}  status={r['status']}  session={r['stripe_session_id']}  issued={ts}\\\")
\""
```

### 3. Diagnose and reply

| status | Likely cause | Action |
|---|---|---|
| `active` | Working correctly — check their client config | Send them the Claude Desktop config block from `docs/CONNECTING.md` with their real key substituted |
| `past_due` | Card failed on renewal | Tell them to update card in Stripe's customer portal; license reactivates on next successful invoice |
| `cancelled` | They (or Stripe) cancelled the subscription | Confirm intent; if resurrecting, issue a new subscription |
| `refunded` | A `charge.refunded` event fired | Expected — license is dead, no action |
| `NO_LICENSE_FOUND` | Webhook never fired or failed | See step 4 |

### 4. If no license row but Stripe shows a payment
Webhook delivery may have failed. Check:
```bash
# Any failed deliveries on the live endpoint?
stripe events list --type checkout.session.completed --limit 20 \
  | python3 -c "
import sys, json
for e in json.load(sys.stdin).get('data', []):
    print(e['id'], e['type'], e['created'])"

# Find the event for this customer's session
stripe events retrieve <evt_id>

# Manually resend the webhook to our endpoint
stripe webhook_endpoints resend we_1TNG4wIbaOFvY0LHQ8tDG6el --event-id=<evt_id>
```

If resending works, great. If not, **issue a license manually** via:
```bash
flyctl ssh console --app hvac-mcp --command "python3 -c \"
from hvac_mcp.storage import LicenseStore
lic = LicenseStore().issue(tier='starter', stripe_customer_id='<cus_id>', stripe_session_id='<cs_id>')
print(lic.key)
\""
```

Then email the key + update `tasks/lessons.md` with a note about why the webhook failed.

## Output format for the customer

```
Your license: hvac_<key>
Tier: <starter|pro|lifetime>
Status: active

Add to your Claude Desktop config at:
  ~/Library/Application Support/Claude/claude_desktop_config.json

{
  "mcpServers": {
    "hvac": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/NightFast-app/hvac-mcp", "hvac-mcp"],
      "env": { "HVAC_MCP_LICENSE_KEY": "hvac_<key>" }
    }
  }
}

Restart Claude Desktop. Reply if anything else.
— Kollin
```

## Non-goals
- Do NOT issue refunds from this skill — that's a Stripe dashboard action.
- Do NOT rotate a customer's key without asking them first.
- Never paste another customer's key into a different ticket, obviously.
