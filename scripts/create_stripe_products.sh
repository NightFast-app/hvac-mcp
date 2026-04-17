#!/usr/bin/env bash
# Create or reuse hvac-mcp products/prices/payment-links in Stripe.
#
# Runs idempotently — if a product with the expected name already exists in
# the current Stripe mode (test or live), we reuse it instead of creating a
# duplicate. Same for prices and payment links.
#
# Usage
# -----
# Test mode (default — needs `stripe login`):
#   bash scripts/create_stripe_products.sh
#
# Live mode:
#   bash scripts/create_stripe_products.sh --live
#
# Output: writes .env-style URLs to stdout and saves JSON snapshot at
# docs/stripe-links.<mode>.json for review. Doesn't push anywhere.

set -eo pipefail

MODE="test"
LIVE_FLAG=""
if [[ "${1:-}" == "--live" ]]; then
  MODE="live"
  LIVE_FLAG="--live"
fi

SUCCESS_URL="https://nightfast-app.github.io/hvac-mcp/success.html?session_id={CHECKOUT_SESSION_ID}"
OUTFILE="docs/stripe-links.${MODE}.json"

echo "=== hvac-mcp: creating Stripe products ($MODE mode) ==="

# Extract JSON field
j() { python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('$1',''))"; }

# Find a product by name in metadata[tier]; returns id or empty string.
find_product_by_tier() {
  local tier=$1
  stripe $LIVE_FLAG products list --limit 100 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin).get('data', [])
for p in data:
    if p.get('metadata', {}).get('tier') == '$tier' and p.get('active'):
        print(p['id']); break
"
}

find_active_price_for_product() {
  local product=$1
  stripe $LIVE_FLAG prices list --product="$product" --active=true --limit 10 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin).get('data', [])
if data: print(data[0]['id'])
"
}

find_link_for_price() {
  local price=$1
  stripe $LIVE_FLAG payment_links list --limit 100 2>/dev/null \
    | python3 -c "
import sys, json, os
price = '$price'
for p in json.load(sys.stdin).get('data', []):
    if not p.get('active'): continue
    # Note: Stripe API doesn't expand line_items by default on list; skip match.
    print(p.get('id'), p.get('url'))
" | head -1
}

ensure_product() {
  local tier=$1 name=$2 description=$3
  local existing
  existing=$(find_product_by_tier "$tier")
  if [[ -n "$existing" ]]; then
    echo "  product (reuse): $existing" >&2
    echo "$existing"
    return
  fi
  local id
  id=$(stripe $LIVE_FLAG products create \
    --name="$name" \
    --description="$description" \
    -d "metadata[tier]=$tier" | j id)
  echo "  product (new):   $id" >&2
  echo "$id"
}

ensure_price() {
  local product=$1 amount=$2 recurring=$3
  local existing
  existing=$(find_active_price_for_product "$product")
  if [[ -n "$existing" ]]; then
    echo "  price (reuse):   $existing" >&2
    echo "$existing"
    return
  fi
  local id
  if [[ "$recurring" == "month" ]]; then
    id=$(stripe $LIVE_FLAG prices create \
      --product="$product" --unit-amount="$amount" --currency=usd \
      -d "recurring[interval]=month" | j id)
  else
    id=$(stripe $LIVE_FLAG prices create \
      --product="$product" --unit-amount="$amount" --currency=usd | j id)
  fi
  echo "  price (new):     $id" >&2
  echo "$id"
}

ensure_payment_link() {
  local price=$1 tier=$2
  # Try to find an active link already tagged with this tier. Stripe doesn't
  # let us filter by line_items.price at list time, so we match on our own
  # metadata[tier] value (set at creation below).
  local existing_url existing_id
  read -r existing_id existing_url < <(
    stripe $LIVE_FLAG payment_links list --limit 100 2>/dev/null \
      | python3 -c "
import sys, json
tier = '$tier'
for p in json.load(sys.stdin).get('data', []):
    if p.get('active') and (p.get('metadata') or {}).get('tier') == tier:
        print(p['id'], p['url']); break
"
  )
  if [[ -n "${existing_url:-}" ]]; then
    echo "  plink (reuse):   $existing_id  $existing_url" >&2
    echo "$existing_url"
    return
  fi
  local json
  json=$(stripe $LIVE_FLAG payment_links create \
    -d "line_items[0][price]=$price" \
    -d "line_items[0][quantity]=1" \
    -d "after_completion[type]=redirect" \
    -d "after_completion[redirect][url]=$SUCCESS_URL" \
    -d "metadata[tier]=$tier")
  local id url
  id=$(echo "$json" | j id)
  url=$(echo "$json" | j url)
  echo "  plink (new):     $id  $url" >&2
  echo "$url"
}

# ─── Starter ────────────────────────────────────────────────────────────────
echo "--- Starter ($29/mo) ---"
STARTER_PRODUCT=$(ensure_product "starter" "hvac-mcp Starter" \
  "Hosted hvac-mcp with invoice drafting, estimates, parts cross-reference")
STARTER_PRICE=$(ensure_price "$STARTER_PRODUCT" 2900 month)
STARTER_URL=$(ensure_payment_link "$STARTER_PRICE" "starter")

# ─── Pro ────────────────────────────────────────────────────────────────────
echo "--- Pro ($79/mo) ---"
PRO_PRODUCT=$(ensure_product "pro" "hvac-mcp Pro" \
  "Everything in Starter + FL county permit lookup + priority support")
PRO_PRICE=$(ensure_price "$PRO_PRODUCT" 7900 month)
PRO_URL=$(ensure_payment_link "$PRO_PRICE" "pro")

# ─── Lifetime ───────────────────────────────────────────────────────────────
echo "--- Lifetime ($399 one-time) ---"
LIFETIME_PRODUCT=$(ensure_product "lifetime" "hvac-mcp Lifetime" \
  "One-time payment, all current and future premium tools. First 50 customers only.")
LIFETIME_PRICE=$(ensure_price "$LIFETIME_PRODUCT" 39900 one_time)
LIFETIME_URL=$(ensure_payment_link "$LIFETIME_PRICE" "lifetime")

# ─── Snapshot ───────────────────────────────────────────────────────────────
cat > "$OUTFILE" <<JSON
{
  "mode": "$MODE",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "starter":  { "product": "$STARTER_PRODUCT",  "price": "$STARTER_PRICE",  "url": "$STARTER_URL" },
  "pro":      { "product": "$PRO_PRODUCT",      "price": "$PRO_PRICE",      "url": "$PRO_URL" },
  "lifetime": { "product": "$LIFETIME_PRODUCT", "price": "$LIFETIME_PRICE", "url": "$LIFETIME_URL" }
}
JSON

echo ""
echo "=== DONE — wrote $OUTFILE ==="
echo "STARTER_URL=$STARTER_URL"
echo "PRO_URL=$PRO_URL"
echo "LIFETIME_URL=$LIFETIME_URL"
echo ""
echo "Next: paste these three URLs into landing/index.html STRIPE_LINKS, commit, push."
