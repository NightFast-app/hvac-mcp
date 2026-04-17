# Stripe products, prices & payment links

Source of truth for what's in Stripe.
Test links land on `buy.stripe.com/test_*`; live links land on `buy.stripe.com/*`
(no `test_` segment).

## Test mode (currently wired into landing/index.html)

Created 2026-04-17 via `stripe products create` → `stripe prices create` →
`stripe payment_links create`.

| Tier | Product ID | Price ID | Payment Link |
|---|---|---|---|
| Starter ($29/mo) | `prod_ULwtwJo9doOKXE` | `price_1TNEzOIbaOFvY0LHhYGwM9VB` | https://buy.stripe.com/test_fZu4gzaBb9G10gP4DOgQE00 |
| Pro ($79/mo) | `prod_ULwt4MaA5qy1j6` | `price_1TNEzPIbaOFvY0LHCbzqN8uj` | https://buy.stripe.com/test_7sYaEX38J3hD6FdfisgQE01 |
| Lifetime ($399 one-time) | `prod_ULwtuEMOBz9f8S` | `price_1TNEzPIbaOFvY0LHuhhTjVu2` | https://buy.stripe.com/test_5kQ3cvfVv19v6FdgmwgQE02 |

**Test card:** `4242 4242 4242 4242`, any future expiry, any 3-digit CVC, any ZIP.
**Declined card (to verify error handling):** `4000 0000 0000 0002`.

### How to test

1. Visit the landing page: https://nightfast-app.github.io/hvac-mcp/
2. Click "Buy Starter" / "Buy Pro" / "Buy Lifetime"
3. Fill in with the test card above
4. Confirm the payment completes and lands on Stripe's success page
5. In Stripe Dashboard → Payments (test mode), confirm the payment shows up

## Going live

When ready to take real money, re-run the creation script against live mode:

```bash
# Flip the CLI into live mode
stripe login --live

# Then re-run the product/price/link creation. The commands are identical —
# only the resulting URLs will differ (no "test_" prefix).
```

Replace the three URLs in `landing/index.html` → the `STRIPE_LINKS` constant,
update this file, and push. The GitHub Pages workflow auto-redeploys.

**Before flipping live:**
- [ ] Confirm business address, tax ID, and payout bank account are set in Stripe Dashboard
- [ ] Enable the customer portal so subscribers can self-manage cancellations
- [ ] Set up a webhook endpoint for `checkout.session.completed`,
      `customer.subscription.deleted`, `invoice.payment_failed`
- [ ] Verify the Stripe account isn't in "Restricted" state (happens with
      no business info filled in)

## Limiting Lifetime to 50 customers

Stripe Payment Links don't have a native "sell N then stop" control for
one-time payments. Options:
1. Enable **Inventory management** on the price (Stripe Dashboard → Price →
   "Limit quantity sold"). Set `available_quantity=50`.
2. Or check a counter in your webhook handler and deactivate the Payment Link
   via `stripe payment_links update --active=false` once the 50th sale fires.

Option 1 is simpler; option 2 is more flexible if you want to extend the
window later.
