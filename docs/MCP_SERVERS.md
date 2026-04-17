# MCP server setup

## Team-shared (committed in `.mcp.json`)

### context7 — live documentation lookup
Already wired. No setup needed.

---

## Per-user (not committed — each operator adds these)

### stripe — customer support + refunds

**What it does**: lets Claude query Stripe customers, subscriptions, and
payments via the hosted Stripe MCP. Use it in conjunction with the
`support-lookup` skill and the `customer-support-responder` agent to
turn a 5-minute dashboard dance into one slash command.

**Add to Claude Code:**

1. Create a **scoped** restricted key in Stripe (never reuse the `rk_live_…`
   deploy token we used for `scripts/create_stripe_products.sh`).

   - https://dashboard.stripe.com/apikeys → **Live mode** → **Create restricted key**
   - Name: `hvac-mcp-support`
   - Scopes (set to **Read** unless noted):
     - Customers → Read
     - Checkout Sessions → Read
     - Subscriptions → Read
     - Payments → Read
     - Prices → Read
     - Products → Read
     - **Refunds → Write** (for the happy-path refund flow)
   - Everything else: None
   - Reveal → copy `rk_live_…`

2. Add the MCP server:
   ```bash
   claude mcp add stripe \
     --transport http \
     https://mcp.stripe.com \
     -H "Authorization: Bearer rk_live_<your_support_token>"
   ```

3. Confirm:
   ```bash
   claude mcp list
   ```
   Should show `stripe` alongside `context7`.

4. Optional — add a second entry for test mode using a separate
   `rk_test_…` key if you want to exercise the CLI against test data.

**Never commit the token.** `.mcp.json` is team-shared; `claude mcp add`
writes to per-user config.

**Revoke when done.** If you stop doing support from your machine (or
it's compromised), revoke at `/apikeys` — no code change needed.

---

### resend — welcome emails (pending)

**What it does**: automates SPF/DKIM DNS verification, domain
addition, and sent-email lookups from the CLI. Not strictly needed —
the Fly server already calls Resend directly when `RESEND_API_KEY` is
set as a Fly secret. Add this only if you want to manage Resend
config itself through Claude.

Not added yet. If/when needed, similar pattern:
```bash
claude mcp add resend --transport http https://mcp.resend.com \
  -H "Authorization: Bearer re_<your_key>"
```

---

### sentry — error tracking (future)

If/when we wire Sentry into the Fly app, add the Sentry MCP for error
investigation:
```bash
claude mcp add sentry --transport http https://mcp.sentry.dev/mcp \
  -H "Authorization: Bearer <your_auth_token>"
```

Not wired yet. Sentry tier decision pending: free Developer tier
(5k events/mo) is likely enough for launch.
