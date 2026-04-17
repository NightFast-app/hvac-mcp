# hvac-mcp landing page

Static single-page site for hvac-mcp.nightfast.tech.

## Deploy

Cloudflare Pages, GitHub Pages, Netlify — any static host. Zero build step.

```bash
# GitHub Pages via a docs branch:
git subtree push --prefix landing origin gh-pages

# Or Cloudflare Pages: just point the Pages project at `landing/` as the
# build output directory; leave build command empty.
```

## Stripe integration

Three Stripe Payment Links (one per tier) — create them in the Stripe dashboard:
1. Starter — $29/mo recurring
2. Pro — $79/mo recurring
3. Lifetime — $399 one-time (limit to 50 via inventory rule)

Then paste the `https://buy.stripe.com/<id>` URLs into the `STRIPE_LINKS`
object at the bottom of `index.html`.

## License-key delivery

Payment Link → webhook → issue key:
- Configure Stripe webhook endpoint: `https://hvac-mcp.nightfast.tech/stripe/webhook`
  (needs a tiny serverless function or extend the MCP server with a webhook
  endpoint in Phase 3.1).
- On `checkout.session.completed`, generate a random key, store the mapping
  `key → stripe_customer_id` in a simple KV (Cloudflare KV, Redis, or a
  Postgres row), then email the customer their key + the connector URL via
  Resend / Postmark.
