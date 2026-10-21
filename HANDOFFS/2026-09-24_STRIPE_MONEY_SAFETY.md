# Stripe money safety — 2026-09-24

## What was hardened (code)
- One-time packs: grant only if `payment_status == paid` **and** `amount_total > 0`
- Subscriptions: same — **no** `no_payment_required` free grants
- Credits granted capped to known pack/plan amounts (+ sub top-up bonus) — metadata can't inflate
- Idempotent via `processed_payments.session_id` (unchanged)
- Webhook refuses to run if `STRIPE_WEBHOOK_SECRET` is empty

## Coupons (intentional free credits)
Private promo codes in `_CANONICAL_PROMO_CODES` (LAUNCH, SULTANSPECIAL, DEVIANTVIP, MOTIONLAUNCH):
- Redeem via `/redeem-promo` only (not listed on public pages)
- `max_uses_per_user: 1`
- These grant wallet credits **without Stripe** — by design

Stripe Promotion Codes at checkout apply a **discount** to a paid session — if someone creates a **100% off** Stripe promo in the Dashboard, checkout can be $0. Code now **blocks credit grant** on $0.

## Packs (UI = charge)
| Pack | Charge | Credits |
|------|--------|---------|
| Try | $7 | 75 |
| Session | $29 | 400 |
| Power | $59 | 900 |
| Marathon | $99 | 1800 |

Uses `price_data.unit_amount` from `CREDIT_PACKAGES` (Dashboard price IDs off by default).

## Nick must verify on Render
1. `STRIPE_SECRET_KEY` = live `sk_live_…` (not test) when advertising  
2. `STRIPE_PUBLISHABLE_KEY` = matching `pk_live_…`  
3. **`STRIPE_WEBHOOK_SECRET` = `whsec_…`** from Stripe Dashboard → Webhooks → endpoint `https://percfectai.com/webhook`  
   - Without this, **monthly renewals won't credit** (one-time packs still grant on `/payment-success` return)  
4. Do a **real $7 Try pack** test with a real card; confirm credits land and Stripe shows the charge  

## Lanes
- Coupons + Stripe money: coding (this note)  
- Post / publish: Nick + Gemini  
- Productions stitcher: coding  
