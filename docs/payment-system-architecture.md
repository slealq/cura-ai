# SightLab Payment System Architecture

> Technical report for integrating real-money payments into SightLab's sparks billing system.
> Created: 2026-03-04

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Payment Provider Comparison](#2-payment-provider-comparison)
3. [Recommended Provider](#3-recommended-provider)
4. [System Architecture](#4-system-architecture)
5. [Database Schema](#5-database-schema)
6. [Webhook Flow](#6-webhook-flow)
7. [Failure Modes](#7-failure-modes)
8. [Security Model](#8-security-model)
9. [UX Design](#9-ux-design)
10. [Implementation Roadmap](#10-implementation-roadmap)

---

## 1. Executive Summary

SightLab has a production-grade internal billing system: sparks currency (1 spark = $0.001 USD), atomic balance operations, idempotent debits, cost catalog, and full audit trail. The missing piece is accepting real money.

**Recommendation:** Start with **Stripe** (requires US LLC) or **Lemon Squeezy** (works directly from Costa Rica) for one-time credit pack purchases. The architecture below is provider-agnostic — the webhook handler and ledger design work with any provider.

The core design principle: **the payment provider is a deposit ATM**. It sends money in; the existing `add_credits()` + `BalanceTransaction` ledger handles everything after.

### Existing Billing Infrastructure

The current system provides:

- **Sparks currency**: 1 spark = $0.001 USD, stored in `UserBalance.balance_sparks`
- **Atomic operations**: `reserve_sparks()` uses SQL `UPDATE ... WHERE` to prevent TOCTOU races
- **Idempotent debits**: Unique constraint on `(user_id, reference_id)` prevents double-charging
- **Full audit trail**: `BalanceTransaction` append-only ledger with trace IDs
- **Cost catalog**: `CostCatalog` with tiered matching (exact → wildcard model → wildcard op)
- **Billing orchestrator**: `CostDecision` pre-persisted before every provider call
- **Admin controls**: Credit management, reconciliation, anomaly tracking

The payment system must integrate at the `BillingService.add_credits()` entry point — no changes to existing billing internals required.

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

### Path A: US LLC exists or planned → Stripe

Best developer experience, lowest fees, superior fraud protection, Link wallet for one-click repeat purchases. Stripe Checkout handles the entire payment flow with minimal frontend code.

### Path B: Costa Rica entity only → Lemon Squeezy

Confirmed Costa Rica support, MoR handles global tax/VAT automatically, absorbs chargebacks. Higher fees but zero tax compliance burden.

### Path C: Hedge both → Stripe + PayPal as fallback

If you set up a US LLC, use Stripe as primary and offer PayPal as an alternative for users who prefer it.

### Practical Strategy

1. **Start with Lemon Squeezy** for the fastest path to revenue with zero tax compliance burden from Costa Rica
2. **Add PayPal** as an alternative payment method for users who prefer it
3. **Monitor Stripe Managed Payments** — when it goes fully public in 2026, evaluate migration (better rates + Stripe infrastructure)
4. **If you form a US LLC**, Stripe becomes viable and offers the lowest fees and best developer experience

**The architecture below is provider-agnostic.** The `PaymentTransaction` model and webhook handler work identically regardless of which provider you choose. You can start with one and add others later.

---

## 4. System Architecture

### End-to-End Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                  │
│                                                                  │
│  Buy Sparks Page → Select Pack → Create Checkout Session ────────┤
│                                      │                           │
│                          ┌───────────▼──────────┐                │
│                          │  Payment Provider     │                │
│                          │  (Stripe Checkout /   │                │
│                          │   LS Overlay)         │                │
│                          └───────────┬──────────┘                │
│                                      │                           │
│  ← Redirect to /billing?status=ok ◄─┘                           │
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
              │   3. Record payment txn    │
              │   4. Credit sparks         │
              │   5. Log audit trail       │
              └───────────────────────────┘
```

### Checkout Session Creation

```
Frontend                    Backend                     Provider
   │                          │                            │
   │  POST /billing/checkout  │                            │
   │  {pack_id: "10k"}       │                            │
   │─────────────────────────>│                            │
   │                          │  Create Checkout Session   │
   │                          │  {amount, currency,        │
   │                          │   metadata: {user_id,      │
   │                          │   pack_id, sparks_amount,  │
   │                          │   idempotency_key}}        │
   │                          │───────────────────────────>│
   │                          │                            │
   │                          │  ◄─ session_id + url       │
   │  ◄── {checkout_url}      │                            │
   │                          │                            │
   │  Redirect to checkout ──────────────────────────────>│
   │                          │                            │
   │  ◄── Redirect back       │  Webhook: payment.success │
   │      /billing?ok         │  ◄─────────────────────────│
   │                          │                            │
   │                          │  Process webhook           │
   │                          │  (credit sparks)           │
```

### Webhook Processing (Critical Path)

```python
# Pseudocode for webhook handler

def handle_payment_webhook(request):
    # 1. VERIFY SIGNATURE (reject spoofed webhooks)
    payload = request.body
    signature = request.headers["Stripe-Signature"]
    event = stripe.Webhook.construct_event(payload, signature, webhook_secret)

    # 2. EXTRACT EVENT
    if event.type != "checkout.session.completed":
        return 200  # Acknowledge but ignore

    session = event.data.object
    metadata = session.metadata
    user_id = int(metadata["user_id"])
    sparks_amount = Decimal(metadata["sparks_amount"])
    provider_payment_id = session.payment_intent  # unique from provider

    # 3. IDEMPOTENCY CHECK (prevent double-credit)
    existing = db.query(PaymentTransaction).filter_by(
        provider_payment_id=provider_payment_id
    ).first()
    if existing:
        return 200  # Already processed

    # 4. RECORD PAYMENT TRANSACTION
    txn = PaymentTransaction(
        user_id=user_id,
        provider="stripe",
        provider_payment_id=provider_payment_id,
        provider_session_id=session.id,
        amount_cents=session.amount_total,
        currency=session.currency,
        sparks_credited=sparks_amount,
        status="completed",
        metadata_snapshot=metadata,
    )
    db.add(txn)

    # 5. CREDIT SPARKS (uses existing billing_service)
    billing = BillingService(db, user_id)
    billing.add_credits(
        amount=sparks_amount,
        description=f"Purchased {sparks_amount} sparks (payment {provider_payment_id})",
    )

    # 6. COMMIT (atomic: payment record + credit in one transaction)
    db.commit()
    return 200
```

---

## 5. Database Schema

### New Table: `payment_transactions`

```python
class PaymentStatus(str, enum.Enum):
    PENDING = "pending"                      # Checkout created, not yet paid
    COMPLETED = "completed"                  # Payment succeeded, sparks credited
    FAILED = "failed"                        # Payment failed
    REFUNDED = "refunded"                    # Full refund issued
    PARTIALLY_REFUNDED = "partially_refunded"
    DISPUTED = "disputed"                    # Chargeback opened

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)

    # Provider references (idempotency keys)
    provider = Column(String(32), nullable=False)
    # "stripe", "lemon_squeezy", "paypal"
    provider_payment_id = Column(String(256), nullable=False, unique=True)
    # payment_intent ID or equivalent
    provider_session_id = Column(String(256), nullable=True)
    # checkout session ID

    # Money
    amount_cents = Column(Integer, nullable=False)
    # Amount in cents (e.g., 1000 = $10.00)
    currency = Column(String(8), nullable=False, default="usd")
    provider_fee_cents = Column(Integer, nullable=True)
    # Fee charged by provider

    # Sparks
    sparks_credited = Column(Numeric(10, 2), nullable=False)
    # Sparks added to balance
    pack_id = Column(String(64), nullable=True)
    # Which pack was purchased

    # Status
    status = Column(Enum(PaymentStatus), nullable=False,
                    default=PaymentStatus.PENDING)

    # Refund tracking
    refunded_amount_cents = Column(Integer, nullable=True, default=0)
    sparks_reversed = Column(Numeric(10, 2), nullable=True, default=0)
    refund_reason = Column(String(512), nullable=True)

    # Audit
    balance_txn_id = Column(Integer,
                            ForeignKey("balance_transactions.id"),
                            nullable=True)
    # Links to the CREDIT transaction
    metadata_snapshot = Column(JSON, nullable=True)
    # Full checkout metadata at time of payment
    provider_event_raw = Column(JSON, nullable=True)
    # Raw webhook payload (for disputes)
    ip_address = Column(String(64), nullable=True)

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

### New Table: `spark_packs` (Pricing Configuration)

```python
class SparkPack(Base):
    __tablename__ = "spark_packs"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)        # "Starter", "Pro"
    sparks_amount = Column(Integer, nullable=False)   # 5000, 25000, 60000
    price_cents = Column(Integer, nullable=False)     # 500, 2000, 4000
    currency = Column(String(8), default="usd")
    bonus_sparks = Column(Integer, default=0)         # Volume discount
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
```

### Integration with Existing Schema

No changes to existing tables. The flow connects via:

```
PaymentTransaction.balance_txn_id → BalanceTransaction.id
```

The `BalanceTransaction` created by `add_credits()` is linked back to the payment for full traceability:

```
PaymentTransaction → BalanceTransaction → UserBalance
(real money in)       (sparks ledger)      (available balance)
```

---

## 6. Webhook Flow

### Stripe Webhook Events to Handle

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Create PaymentTransaction, credit sparks |
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

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook signature")

    handler = WEBHOOK_HANDLERS.get(event.type)
    if handler:
        handler(db, event)

    return {"received": True}


WEBHOOK_HANDLERS = {
    "checkout.session.completed": handle_checkout_completed,
    "charge.refunded": handle_refund,
    "charge.dispute.created": handle_dispute,
}
```

### Idempotency Guarantee

Three layers of protection against double-crediting:

1. **Provider-level**: `provider_payment_id` has a UNIQUE constraint. Second webhook delivery triggers IntegrityError, caught and returns 200.

2. **Application-level**: Check `PaymentTransaction` exists before processing. If found with status=COMPLETED, skip.

3. **Balance-level**: The `BalanceTransaction` created by `add_credits()` can use a reference_id pointing to `PaymentTransaction.id` for additional deduplication.

```python
def handle_checkout_completed(db: Session, event):
    session = event.data.object
    provider_payment_id = session.payment_intent

    # Layer 1: Already processed?
    existing = db.query(PaymentTransaction).filter_by(
        provider_payment_id=provider_payment_id
    ).first()
    if existing and existing.status == PaymentStatus.COMPLETED:
        return  # Idempotent - already credited

    # ... create PaymentTransaction + credit sparks atomically ...
```

---

## 7. Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|------------|
| **Webhook never arrives** | User paid but no sparks | Reconciliation job compares provider records vs local DB daily. Manual credit via admin panel. |
| **Webhook arrives twice** | Double credit risk | UNIQUE on `provider_payment_id` + application check. |
| **DB commit fails after payment** | Payment succeeded but sparks not credited | Webhook retry (Stripe retries for 3 days). Idempotent handler processes retry safely. |
| **Webhook signature invalid** | Spoofed webhook | Reject with 400. Never credit without valid signature. |
| **User navigates away before redirect** | User thinks payment failed | Webhook still fires independently. Balance updates regardless of redirect. |
| **Provider goes down** | Cannot create checkout | Frontend shows error, user retries later. No data inconsistency. |
| **Chargeback/dispute** | Sparks already used | Flag account, freeze balance if sparks remain. Admin review. |
| **Refund requested** | Reverse sparks | Only refund if `balance_sparks >= sparks_to_reverse`. Partial refund if some sparks spent. |

### Reconciliation

A daily admin task (or Celery beat job) should:

1. Query the payment provider API for all payments in the last 48 hours
2. Compare against `payment_transactions` table
3. Flag any payments that exist at the provider but not locally (missed webhooks)
4. Flag any local records with status=PENDING older than 1 hour
5. Surface alerts in the admin dashboard

---

## 8. Security Model

### Webhook Verification

Every provider uses HMAC-based webhook signatures:

- **Stripe**: `stripe.Webhook.construct_event(payload, sig_header, secret)` verifies timing + signature
- **Lemon Squeezy**: HMAC-SHA256 of raw body against signing secret
- **PayPal**: Verify via PayPal API call

**Rule: Never trust webhook data without signature verification.**

### Replay Attack Prevention

- Stripe includes a timestamp in the signature. `construct_event` rejects events older than 5 minutes by default.
- Store `provider_payment_id` with UNIQUE constraint — replayed events are caught.

### Double Credit Prevention

Three independent layers:

1. UNIQUE constraint on `provider_payment_id`
2. Application-level existence check
3. Atomic transaction (payment record + credit in one commit)

### Chargeback Handling

```
charge.dispute.created webhook arrives
  -> Update PaymentTransaction.status = DISPUTED
  -> Calculate sparks at risk
  -> If user still has sparks: freeze reserved_sparks += disputed_amount
  -> Alert admin via email/Sentry
  -> Admin reviews and responds to dispute

charge.dispute.closed (won)
  -> Release frozen sparks
  -> Update status back to COMPLETED

charge.dispute.closed (lost)
  -> Debit sparks from balance (ADJUSTMENT transaction)
  -> Update PaymentTransaction.status = REFUNDED
  -> If balance goes negative: flag account, block operations
```

### Fraud Signals

- Track purchase velocity (multiple purchases in short window)
- Flag mismatched billing country vs user locale
- Monitor for accounts that purchase and immediately consume all sparks (then dispute)
- Stripe Radar handles most of this automatically

### Tax / VAT

- **With MoR (Paddle/LS)**: Provider handles everything. No action needed.
- **With Stripe**: Either use Stripe Tax ($0.50/tx) or handle manually. For virtual goods (digital credits), many jurisdictions still require VAT/GST collection. Consult a tax advisor before launch.

### Sensitive Data

- **Never store card numbers.** The payment provider handles PCI compliance.
- Store only provider-generated IDs (`payment_intent`, `session_id`).
- The `provider_event_raw` JSON column stores the raw webhook for dispute evidence — no card details are included in webhooks.

---

## 9. UX Design

### Spark Pack Tiers (Suggested)

| Pack | Sparks | Price | Bonus | Per-spark cost |
|------|--------|-------|-------|----------------|
| Starter | 5,000 | $5 | — | $0.001 |
| Creator | 25,000 | $20 | 2,500 bonus | $0.000727 |
| Pro | 60,000 | $40 | 10,000 bonus | $0.000571 |
| Studio | 150,000 | $80 | 30,000 bonus | $0.000444 |

Volume discounts incentivize larger purchases (fewer transactions = lower payment processing overhead).

### Buy Sparks Page

```
┌──────────────────────────────────────────────────┐
│  Buy Sparks                                       │
│                                                   │
│  Current balance: 1,250 sparks                    │
│                                                   │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐ │
│  │Starter │  │Creator │  │  Pro   │  │Studio  │ │
│  │        │  │        │  │        │  │        │ │
│  │ 5,000  │  │25,000  │  │60,000  │  │150,000 │ │
│  │sparks  │  │sparks  │  │sparks  │  │sparks  │ │
│  │        │  │+2,500  │  │+10,000 │  │+30,000 │ │
│  │ $5     │  │ $20    │  │ $40    │  │  $80   │ │
│  │        │  │        │  │        │  │        │ │
│  │ [Buy]  │  │ [Buy]  │  │ [Buy]  │  │ [Buy]  │ │
│  └────────┘  └────────┘  └────────┘  └────────┘ │
│                                                   │
│  Purchase history                                 │
│  ┌───────────────────────────────────────────┐   │
│  │ Mar 1  │ 25,000 sparks │ $20 │ Completed │   │
│  │ Feb 15 │ 5,000 sparks  │ $5  │ Completed │   │
│  └───────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

### Checkout Flow

1. User clicks "Buy" on a pack
2. Backend creates checkout session with provider
3. User is redirected to provider's hosted checkout (Stripe Checkout / LS overlay)
4. User completes payment
5. Redirect back to `/billing?purchase=success`
6. Frontend shows success toast + polls balance until updated
7. Webhook credits sparks in background (may arrive before or after redirect)

### Post-Purchase UX

- Show "Purchase successful! Your sparks will appear shortly." toast
- Poll `/billing/balance` every 2s for 30s after redirect
- When balance increases, show "X sparks added to your account" toast
- If balance doesn't update within 30s, show "Payment received — sparks may take a moment to appear"

---

## 10. Implementation Roadmap

### Phase 1: Minimal Working Payment System (2-3 weeks)

**Backend:**

1. Alembic migration: `payment_transactions` + `spark_packs` tables
2. Seed `spark_packs` with initial tiers
3. `backend/app/services/payment_service.py`:
   - `create_checkout_session(user_id, pack_id)` — returns checkout URL
   - `handle_webhook(provider, payload, signature)` — processes payment
   - `get_purchase_history(user_id)` — returns past purchases
4. `backend/app/api/webhooks.py`: Webhook endpoint (no auth, signature-verified)
5. `backend/app/api/billing.py`: Add `POST /billing/checkout` and `GET /billing/packs` endpoints
6. Environment variables: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`

**Frontend:**

7. `frontend/src/app/billing/page.tsx`: Add "Buy Sparks" section with pack cards
8. Redirect to Stripe Checkout on pack selection
9. Handle `?purchase=success` redirect with balance polling
10. Add purchase history to billing page

**Infrastructure:**

11. Configure webhook URL in provider dashboard (or via CLI for dev)
12. Set up webhook forwarding for local development (`stripe listen --forward-to`)

### Phase 2: Improved Billing UX (1-2 weeks)

1. Custom checkout page using Stripe Elements (embed payment form in-app)
2. Saved payment methods (Link wallet / Stripe Customer portal)
3. Email receipts on successful purchase
4. Low balance warning ("You have 50 sparks remaining — buy more?")
5. Admin dashboard: purchase analytics, revenue metrics
6. Reconciliation Celery beat task (daily provider vs local check)

### Phase 3: Subscriptions & Auto-Top-Up (2-3 weeks)

1. Subscription plans (e.g., "Pro Plan: 50,000 sparks/month for $35")
2. Auto-top-up: when balance drops below threshold, charge saved card
3. Stripe Customer Portal for subscription management
4. Usage-based billing option (monthly invoice based on actual consumption)
5. Promotional credits / coupon codes
6. Referral credits

### New API Endpoints (Phase 1)

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `GET /billing/packs` | GET | User | List available spark packs |
| `POST /billing/checkout` | POST | User | Create checkout session, returns URL |
| `GET /billing/purchases` | GET | User | Purchase history |
| `POST /webhooks/stripe` | POST | None* | Stripe webhook (*signature-verified) |
| `GET /billing/admin/purchases` | GET | Admin | All purchases, filterable |
| `POST /billing/admin/refund/{payment_id}` | POST | Admin | Issue refund |

### New Environment Variables

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
PAYMENT_PROVIDER=stripe          # or "lemon_squeezy"
```
