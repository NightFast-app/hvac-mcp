# Deploy runbook — hosting the premium tier

The free tier needs nothing. This runbook is for when you want `hvac-mcp.nightfast.tech/mcp` to actually serve paying customers.

## 0. One-time prerequisites
- A Railway (or Fly.io) account connected to the `NightFast-app/hvac-mcp` repo.
- A Resend account + verified sending domain (for welcome emails). Free tier = 3k emails/mo.
- A Cloudflare (or other) DNS zone for `nightfast.tech`.

## 1. Deploy to Railway (~10 min)

1. Dashboard → **New project** → **Deploy from GitHub repo** → `NightFast-app/hvac-mcp`.
2. Railway auto-detects the `Dockerfile` and `railway.toml`.
3. The `railway.toml` already declares a volume at `/data` — accept the default name (`hvac-mcp-data`).
4. **Environment variables** (Service → Variables tab):

   | Name | Value | Notes |
   |---|---|---|
   | `STRIPE_WEBHOOK_SECRET` | `whsec_…` | From step 3 below. Required. |
   | `HVAC_MCP_DATA_DIR` | `/data` | Points SQLite at the volume. |
   | `RESEND_API_KEY` | `re_…` | From Resend dashboard. |
   | `HVAC_MCP_EMAIL_FROM` | `hvac-mcp <noreply@nightfast.tech>` | Sending address (must match a verified Resend domain). |
   | `LOG_LEVEL` | `INFO` | Optional. |

5. Deploy. Health check at `/health` should turn green within a minute.
6. Grab the Railway-generated URL (e.g. `hvac-mcp-production.up.railway.app`).

## 2. Custom domain: `hvac-mcp.nightfast.tech`

1. Railway → Service → **Settings** → **Networking** → Custom domain → `hvac-mcp.nightfast.tech`. Railway shows a CNAME target.
2. Cloudflare DNS → Add record:
   - Type: `CNAME`
   - Name: `hvac-mcp`
   - Target: *(Railway's CNAME target)*
   - Proxy: **DNS only** (gray cloud) — WebSocket/streaming works better bypassing the proxy for MCP traffic.
3. Wait for DNS propagation (typically <5 min). Railway auto-issues a TLS cert once it sees the domain resolve.
4. Smoke test:
   ```bash
   curl https://hvac-mcp.nightfast.tech/health
   # → {"status":"ok","service":"hvac-mcp"}
   ```

## 3. Register the Stripe webhook (~5 min)

1. Stripe Dashboard → **Developers → Webhooks → + Add endpoint**.
2. Endpoint URL: `https://hvac-mcp.nightfast.tech/stripe/webhook`
3. Events to send (select exactly these five):
   - `checkout.session.completed`
   - `customer.subscription.deleted`
   - `customer.subscription.paused`
   - `invoice.payment_failed`
   - `charge.refunded`
4. After creating, click the endpoint → **Signing secret → Reveal** → copy `whsec_…`.
5. Paste into Railway env var `STRIPE_WEBHOOK_SECRET`. Railway redeploys automatically.
6. Stripe endpoint detail page → **Send test webhook** → `checkout.session.completed` → Send. Should return 200 within a second.

## 4. Configure Resend (~5 min)

1. Resend → **Domains → Add domain** → `nightfast.tech`.
2. Add the DNS records Resend shows (SPF/DKIM/DMARC). In Cloudflare, all must be **DNS only**.
3. Wait for verification to turn green (usually under 10 min).
4. Resend → **API Keys → Create** → scope `Sending access` → copy `re_…`.
5. Paste into Railway env var `RESEND_API_KEY`. Redeploy.
6. Test: buy your own Starter tier with card `4242 4242 4242 4242`, use an email you control. Email should land within 30 seconds.

If email delivery fails but the webhook succeeded, the key is still in the DB:

```bash
curl https://hvac-mcp.nightfast.tech/license/lookup?session_id=cs_...
```

## 5. Flip Stripe into live mode

**Only after steps 1–4 are verified in test mode.**

```bash
# Switch CLI to live
stripe login --live

# Re-run the product/price/link creation (same commands, live account)
bash scripts/create_stripe_products.sh    # if we script it; else re-run inline

# Update landing/index.html:
#   STRIPE_LINKS → new live https://buy.stripe.com/... (no /test_ prefix)

# Commit + push; Pages auto-redeploys
```

Create a **second webhook endpoint** in Stripe live mode (same URL, same events, new `whsec_…`). Replace the value in Railway. Your test-mode endpoint can stay — it's harmless and lets you keep using test cards.

## 6. Ongoing ops

- **Monitor webhook deliveries** in Stripe Dashboard → Webhooks → your endpoint → Logs tab. Any failures = investigate.
- **Back up the license DB** by setting up a nightly Railway cron that `sqlite3 /data/licenses.db .dump > backup-$(date).sql` and uploads to S3/R2.
- **Rotating the webhook secret**: Stripe supports two secrets simultaneously — add the new one to env, Stripe signs with both during overlap window, then remove the old. No downtime.
- **Refund handling**: issue refunds from Stripe Dashboard. `charge.refunded` fires automatically, license status flips to `refunded`, premium tools stop working on next call.

## 7. Expected failure modes and recovery

| Symptom | Cause | Fix |
|---|---|---|
| Webhook returns 503 | `STRIPE_WEBHOOK_SECRET` unset | Set env var, redeploy |
| Webhook returns 400 | Wrong secret (test vs live mismatch) | Re-copy from correct Stripe mode |
| Key generated but no email | `RESEND_API_KEY` unset or domain unverified | Fix Resend, customer uses `/license/lookup` meanwhile |
| Redeploy wiped licenses | Volume not mounted at `/data`, or `HVAC_MCP_DATA_DIR` not set | Mount volume, set env, restore from backup |
| Customer says key doesn't work | Their subscription lapsed (`past_due`) or was cancelled | Check DB: `sqlite3 /data/licenses.db "SELECT * FROM licenses WHERE key='...'"` |
| Duplicate webhook deliveries | Normal Stripe behavior | Handler is idempotent on `stripe_session_id` — safe to ignore |
