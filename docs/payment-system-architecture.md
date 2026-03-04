# SightLab Payment System Architecture

> Technical report for integrating real-money payments into SightLab's sparks billing system.
> Created: 2026-03-04 | Revised: 2026-03-04 (post architecture review)

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Payment Provider Comparison](#2-payment-provider-comparison)
3. [Recommended Provider](#3-recommended-provider)
4. [Pricing Model](#4-pricing-model)
5. [System Architecture](#5-system-architecture)
6. [Database Schema](#6-database-schema)
7. [Webhook Flow](#7-webhook-flow)
8. [Failure Modes](#8-failure-modes)
9. [Security Model](#9-security-model)
10. [UX Design](#10-ux-design)
11. [Implementation Roadmap](#11-implementation-roadmap)

> **Key decision:** Sparks are an internal accounting unit, not a price. Users never see "1 spark = $0.001." Pack and subscription pricing sets the exchange rate. See [Section 4](#4-pricing-model).

---

## 1. Executive Summary

SightLab has a production-grade internal billing system: sparks virtual currency, atomic balance operations, idempotent debits, cost catalog, and full audit trail. Sparks are an internal accounting unit (1 spark = $0.001 USD internally) — but this equivalence is never shown to users. Pack and subscription pricing sets the user-facing exchange rate. The missing piece is accepting real money.

**Recommendation:** Start with **Stripe** (requires US LLC) or **Lemon Squeezy** (works directly from Costa Rica) for one-time credit pack purchases. The architecture below is provider-agnostic — the webhook handler and ledger design work with any provider.

The core design principle: **the payment provider is a deposit ATM**. It sends money in; the existing `add_credits()` + `BalanceTransaction` ledger handles everything after.

### Existing Billing Infrastructure

The current system provides:

- **Sparks currency**: 1 spark = $0.001 USD internally (never shown to users), stored in `UserBalance.balance_sparks`
- **Atomic operations**: `reserve_sparks()` uses SQL `UPDATE ... WHERE` to prevent TOCTOU races
- **Idempotent debits**: Unique constraint on `(user_id, reference_id)` prevents double-charging
- **Full audit trail**: `BalanceTransaction` append-only ledger with trace IDs
- **Cost catalog**: `CostCatalog` with tiered matching (exact -> wildcard model -> wildcard op)
- **Billing orchestrator**: `CostDecision` pre-persisted before every provider call
- **Admin controls**: Credit management, reconciliation, anomaly tracking

The payment system must integrate at the `BillingService.add_credits()` entry point — no changes to existing billing internals required.

### Design Principles

1. **Ledger is the single source of truth.** `BalanceTransaction` is authoritative for sparks. `PaymentTransaction` references it but never duplicates it.
2. **Webhook-first.** Frontend redirects are never trusted for crediting. Only verified webhooks trigger balance changes.
3. **Track before you charge.** Checkout sessions create a PENDING `PaymentTransaction` before the user pays, enabling abandoned checkout analytics and reconciliation.
4. **Internal IDs everywhere.** Every purchase gets a SightLab `purchase_id` (UUID) sent as provider metadata, independent of provider IDs.
5. **Provider abstraction.** A `PaymentGateway` interface allows swapping providers without changing the core billing flow.

---

## 2. Payment Provider Comparison

### Feature Matrix

| Factor | Stripe | Paddle | Lemon Squeezy | PayPal |
|--------|--------|--------|---------------|--------|
| **Costa Rica seller** | No (need US LLC) | Likely yes (verify) | Yes (confirmed) | Yes (limited) |
| **Domestic fees** | 2.9% + $0.30 | 5% + $0.50 | 5% + $0.50 | 3.49% + $0.49 |
| **International fees** | 4.4% + $0.30 | 5% + $0.50 (flat) | 6.5% + $0.50 | 4.99% + $0.49 |
| **Tax/VAT handling** | Manual (or +$0.50/tx) | Automatic (MoR) | Automatic (MoR) | Manual |
| **Chargeback liability** | You | Paddle | Lemon Squeezy | You |
| **Fraud protection** | Excellent (Radar) | Good (included) | Good (included) | Basic |
| **Developer experience** | Best-in-class | Good | Good (simple) | Fair |
| **Webhook reliability** | Excellent (3-day retry) | Good | Adequate | Fair |
| **Checkout UX** | Excellent + Link wallet | Good (overlay) | Good (overlay) | Trusted brand |
| **One-time purchases** | Full support | Full support | Full support | Full support |
| **Subscription support** | Full | Full | Full | Full |
| **Min monthly** | None | None | None | None |

**Adyen**: Eliminated — EUR 1,000/month minimum, enterprise-only.

### Fee Impact on Credit Pack Purchases

**$10 credit pack (10,000 sparks):**

| Provider | Fee | You receive | Effective rate |
|----------|-----|-------------|----------------|
| Stripe (domestic) | $0.59 | $9.41 | 5.9% |
| Stripe (international) | $0.74 | $9.26 | 7.4% |
| Paddle | $1.00 | $9.00 | 10.0% |
| Lemon Squeezy (domestic) | $1.00 | $9.00 | 10.0% |
| Lemon Squeezy (intl) | $1.15 | $8.85 | 11.5% |
| PayPal | $0.84 | $9.16 | 8.4% |

**$50 credit pack (50,000 sparks):**

| Provider | Fee | You receive | Effective rate |
|----------|-----|-------------|----------------|
| Stripe (domestic) | $1.75 | $48.25 | 3.5% |
| Paddle | $3.00 | $47.00 | 6.0% |
| Lemon Squeezy (domestic) | $3.00 | $47.00 | 6.0% |

**Key insight:** Stripe's fixed fee ($0.30) hurts less on larger purchases. The MoR providers (Paddle/LS) have a higher fixed fee ($0.50) but include tax compliance and chargeback coverage. For small purchases ($5-10), all providers take a significant cut.

### Provider Deep Dives

#### Stripe

- **Strengths**: Best-in-class API docs, SDKs in every language, CLI for local dev, Stripe Checkout (hosted payment page), Link wallet for one-click returning payments, Radar ML fraud detection (included free on standard pricing)
- **Weakness**: Not available in Costa Rica — requires US entity (US LLC via doola/Firstbase + US bank account via Mercury)
- **Tax**: Stripe Tax available as add-on ($0.50/tx), but you remain the seller of record
- **Webhooks**: Industry-leading. Retries for up to 3 days, CLI forwarding for local dev

#### Paddle

- **Strengths**: Merchant of Record — Paddle is the legal seller, handles all global tax/VAT, absorbs chargebacks, flat international pricing (no extra fees)
- **Weakness**: Verify Costa Rica payout support before committing. Smaller ecosystem than Stripe
- **Tax**: Fully automatic (included in MoR model)
- **Webhooks**: Reliable with Webhook Simulator for testing

#### Lemon Squeezy

- **Strengths**: Confirmed Costa Rica bank payout support, MoR with automatic tax handling, simple API, fastest time-to-integration
- **Weakness**: +1.5% surcharge on non-US transactions. Stripe acquired LS in July 2024 — long-term independence uncertain. Stripe Managed Payments (Stripe's own MoR) entering public access in 2026 at ~7.9% + $0.30
- **Tax**: Fully automatic (included in MoR model)
- **Webhooks**: Adequate but not as battle-tested as Stripe

#### PayPal

- **Strengths**: Works in Costa Rica, trusted brand (drives conversions for B2C), Smart Payment Buttons, Buy Now Pay Later
- **Weakness**: High fees (3.49% + $0.49), dated developer experience, no automatic tax handling
- **Best use**: As a secondary payment method alongside your primary processor

---

## 3. Recommended Provider

### Path A: US LLC exists or planned -> Stripe

Best developer experience, lowest fees, superior fraud protection, Link wallet for one-click repeat purchases. Stripe Checkout handles the entire payment flow with minimal frontend code.

### Path B: Costa Rica entity only -> Lemon Squeezy

Confirmed Costa Rica support, MoR handles global tax/VAT automatically, absorbs chargebacks. Higher fees but zero tax compliance burden.

### Path C: Hedge both -> Stripe + PayPal as fallback

If you set up a US LLC, use Stripe as primary and offer PayPal as an alternative for users who prefer it.

### Practical Strategy

1. **Start with Lemon Squeezy** for the fastest path to revenue with zero tax compliance burden from Costa Rica
2. **Add PayPal** as an alternative payment method for users who prefer it
3. **Monitor Stripe Managed Payments** — when it goes fully public in 2026, evaluate migration (better rates + Stripe infrastructure)
4. **If you form a US LLC**, Stripe becomes viable and offers the lowest fees and best developer experience

**Long-term recommendation: Stripe.** Best APIs, best fraud detection, best ecosystem, easiest subscription support, best webhooks. Many startups begin with MoR then migrate to Stripe once they have a US entity.

**The architecture below is provider-agnostic.** The `PaymentTransaction` model and webhook handler work identically regardless of which provider you choose. You can start with one and add others later.

---

## 4. Pricing Model

### The Problem: Sparks Are Doing Two Jobs

Currently, `1 spark = $0.001 USD` is used for both:

1. **Internal cost accounting** — what AI operations cost users (debits)
2. **Implied purchase price** — what users would pay for sparks (credits)

This creates a conflict. The 2x markup on AI provider costs is already baked into the spark debit amounts. If we sell sparks at $0.001/spark, our gross margin is exactly 50% on AI costs — but that's *before* payment processor fees, Azure infrastructure, and storage costs. After Lemon Squeezy's ~7-9% take-rate, actual margin drops below the 2x target.

### Solution: Separate Cost-Sparks from Sell-Sparks

**Keep `1 spark = $0.001 USD` as the internal accounting constant.** It's convenient, stable, and all existing billing logic depends on it. Don't change `USD_TO_SPARKS`, the cost catalog, or the debit flow.

**Decouple the purchase price from the internal constant.** Packs define how many sparks you get per dollar. The exchange rate varies by pack and by purchase channel (one-time vs subscription).

In practice:

| Concept | Definition | Example |
|---------|------------|---------|
| **Cost-spark** | Internal unit. 1 spark = $0.001 USD. Used for debits, reservations, catalog pricing. | Generate costs 50 sparks (= $0.05 after 2x markup on $0.025 provider cost) |
| **Sell-spark** | What users receive when purchasing. Exchange rate set by pack/subscription pricing. | $20 Creator pack gives 15,000 sparks (= $0.00133/spark effective) |

Users see "sparks" everywhere — they never see the internal dollar equivalence. The frontend should **remove** the "1 spark = $0.001 USD" display.

### Fully-Loaded Cost Per Spark

To set prices, we need the true cost of fulfilling 1 spark of user activity:

```
Provider cost per spark:
  1 spark = $0.001 (charged to user after 2x markup)
  Provider actually costs $0.0005 (half, because of 2x markup)

Infrastructure overhead (Azure compute, storage, Redis, networking):
  Estimate ~20% on top of provider costs
  Overhead per spark = $0.0005 × 0.20 = $0.0001

Fully-loaded COGS per spark = $0.0005 + $0.0001 = $0.0006
```

| Cost component | Per spark | Notes |
|----------------|-----------|-------|
| AI provider (raw) | $0.0005 | Half of spark value (2x markup) |
| Azure infrastructure | $0.0001 | ~20% overhead estimate |
| **Total COGS** | **$0.0006** | Measure and refine over time |

### Target Margins

"2x profit" means: **profit = 2 x cost**, so **revenue = 3 x cost** (67% gross margin).

"2x markup" means: **revenue = 2 x cost** (50% gross margin).

We target **2x markup (50% margin)** as the floor, after payment processor fees:

```
Target: net_revenue_per_spark >= 2 × COGS_per_spark
        net_revenue_per_spark >= 2 × $0.0006 = $0.0012

Where: net_revenue = gross_price - payment_fees
```

### Payment Fee Impact by Provider

| Provider | Fee formula | On $20 pack | Fee | Net | Effective rate |
|----------|-------------|-------------|-----|-----|----------------|
| Lemon Squeezy (domestic) | 5% + $0.50 | $20 | $1.50 | $18.50 | 7.5% |
| Lemon Squeezy (intl) | 6.5% + $0.50 | $20 | $1.80 | $18.20 | 9.0% |
| Stripe (domestic) | 2.9% + $0.30 | $20 | $0.88 | $19.12 | 4.4% |
| Stripe (intl) | 4.4% + $0.30 | $20 | $1.18 | $18.82 | 5.9% |

### Pack Pricing (Solving for Margin)

To achieve net $0.0012/spark after fees:

```
gross_price_per_spark = $0.0012 / (1 - fee_rate)

Lemon Squeezy domestic (7.5%): $0.0012 / 0.925 = $0.001297/spark
Lemon Squeezy intl (9.0%):     $0.0012 / 0.91  = $0.001319/spark
Stripe domestic (4.4%):        $0.0012 / 0.956 = $0.001255/spark
```

**Blended target: ~$0.00130/spark** (covers worst-case LS international).

This means:
- $20 should buy ~15,400 sparks (not 20,000)
- $50 should buy ~38,500 sparks (not 50,000)

### Recommended Pack Tiers

Packs use **decreasing price-per-spark** to incentivize larger purchases:

| Pack | Price | Sparks | Bonus | Total sparks | Effective $/spark | Net revenue (LS domestic) | COGS | Margin |
|------|-------|--------|-------|-------------|-------------------|--------------------------|------|--------|
| Starter | $10 | 7,000 | -- | 7,000 | $0.00143 | $9.00 | $4.20 | 2.14x |
| Creator | $25 | 20,000 | 2,000 | 22,000 | $0.00114 | $23.25 | $13.20 | 1.76x |
| Pro | $50 | 42,000 | 6,000 | 48,000 | $0.00104 | $47.00 | $28.80 | 1.63x |
| Studio | $100 | 90,000 | 15,000 | 105,000 | $0.00095 | $94.50 | $63.00 | 1.50x |

#### Margin Walkthrough: Starter ($10 → 7,000 sparks → 2.14x)

```
Step 1: Net after payment fees
  Gross:  $10.00
  LS fee: 5% + $0.50 = $1.00
  Net:    $9.00

Step 2: Cost to fulfill 7,000 sparks (if user spends them all)
  Provider cost per spark:       $0.0005  (half of $0.001, because 2x markup)
  Infrastructure overhead (20%): $0.0001
  Fully-loaded COGS per spark:   $0.0006

  COGS = 7,000 × $0.0006 = $4.20

Step 3: Margin
  $9.00 / $4.20 = 2.14x

  For every $1 of cost to fulfill those sparks, you keep $2.14 in revenue.
```

#### Margin Walkthrough: Studio ($100 → 105,000 sparks → 1.50x)

```
Step 1: Net after payment fees
  Gross:  $100.00
  LS fee: 5% + $0.50 = $5.50
  Net:    $94.50

Step 2: Cost to fulfill 105,000 sparks
  COGS = 105,000 × $0.0006 = $63.00

Step 3: Margin
  $94.50 / $63.00 = 1.50x
```

The margin is lower because the user gets far more sparks per dollar (volume discount).
The trade-off: lower margin but higher absolute revenue per transaction ($94.50 net vs
$9.00 on Starter) and lower fee impact ($0.50 fixed fee is 0.5% of $100 vs 5% of $10).

#### Why the margins decrease with pack size

- Larger packs have lower effective fee rates (fixed $0.50 is smaller %)
- Volume discount drives users toward bigger purchases (higher LTV)
- Even the Studio pack at 1.50x is profitable — the Starter pack at 2.14x subsidizes

**Weighted average margin** (assuming 40% Creator / 30% Pro / 20% Starter / 10% Studio):
~1.80x across all pack sizes.

**No $5 pack.** Lemon Squeezy's $0.50 fixed fee makes a $5 pack cost 15% in fees alone. Minimum pack is $10.

#### Key assumption: usage rate

All margins above assume the user **spends every spark they purchase**. In practice,
some percentage goes unused — and unused sparks cost $0 in provider calls. If a user
buys 7,000 sparks but only uses 5,000, the real COGS is $3.00 not $4.20, making the
effective margin 3.0x instead of 2.14x. Unused sparks are pure profit.

### Subscription Pricing (Better Value)

Subscriptions are 15-25% cheaper per spark than packs, incentivizing predictable recurring revenue:

| Plan | Monthly price | Sparks/month | Effective $/spark | vs Creator pack |
|------|--------------|-------------|-------------------|-----------------|
| Hobby | $15/mo | 15,000 | $0.00100 | 12% cheaper |
| Pro | $40/mo | 45,000 | $0.00089 | 22% cheaper |
| Studio | $80/mo | 100,000 | $0.00080 | 30% cheaper |

#### Margin Walkthrough: Pro Subscription ($40/mo → 45,000 sparks → 1.38x headline)

```
Step 1: Net after payment fees
  LS adds +0.5% for subscriptions, so 5.5% + $0.50:
  Gross:  $40.00
  LS fee: 5.5% + $0.50 = $2.70
  Net:    $37.30

Step 2: Cost to fulfill 45,000 sparks (if user spends them all)
  COGS = 45,000 × $0.0006 = $27.00

Step 3: Headline margin (100% usage)
  $37.30 / $27.00 = 1.38x
```

This looks thin — but subscriptions have **breakage** (unused credits that expire).
If 20% of subscription sparks go unused on average:

```
Effective COGS: 45,000 × 0.80 × $0.0006 = $21.60
Adjusted margin: $37.30 / $21.60 = 1.73x
```

#### Why subscriptions work at lower headline margins

- **Predictable recurring revenue** (MRR — the metric investors and lenders care about)
- **Higher LTV** — a user paying $40/mo for 6 months = $240 total vs a one-time $50 pack
- **Breakage** — unused sparks expire monthly, improving real-world margin from 1.38x to ~1.73x
- **Lower churn cost** — acquiring a subscriber once vs re-acquiring pack buyers repeatedly

Subscription sparks reset monthly (no rollover in base plan). Unused sparks expire at
month end. This is standard for credit subscription models (Midjourney, Replicate).

Optional: allow rollover for up to 1 month of unused sparks at higher-tier plans.

LS adds +0.5% for subscription billing, factored into the margins above.

### What Users Can DO With Sparks

For context when setting pack sizes — what a typical session costs:

| Activity | Sparks | Notes |
|----------|--------|-------|
| Process 100 images (full pipeline: tag + describe + embed) | ~1,500 | ~15 sparks/image |
| Generate 20 images (flux-dev) | ~1,000 | 50 sparks/image |
| Generate 20 images (nano-banana-pro) | ~1,560 | 78 sparks/image |
| Edit 10 images (qwen-image-max) | ~1,500 | 150 sparks/image |
| Edit 10 images (kling-image) | ~560 | 56 sparks/image |
| Train 1 LoRA model (flux-dev) | ~4,000 | One-time |
| Evaluate 1 LoRA (5 ref + 5 creative pairs) | ~1,500 | Estimated |
| **Typical full session** | **~6,500** | Upload + train + generate |

So the **Creator pack ($25 = 22,000 sparks)** covers ~3 full sessions. That feels like the right anchor — enough to explore without running out immediately, priced to encourage the upgrade conversation.

### Implementation Changes Required

**Backend:**

1. **Remove `1 spark = $0.001` from user-facing contexts.** Keep `USD_TO_SPARKS = 1000` in `cost_calculator.py` for internal cost accounting only.
2. **Do NOT change the cost catalog, markup, or debit logic.** The internal billing system stays exactly the same.
3. **Pack pricing is the only place USD-to-spark conversion happens for purchases.** The `spark_packs` table defines the exchange rate per pack.

**Frontend:**

1. **Remove** the "1 spark = $0.001 USD" text from `billing/page.tsx:66`.
2. **Show spark costs in sparks only**, never in dollar equivalents on the user-facing billing page.
3. **Pack cards show**: price, sparks received, bonus sparks. No $/spark calculation displayed.
4. **Subscription page shows**: monthly price, sparks/month, "Best value" badge.

**What stays the same:**

- `USD_TO_SPARKS = 1000` constant (internal only)
- `CostCatalog` pricing and markup (internal only)
- `BillingService.debit_usage()` and `record_usage()` (no changes)
- `UserBalance.balance_sparks` and `BalanceTransaction` (no changes)
- Admin dashboard can still show dollar equivalents for cost analysis

### Margin Monitoring

Add a `purchase_margin_report` admin endpoint (or Celery beat task) that computes:

```python
# For each PaymentTransaction (COMPLETED):
gross_paid = txn.amount_cents / 100
processor_fee = txn.provider_fee_cents / 100  # From provider data
net_received = gross_paid - processor_fee
sparks_credited = balance_txn.amount_sparks  # From linked ledger entry
cogs = sparks_credited * Decimal("0.0006")   # Fully-loaded cost
margin_ratio = net_received / cogs

# Aggregate across time periods for dashboard
```

Surface alerts if blended margin drops below 1.5x (warning) or 1.3x (critical).

---

## 5. System Architecture

### End-to-End Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                  │
│                                                                  │
│  Buy Sparks Page -> Select Pack -> Create Checkout Session ──────┤
│                                      │                           │
│                          ┌───────────▼──────────┐                │
│                          │  Payment Provider     │                │
│                          │  (Stripe Checkout /   │                │
│                          │   LS Overlay)         │                │
│                          └───────────┬──────────┘                │
│                                      │                           │
│  <- Redirect to /billing?status=ok <─┘                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────▼──────────────┐
              │   Payment Provider         │
              │   Webhook (async)          │
              └────────────┬──────────────┘
                           │
              ┌────────────▼──────────────┐
              │   POST /api/webhooks/     │
              │   stripe (or /lemon)      │
              │                            │
              │   1. Verify signature      │
              │   2. Check idempotency     │
              │   3. Update payment txn    │
              │   4. Credit sparks         │
              │   5. Log audit trail       │
              └───────────────────────────┘
```

### Checkout Session Creation (with PENDING tracking)

```
Frontend                    Backend                     Provider
   │                          │                            │
   │  POST /billing/checkout  │                            │
   │  {pack_id: 2}            │                            │
   │─────────────────────────>│                            │
   │                          │  Generate purchase_id      │
   │                          │  (UUID, internal)          │
   │                          │                            │
   │                          │  Create PaymentTransaction │
   │                          │  (status=PENDING)          │
   │                          │                            │
   │                          │  Create Checkout Session   │
   │                          │  {amount, currency,        │
   │                          │   metadata: {purchase_id,  │
   │                          │   user_id, pack_id,        │
   │                          │   sparks_amount}}          │
   │                          │───────────────────────────>│
   │                          │                            │
   │                          │  <- session_id + url       │
   │                          │                            │
   │                          │  Update PaymentTransaction │
   │                          │  (provider_session_id)     │
   │                          │                            │
   │  <── {checkout_url}      │                            │
   │                          │                            │
   │  Redirect to checkout ──────────────────────────────>│
   │                          │                            │
   │  <── Redirect back       │  Webhook: payment.success │
   │      /billing?ok         │  <─────────────────────────│
   │                          │                            │
   │                          │  Find PENDING txn by       │
   │                          │  purchase_id or payment_id │
   │                          │  Update -> COMPLETED       │
   │                          │  Credit sparks via ledger  │
```

### Provider Gateway Abstraction

```python
# backend/app/services/payment_gateway.py

class PaymentGateway(ABC):
    """Abstract payment provider interface."""

    @abstractmethod
    def create_checkout_session(
        self,
        amount_cents: int,
        currency: str,
        metadata: dict,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        """Create a hosted checkout session. Returns URL + provider session ID."""
        ...

    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        """Verify webhook signature and parse event."""
        ...

    @abstractmethod
    def create_refund(
        self, provider_payment_id: str, amount_cents: int | None = None
    ) -> RefundResult:
        """Issue full or partial refund."""
        ...


class StripeGateway(PaymentGateway):
    ...

class LemonSqueezyGateway(PaymentGateway):
    ...

class PayPalGateway(PaymentGateway):
    ...
```

This prevents vendor lock-in. The `PaymentService` depends on the `PaymentGateway` interface, not on Stripe directly.

### Webhook Processing (Critical Path)

```python
# Pseudocode for webhook handler

def handle_payment_webhook(request):
    payload = request.body
    signature = request.headers["Stripe-Signature"]

    # 1. STORE RAW EVENT (before verification, for debugging)
    raw_event = PaymentWebhookEvent(
        provider="stripe",
        event_type="unknown",  # Updated after verification
        payload=json.loads(payload),
        received_at=utcnow(),
    )
    db.add(raw_event)
    db.flush()

    # 2. VERIFY SIGNATURE (reject spoofed webhooks)
    event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    raw_event.event_type = event.type
    raw_event.provider_event_id = event.id

    # 3. DISPATCH BY EVENT TYPE
    if event.type != "checkout.session.completed":
        raw_event.processed = True
        db.commit()
        return 200  # Acknowledge but ignore

    session = event.data.object
    metadata = session.metadata
    purchase_id = metadata["purchase_id"]  # Our internal UUID
    provider_payment_id = session.payment_intent

    # 4. FIND PENDING TRANSACTION (created at checkout time)
    txn = db.query(PaymentTransaction).filter_by(
        purchase_id=purchase_id
    ).first()

    if not txn:
        log.error(f"No PENDING txn for purchase_id={purchase_id}")
        raise ValueError(f"Orphaned webhook: {purchase_id}")

    # 5. IDEMPOTENCY CHECK (prevent double-credit)
    if txn.status == PaymentStatus.COMPLETED:
        return 200  # Already processed

    if txn.status != PaymentStatus.PENDING:
        log.warning(f"Unexpected status {txn.status} for {purchase_id}")
        return 200

    # 6. UPDATE TRANSACTION
    txn.provider_payment_id = provider_payment_id
    txn.status = PaymentStatus.COMPLETED
    txn.completed_at = utcnow()
    txn.webhook_event_id = raw_event.id

    # 7. CREDIT SPARKS (ledger is the source of truth)
    pack = db.query(SparkPack).get(txn.pack_id)
    sparks_to_credit = pack.sparks_amount + pack.bonus_sparks

    billing = BillingService(db, txn.user_id)
    balance_txn = billing.add_credits(
        amount=sparks_to_credit,
        description=f"Purchased {sparks_to_credit} sparks ({txn.purchase_id})",
    )

    # 8. LINK BACK (payment -> ledger for traceability)
    txn.balance_txn_id = balance_txn.id
    raw_event.processed = True

    # 9. COMMIT (atomic: all updates in one transaction)
    db.commit()
    return 200
```

---

## 6. Database Schema

### New Table: `payment_transactions`

```python
class PaymentStatus(str, enum.Enum):
    PENDING = "pending"                      # Checkout created, not yet paid
    COMPLETED = "completed"                  # Payment succeeded, sparks credited
    FAILED = "failed"                        # Payment failed
    EXPIRED = "expired"                      # Checkout session expired (abandoned)
    REFUNDED = "refunded"                    # Full refund issued
    PARTIALLY_REFUNDED = "partially_refunded"
    DISPUTED = "disputed"                    # Chargeback opened

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True)

    # Internal purchase ID (our own, provider-independent)
    purchase_id = Column(String(64), nullable=False, unique=True)
    # UUID generated at checkout creation time

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)

    # Provider references
    provider = Column(String(32), nullable=False)
    # "stripe", "lemon_squeezy", "paypal"
    provider_payment_id = Column(String(256), nullable=True, unique=True)
    # payment_intent ID — set when webhook arrives (nullable for PENDING)
    provider_session_id = Column(String(256), nullable=True)
    # checkout session ID — set at checkout creation

    # Money (always stored)
    amount_cents = Column(Integer, nullable=False)
    # Amount charged in smallest currency unit (e.g., 1000 = $10.00)
    currency = Column(String(8), nullable=False, default="usd")
    provider_fee_cents = Column(Integer, nullable=True)
    # Fee charged by provider (if reported via webhook)

    # Currency normalization (for international payments)
    usd_amount_cents = Column(Integer, nullable=True)
    # Normalized to USD cents. Same as amount_cents if currency=usd.
    exchange_rate = Column(Numeric(12, 6), nullable=True)
    # Exchange rate used (e.g., 1.08 for EUR->USD). Null if currency=usd.

    # Pack reference
    pack_id = Column(Integer, ForeignKey("spark_packs.id"), nullable=True)
    # Which pack was purchased

    # Status
    status = Column(Enum(PaymentStatus), nullable=False,
                    default=PaymentStatus.PENDING)

    # Refund tracking
    refunded_amount_cents = Column(Integer, nullable=True, default=0)
    refund_reason = Column(String(512), nullable=True)

    # Ledger reference (authoritative for sparks credited)
    balance_txn_id = Column(Integer,
                            ForeignKey("balance_transactions.id"),
                            nullable=True)
    # Links to the CREDIT BalanceTransaction. The ledger entry is the
    # source of truth for how many sparks were credited — derive from
    # BalanceTransaction.amount_sparks, not from this table.

    # Audit
    metadata_snapshot = Column(JSON, nullable=True)
    # Full checkout metadata at time of creation
    webhook_event_id = Column(Integer,
                              ForeignKey("payment_webhook_events.id"),
                              nullable=True)
    # Links to the webhook event that completed this payment
    ip_address = Column(String(64), nullable=True)
    # User's IP at checkout creation (fraud signal)

    # Timestamps
    created_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_payment_transactions_user_created",
              "user_id", "created_at"),
        Index("ix_payment_transactions_status", "status"),
    )
```

### New Table: `payment_webhook_events`

Separate event store for all incoming webhooks. Enables replay, debugging, and audit.

```python
class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    id = Column(Integer, primary_key=True)
    provider = Column(String(32), nullable=False)
    # "stripe", "lemon_squeezy", "paypal"
    event_type = Column(String(128), nullable=False)
    # e.g., "checkout.session.completed", "charge.refunded"
    provider_event_id = Column(String(256), nullable=True, unique=True)
    # Provider's event ID for deduplication
    payload = Column(JSON, nullable=False)
    # Raw webhook payload (no card details included by providers)
    processed = Column(Boolean, default=False)
    # Whether this event was successfully processed
    processing_error = Column(Text, nullable=True)
    # Error message if processing failed
    received_at = Column(DateTime, default=func.now())
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_webhook_events_provider_type",
              "provider", "event_type"),
    )
```

### New Table: `spark_packs` (Pricing Configuration)

```python
class SparkPack(Base):
    __tablename__ = "spark_packs"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)        # "Starter", "Creator", "Pro", "Studio"
    sparks_amount = Column(Integer, nullable=False)   # 7000, 20000, 42000, 90000
    price_cents = Column(Integer, nullable=False)     # 1000, 2500, 5000, 10000
    currency = Column(String(8), default="usd")
    bonus_sparks = Column(Integer, default=0)         # Volume discount bonus
    is_featured = Column(Boolean, default=False)      # Highlighted "Recommended" pack
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
```

### Integration with Existing Schema

No changes to existing tables. The flow connects via:

```
PaymentTransaction.balance_txn_id -> BalanceTransaction.id  (authoritative)
PaymentTransaction.webhook_event_id -> PaymentWebhookEvent.id
PaymentTransaction.pack_id -> SparkPack.id
```

**Ledger as source of truth:**

```
PaymentTransaction -> BalanceTransaction -> UserBalance
(real money in)       (sparks ledger,       (materialized
                       AUTHORITATIVE)        balance)
```

The `BalanceTransaction.amount_sparks` is the single source of truth for how many sparks were credited. `PaymentTransaction` references it via `balance_txn_id` but does not store a redundant `sparks_credited` column. To query sparks for a purchase, join through `balance_txn_id`.

### Credit Expiration (Optional, Future)

For platforms that need credit expiration:

```python
# On BalanceTransaction (extend existing)
expires_at = Column(DateTime, nullable=True)
# Null = never expires. Purchased sparks may have 12-month expiry.
# Promotional sparks may expire sooner (e.g., 30 days).
```

Expiration is enforced at debit time: oldest non-expired credits are consumed first (FIFO). This is a Phase 3+ consideration — not required for MVP.

---

## 7. Webhook Flow

### Stripe Webhook Events to Handle

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Update PENDING -> COMPLETED, credit sparks |
| `checkout.session.expired` | Update PENDING -> EXPIRED (abandoned checkout) |
| `payment_intent.payment_failed` | Update PaymentTransaction status to FAILED |
| `charge.refunded` | Reverse sparks, update PaymentTransaction |
| `charge.dispute.created` | Flag PaymentTransaction as DISPUTED, alert admin |
| `charge.dispute.closed` | Update dispute status (won/lost) |

### Webhook Handler Architecture

```python
# backend/app/api/webhooks.py

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    No auth required - verified by Stripe signature.
    Must return 200 quickly (< 5s) or Stripe retries.
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    # 1. Store raw event first (even before verification, for debugging)
    raw_event = PaymentWebhookEvent(
        provider="stripe",
        event_type="unknown",  # Updated after verification
        payload=json.loads(payload),
    )
    db.add(raw_event)
    db.flush()

    # 2. Verify signature
    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raw_event.processing_error = "Invalid signature"
        db.commit()
        raise HTTPException(400, "Invalid webhook signature")

    # 3. Update event metadata
    raw_event.event_type = event.type
    raw_event.provider_event_id = event.id

    # 4. Deduplicate by provider event ID
    if db.query(PaymentWebhookEvent).filter(
        PaymentWebhookEvent.provider_event_id == event.id,
        PaymentWebhookEvent.id != raw_event.id,
        PaymentWebhookEvent.processed == True,
    ).first():
        return {"received": True}  # Already processed this event

    # 5. Dispatch to handler
    handler = WEBHOOK_HANDLERS.get(event.type)
    if handler:
        try:
            handler(db, event, raw_event)
            raw_event.processed = True
            raw_event.processed_at = func.now()
        except Exception as e:
            raw_event.processing_error = str(e)
            db.commit()
            raise

    db.commit()
    return {"received": True}


WEBHOOK_HANDLERS = {
    "checkout.session.completed": handle_checkout_completed,
    "checkout.session.expired": handle_checkout_expired,
    "charge.refunded": handle_refund,
    "charge.dispute.created": handle_dispute,
    "charge.dispute.closed": handle_dispute_closed,
}
```

### Idempotency Guarantee

Three layers of protection against double-crediting:

1. **Provider-level**: `provider_event_id` on `PaymentWebhookEvent` has a UNIQUE constraint. Duplicate webhook deliveries are caught.

2. **Application-level**: Check `PaymentTransaction.status`. Only transition `PENDING -> COMPLETED`. If already `COMPLETED`, `REFUNDED`, or `DISPUTED`, skip crediting.

3. **Balance-level**: The `BalanceTransaction` created by `add_credits()` is linked via `balance_txn_id`. If `balance_txn_id` is already set, the credit was already applied.

```python
def handle_checkout_completed(db: Session, event, raw_event):
    session = event.data.object
    purchase_id = session.metadata.get("purchase_id")
    provider_payment_id = session.payment_intent

    # Find PENDING transaction (created at checkout time)
    txn = db.query(PaymentTransaction).filter_by(
        purchase_id=purchase_id
    ).first()

    if not txn:
        log.error(f"No PENDING txn for purchase_id={purchase_id}")
        raise ValueError(f"Orphaned webhook: {purchase_id}")

    # Idempotency: only credit if currently PENDING
    if txn.status == PaymentStatus.COMPLETED:
        return  # Already processed

    if txn.status not in (PaymentStatus.PENDING,):
        log.warning(f"Unexpected status {txn.status} for {purchase_id}")
        return

    # Update transaction
    txn.provider_payment_id = provider_payment_id
    txn.status = PaymentStatus.COMPLETED
    txn.completed_at = func.now()
    txn.webhook_event_id = raw_event.id

    # Credit sparks via ledger (source of truth)
    pack = db.query(SparkPack).get(txn.pack_id)
    sparks_to_credit = pack.sparks_amount + pack.bonus_sparks

    billing = BillingService(db, txn.user_id)
    balance_txn = billing.add_credits(
        amount=Decimal(sparks_to_credit),
        description=f"Purchased {sparks_to_credit} sparks ({txn.purchase_id})",
    )
    txn.balance_txn_id = balance_txn.id
```

---

## 8. Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|------------|
| **Webhook never arrives** | User paid but no sparks | Reconciliation job compares provider records vs local DB daily. Manual credit via admin panel. |
| **Webhook arrives twice** | Double credit risk | UNIQUE on `provider_event_id` + status check (only PENDING -> COMPLETED). |
| **DB commit fails after payment** | Payment succeeded but sparks not credited | Webhook retry (Stripe retries for 3 days). Idempotent handler processes retry safely. |
| **Webhook signature invalid** | Spoofed webhook | Reject with 400. Never credit without valid signature. Raw event stored for debugging. |
| **User navigates away before redirect** | User thinks payment failed | Webhook still fires independently. Balance updates regardless of redirect. |
| **Provider API goes down** | Cannot create checkout | Retry with exponential backoff (2-3 attempts). If all fail, show error. Future: fallback to secondary provider. |
| **Chargeback/dispute** | Sparks already used | Flag account, freeze balance if sparks remain. Admin review. |
| **Refund requested** | Reverse sparks | Only refund if `balance_sparks >= sparks_to_reverse`. Partial refund if some sparks spent. |
| **Checkout abandoned** | PENDING txn with no payment | `checkout.session.expired` webhook updates to EXPIRED. Reconciliation catches any missed. |

### Provider Outage Handling

```python
def create_checkout_session(self, user_id: int, pack_id: int) -> str:
    """Create checkout with retry logic."""
    gateway = get_payment_gateway()  # Returns configured provider

    for attempt in range(3):
        try:
            result = gateway.create_checkout_session(...)
            return result.checkout_url
        except ProviderUnavailableError:
            if attempt == 2:
                raise HTTPException(503, "Payment service temporarily unavailable")
            time.sleep(2 ** attempt)  # 1s, 2s, 4s
```

### Reconciliation

A daily Celery beat task should:

1. Query the payment provider API for all payments in the last 48 hours
2. Compare against `payment_transactions` table
3. Flag any payments that exist at the provider but not locally (missed webhooks)
4. Flag any local records with status=PENDING older than 1 hour (abandoned or missed)
5. Auto-expire PENDING transactions older than 24 hours (checkout session TTL)
6. Surface alerts in the admin dashboard and optionally via Sentry

---

## 9. Security Model

### Webhook Verification

Every provider uses HMAC-based webhook signatures:

- **Stripe**: `stripe.Webhook.construct_event(payload, sig_header, secret)` verifies timing + signature
- **Lemon Squeezy**: HMAC-SHA256 of raw body against signing secret
- **PayPal**: Verify via PayPal API call

**Rule: Never trust webhook data without signature verification.**

### Replay Attack Prevention

- Stripe includes a timestamp in the signature. `construct_event` rejects events older than 5 minutes by default.
- `provider_event_id` on `PaymentWebhookEvent` with UNIQUE constraint catches replayed events.
- `PaymentTransaction` status machine (PENDING -> COMPLETED) prevents re-crediting.

### Double Credit Prevention

Three independent layers:

1. UNIQUE constraint on `provider_event_id` (webhook dedup)
2. Status machine: only PENDING -> COMPLETED transitions credit sparks
3. Atomic transaction (status update + ledger credit in one commit)

### Chargeback Handling

```
charge.dispute.created webhook arrives
  -> Store raw event in payment_webhook_events
  -> Update PaymentTransaction.status = DISPUTED
  -> Calculate sparks at risk (from linked BalanceTransaction)
  -> If user still has sparks: freeze reserved_sparks += disputed_amount
  -> Alert admin via Sentry + email
  -> Admin reviews and responds to dispute

charge.dispute.closed (won)
  -> Release frozen sparks
  -> Update status back to COMPLETED

charge.dispute.closed (lost)
  -> Debit sparks from balance (ADJUSTMENT transaction)
  -> Update PaymentTransaction.status = REFUNDED
  -> If balance goes negative: flag account, block operations
```

### Fraud Protection

**Stripe Radar** (included free) handles most fraud detection automatically. Additional application-level protections:

- **New account cooldown**: Accounts less than 24 hours old are limited to max $20 purchase. This reduces chargeback fraud from throwaway accounts.
- **Purchase velocity**: Flag more than 3 purchases within 1 hour from the same user.
- **Billing country mismatch**: Flag when billing address country differs significantly from user's typical login locale.
- **Rapid-consume pattern**: Monitor accounts that purchase sparks and immediately consume 100% within minutes (then dispute). Auto-flag for review.

### Tax / VAT

- **With MoR (Paddle/LS)**: Provider handles everything. No action needed.
- **With Stripe**: Either use Stripe Tax ($0.50/tx) or handle manually. For virtual goods (digital credits), many jurisdictions still require VAT/GST collection. Consult a tax advisor before launch.

### Sensitive Data

- **Never store card numbers.** The payment provider handles PCI compliance.
- Store only provider-generated IDs (`payment_intent`, `session_id`).
- The `payment_webhook_events` table stores raw payloads for dispute evidence — providers never include card details in webhooks.

---

## 10. UX Design

### Spark Pack Tiers

See [Section 4: Pricing Model](#4-pricing-model) for the margin analysis behind these numbers.

| Pack | Price | Sparks | Bonus | Total | Featured |
|------|-------|--------|-------|-------|----------|
| Starter | $10 | 7,000 | -- | 7,000 | |
| Creator | $25 | 20,000 | 2,000 | 22,000 | Recommended |
| Pro | $50 | 42,000 | 6,000 | 48,000 | |
| Studio | $100 | 90,000 | 15,000 | 105,000 | |

No $5 pack — Lemon Squeezy's $0.50 fixed fee makes small packs unprofitable.

**Highlight the "Creator" pack as recommended.** It covers ~3 full sessions (upload + train + generate), priced to encourage exploration without immediate exhaustion.

### Buy Sparks Page

```
┌──────────────────────────────────────────────────────────────┐
│  Buy Sparks                                                   │
│                                                               │
│  Current balance: 1,250 sparks                                │
│                                                               │
│  ┌────────┐  ┌─────────────┐  ┌────────┐  ┌─────────┐      │
│  │Starter │  │  Creator    │  │  Pro   │  │ Studio  │      │
│  │        │  │ RECOMMENDED │  │        │  │         │      │
│  │ 7,000  │  │   22,000    │  │48,000  │  │105,000  │      │
│  │sparks  │  │   sparks    │  │sparks  │  │ sparks  │      │
│  │        │  │  +2,000     │  │+6,000  │  │+15,000  │      │
│  │ $10    │  │   $25       │  │ $50    │  │  $100   │      │
│  │        │  │             │  │        │  │         │      │
│  │ [Buy]  │  │   [Buy]     │  │ [Buy]  │  │ [Buy]   │      │
│  └────────┘  └─────────────┘  └────────┘  └─────────┘      │
│                                                               │
│  Or subscribe for the best value:                             │
│  [View subscription plans ->]                                 │
│                                                               │
│  Purchase history                                             │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ Mar 1  │ Creator Pack │ 22,000 sparks │ $25 │ Paid   │   │
│  │ Feb 15 │ Starter Pack │ 7,000 sparks  │ $10 │ Paid   │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Checkout Flow

1. User clicks "Buy" on a pack
2. Backend generates `purchase_id` (UUID), creates PENDING `PaymentTransaction`
3. Backend creates checkout session with provider (includes `purchase_id` in metadata)
4. User is redirected to provider's hosted checkout (Stripe Checkout / LS overlay)
5. User completes payment
6. Redirect back to `/billing?purchase=success`
7. Frontend shows success toast + polls balance until updated
8. Webhook credits sparks in background (may arrive before or after redirect)

### Post-Purchase UX

- Show "Purchase successful! Your sparks will appear shortly." toast
- Poll `/billing/balance` every 2s for 30s after redirect
- When balance increases, show "X sparks added to your account" toast
- If balance doesn't update within 30s, show "Payment received -- sparks may take a moment to appear"

### Low Balance Warning

When `available_balance < 100 sparks`, show a subtle banner:

```
⚡ Low balance: 47 sparks remaining. [Buy more sparks]
```

This appears in the sidebar or header, not as a blocking modal.

---

## 11. Implementation Roadmap

### Phase 1: Minimal Working Payment System (2-3 weeks)

Goal: Users can buy spark packs with real money. Admin can see purchases and issue refunds.

#### Step 1 — Database (migration 034)

Create three new tables in a single Alembic migration:

| Table | Key columns | Notes |
|-------|-------------|-------|
| `spark_packs` | name, sparks_amount, price_cents, bonus_sparks, is_featured, is_active, sort_order | Seed with 4 tiers (see below) |
| `payment_webhook_events` | provider, event_type, provider_event_id (unique), payload (JSON), processed, processing_error | Raw event store |
| `payment_transactions` | purchase_id (unique UUID), user_id, provider, provider_payment_id (unique), provider_session_id, amount_cents, currency, usd_amount_cents, exchange_rate, pack_id (FK), status (enum), refunded_amount_cents, balance_txn_id (FK), webhook_event_id (FK), ip_address | PENDING -> COMPLETED flow |

**Seed data for `spark_packs`:**

```python
packs = [
    {"name": "Starter",  "sparks_amount": 7000,  "price_cents": 1000,  "bonus_sparks": 0,     "is_featured": False, "sort_order": 1},
    {"name": "Creator",  "sparks_amount": 20000, "price_cents": 2500,  "bonus_sparks": 2000,  "is_featured": True,  "sort_order": 2},
    {"name": "Pro",      "sparks_amount": 42000, "price_cents": 5000,  "bonus_sparks": 6000,  "is_featured": False, "sort_order": 3},
    {"name": "Studio",   "sparks_amount": 90000, "price_cents": 10000, "bonus_sparks": 15000, "is_featured": False, "sort_order": 4},
]
```

#### Step 2 — Models

New files:

| File | Contents |
|------|----------|
| `backend/app/models/payment.py` | `PaymentStatus` enum, `PaymentTransaction`, `PaymentWebhookEvent`, `SparkPack` models |

Update `backend/app/models/__init__.py` to export the new models.

#### Step 3 — Payment Gateway Abstraction

New file: `backend/app/services/payment_gateway.py`

```
PaymentGateway (ABC)
  ├── create_checkout_session(amount_cents, currency, metadata, success_url, cancel_url) -> CheckoutResult
  ├── verify_webhook(payload, signature) -> WebhookEvent
  └── create_refund(provider_payment_id, amount_cents?) -> RefundResult

StripeGateway(PaymentGateway)    # Phase 1 implementation
LemonSqueezyGateway(PaymentGateway)  # Phase 1 alternative (if no US LLC)

get_payment_gateway() -> PaymentGateway  # Factory, reads PAYMENT_PROVIDER env var
```

The choice of Stripe vs Lemon Squeezy depends on entity setup (US LLC vs Costa Rica). The gateway abstraction means either can be swapped with zero changes to the rest of the codebase.

#### Step 4 — Payment Service

New file: `backend/app/services/payment_service.py`

| Method | Description |
|--------|-------------|
| `create_checkout(user_id, pack_id)` | Validate pack exists and is active. Generate `purchase_id` (UUID). Create PENDING `PaymentTransaction`. Call gateway `create_checkout_session()`. Update txn with `provider_session_id`. Return checkout URL. |
| `handle_webhook(provider, payload, signature)` | Store raw event in `payment_webhook_events`. Verify signature via gateway. Dispatch by event type. For `checkout.session.completed`: find PENDING txn by `purchase_id`, transition to COMPLETED, call `BillingService.add_credits()`, link `balance_txn_id`. All in one atomic commit. |
| `get_purchases(user_id, limit, skip)` | Paginated purchase history (joins to `SparkPack` for pack name and to `BalanceTransaction` for credited sparks). |
| `create_refund(payment_id, admin_user_id)` | Call gateway `create_refund()`. Update txn status. Create ADJUSTMENT `BalanceTransaction` to reverse sparks. Only if user has sufficient balance for full reversal; otherwise partial. |

#### Step 5 — API Routes

New file: `backend/app/api/webhooks.py`

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `POST /webhooks/stripe` | POST | None (signature-verified) | Stripe webhook receiver |
| `POST /webhooks/lemon-squeezy` | POST | None (signature-verified) | LS webhook receiver (if using LS) |

Add to existing `backend/app/api/billing.py`:

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `GET /billing/packs` | GET | User | List active spark packs (sorted by sort_order) |
| `POST /billing/checkout` | POST | User | Create checkout session, returns `{checkout_url}` |
| `GET /billing/purchases` | GET | User | Paginated purchase history |
| `GET /billing/admin/purchases` | GET | Admin | All purchases, filterable by user/status/date |
| `POST /billing/admin/refund/{payment_id}` | POST | Admin | Issue refund |
| `GET /billing/admin/abandoned` | GET | Admin | PENDING/EXPIRED checkouts |
| `GET /billing/admin/webhook-events` | GET | Admin | Raw webhook event log |

Register webhooks router in `backend/app/main.py` (no `/api` prefix — webhooks are at `/webhooks/stripe`).

#### Step 6 — Frontend Changes

| File | Change |
|------|--------|
| `frontend/src/app/billing/page.tsx` | Remove "1 spark = $0.001 USD" text (line 66). Add "Buy Sparks" section above existing balance card. Pack cards with featured highlight. "Buy" button calls `POST /billing/checkout` and redirects to returned URL. |
| `frontend/src/app/billing/page.tsx` | Handle `?purchase=success` query param: show success toast, poll `/billing/balance` every 2s for 30s until balance increases. |
| `frontend/src/app/billing/page.tsx` | Add purchase history table below transaction history (or as a new tab). |
| `frontend/src/lib/api.ts` | Add `billingApi.getPacks()`, `billingApi.createCheckout(packId)`, `billingApi.getPurchases()` functions. |

#### Step 7 — Infrastructure & Config

| Task | Details |
|------|---------|
| Environment variables | Add `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `PAYMENT_PROVIDER` to `.env`, Docker Compose, and Azure Container App secrets. |
| Webhook URL (production) | Configure in Stripe Dashboard: `https://<backend-url>/webhooks/stripe` |
| Webhook forwarding (local dev) | `stripe listen --forward-to localhost:8000/webhooks/stripe` |
| Docker Compose | Add `stripe` pip dependency to `backend/requirements.txt` |
| Stripe test mode | All development uses Stripe test keys (`sk_test_...`, `pk_test_...`). Test cards: `4242424242424242` (success), `4000000000000002` (decline). |

#### Phase 1 Deliverables Checklist

- [ ] Migration 034 creates 3 tables with seed data
- [ ] Models in `payment.py`
- [ ] `PaymentGateway` ABC + `StripeGateway` (or `LemonSqueezyGateway`)
- [ ] `PaymentService` with checkout, webhook, purchases, refund
- [ ] Webhook API route (signature-verified, no auth)
- [ ] Billing API routes (packs, checkout, purchases, admin)
- [ ] Frontend: pack cards, checkout redirect, balance polling, purchase history
- [ ] Frontend: remove "1 spark = $0.001" display
- [ ] Stripe test mode working locally with `stripe listen`
- [ ] Manual test: buy pack -> webhook -> sparks appear in balance

---

### Phase 2: Billing UX & Safety (1-2 weeks)

Goal: Better checkout experience, admin visibility, fraud guardrails.

| Task | Details |
|------|---------|
| **Low balance warning** | When `available_balance < 100 sparks`, show banner in sidebar/header: "Low balance: X sparks remaining. [Buy more]" |
| **Reconciliation task** | Celery beat job (daily): query provider API for payments in last 48h, compare against `payment_transactions`, flag mismatches. Auto-expire PENDING txns older than 24h. Alert via Sentry. |
| **Margin monitoring** | Admin endpoint `GET /billing/admin/margins`: for each COMPLETED payment, compute `net_received / cogs`. Surface alerts if blended margin < 1.5x (warning) or < 1.3x (critical). |
| **Abandoned checkout analytics** | Admin endpoint `GET /billing/admin/abandoned`: list PENDING/EXPIRED txns with user info and pack. Shows conversion funnel. |
| **New account cooldown** | Accounts < 24h old: max single purchase $20. Enforce in `create_checkout()`. |
| **Purchase velocity limit** | Max 3 purchases per user per hour. Enforce in `create_checkout()`. |
| **Email receipts** | Send email on successful purchase (via provider's built-in receipt or custom email). |
| **Saved payment methods** | Enable Stripe Link wallet or Stripe Customer objects for one-click returning purchases. |

---

### Phase 3: Subscriptions & Growth (2-3 weeks)

Goal: Recurring revenue, auto-top-up, promotional tools.

| Task | Details |
|------|---------|
| **Subscription plans** | Three tiers: Hobby ($15/mo, 15,000 sparks), Pro ($40/mo, 45,000 sparks), Studio ($80/mo, 100,000 sparks). Monthly reset with no rollover (standard model). |
| **Subscription models** | New `subscription_plans` table + `user_subscriptions` table (user_id, plan_id, provider_subscription_id, status, current_period_start/end). |
| **Subscription webhooks** | Handle `invoice.paid` (credit monthly sparks), `customer.subscription.deleted` (cancel), `invoice.payment_failed` (notify user). |
| **Auto-top-up** | User sets threshold (e.g., "recharge 10,000 sparks when balance < 500"). Requires saved payment method. Triggered by `BillingService` when balance drops below threshold during debit. |
| **Stripe Customer Portal** | Link to Stripe-hosted portal for subscription management (cancel, change plan, update payment method). |
| **Promotional credits** | Admin can create promo codes that grant bonus sparks. `promo_codes` table (code, sparks_amount, expires_at, max_uses, uses_count). Credits marked with `expires_at` on `BalanceTransaction`. |
| **Credit expiration** | Add `expires_at` column to `BalanceTransaction`. Purchased sparks: 12-month expiry. Promo sparks: 30-day expiry. Debit consumes oldest non-expired first (FIFO). |
| **Secondary provider** | Add `LemonSqueezyGateway` or `PayPalGateway` via `PaymentGateway` abstraction. User selects payment method at checkout. |
| **Referral credits** | User generates referral link. New user signs up -> both get bonus sparks after first purchase. |

---

### New Environment Variables (All Phases)

```bash
# Phase 1
PAYMENT_PROVIDER=stripe          # or "lemon_squeezy"
STRIPE_SECRET_KEY=sk_test_...    # sk_live_... in production
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Phase 2 (if using LS as secondary)
LEMON_SQUEEZY_API_KEY=...
LEMON_SQUEEZY_WEBHOOK_SECRET=...
LEMON_SQUEEZY_STORE_ID=...
```
