# SightLab Payment System Architecture

> Technical report for integrating real-money payments into SightLab's sparks billing system.
> Created: 2026-03-04 | Revised: 2026-03-04 (post architecture review)

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

## 4. System Architecture

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
   │  {pack_id: "10k"}       │                            │
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
    # 1. STORE RAW EVENT (before any processing)
    raw_event = PaymentWebhookEvent(
        provider="stripe",
        event_type=event.type,
        payload=json.loads(payload),
        received_at=utcnow(),
    )
    db.add(raw_event)
    db.flush()

    # 2. VERIFY SIGNATURE (reject spoofed webhooks)
    payload = request.body
    signature = request.headers["Stripe-Signature"]
    event = stripe.Webhook.construct_event(payload, signature, webhook_secret)

    # 3. EXTRACT EVENT
    if event.type != "checkout.session.completed":
        return 200  # Acknowledge but ignore

    session = event.data.object
    metadata = session.metadata
    purchase_id = metadata["purchase_id"]  # Our internal UUID
    user_id = int(metadata["user_id"])
    provider_payment_id = session.payment_intent

    # 4. FIND PENDING TRANSACTION (created at checkout time)
    txn = db.query(PaymentTransaction).filter_by(
        purchase_id=purchase_id
    ).first()

    if not txn:
        # Orphaned webhook — log anomaly, create txn anyway
        log.warning(f"No PENDING txn for purchase_id={purchase_id}")
        txn = PaymentTransaction(...)
        db.add(txn)

    # 5. IDEMPOTENCY CHECK (prevent double-credit)
    if txn.status == PaymentStatus.COMPLETED:
        return 200  # Already processed

    # 6. UPDATE TRANSACTION
    txn.provider_payment_id = provider_payment_id
    txn.status = PaymentStatus.COMPLETED
    txn.completed_at = utcnow()
    txn.webhook_event_id = raw_event.id

    # 7. CREDIT SPARKS (uses existing billing_service)
    #    The ledger entry is the source of truth, not txn.sparks_credited
    pack = db.query(SparkPack).get(txn.pack_id)
    sparks_to_credit = pack.sparks_amount + pack.bonus_sparks

    billing = BillingService(db, user_id)
    balance_txn = billing.add_credits(
        amount=sparks_to_credit,
        description=f"Purchased {sparks_to_credit} sparks ({txn.purchase_id})",
    )

    # 8. LINK BACK (payment -> ledger for traceability)
    txn.balance_txn_id = balance_txn.id

    # 9. COMMIT (atomic: all updates in one transaction)
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
    name = Column(String(64), nullable=False)        # "Starter", "Pro"
    sparks_amount = Column(Integer, nullable=False)   # 5000, 25000, 60000
    price_cents = Column(Integer, nullable=False)     # 500, 2000, 4000
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

## 6. Webhook Flow

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

## 7. Failure Modes

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

## 8. Security Model

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

## 9. UX Design

### Spark Pack Tiers (Suggested)

| Pack | Sparks | Price | Bonus | Per-spark cost | Featured |
|------|--------|-------|-------|----------------|----------|
| Starter | 5,000 | $5 | -- | $0.001 | |
| Creator | 25,000 | $20 | 2,500 bonus | $0.000727 | Recommended |
| Pro | 60,000 | $40 | 10,000 bonus | $0.000571 | |
| Studio | 150,000 | $80 | 30,000 bonus | $0.000444 | |

Volume discounts incentivize larger purchases (fewer transactions = lower payment processing overhead).

**Highlight the "Creator" pack as recommended.** Most SaaS credit systems feature one pack to increase conversion. The mid-tier pack is typically the best choice — not too small (low value perception), not too large (commitment barrier).

### Buy Sparks Page

```
┌──────────────────────────────────────────────────────────────┐
│  Buy Sparks                                                   │
│                                                               │
│  Current balance: 1,250 sparks                                │
│                                                               │
│  ┌────────┐  ┌─────────────┐  ┌────────┐  ┌────────┐        │
│  │Starter │  │  Creator    │  │  Pro   │  │Studio  │        │
│  │        │  │ RECOMMENDED │  │        │  │        │        │
│  │ 5,000  │  │   25,000    │  │60,000  │  │150,000 │        │
│  │sparks  │  │   sparks    │  │sparks  │  │sparks  │        │
│  │        │  │  +2,500     │  │+10,000 │  │+30,000 │        │
│  │ $5     │  │   $20       │  │ $40    │  │  $80   │        │
│  │        │  │             │  │        │  │        │        │
│  │ [Buy]  │  │   [Buy]     │  │ [Buy]  │  │ [Buy]  │        │
│  └────────┘  └─────────────┘  └────────┘  └────────┘        │
│                                                               │
│  Purchase history                                             │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ Mar 1  │ Creator Pack │ 27,500 sparks │ $20 │ Paid   │   │
│  │ Feb 15 │ Starter Pack │ 5,000 sparks  │ $5  │ Paid   │   │
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

## 10. Implementation Roadmap

### Phase 1: Minimal Working Payment System (2-3 weeks)

**Backend:**

1. Alembic migration: `payment_transactions` + `payment_webhook_events` + `spark_packs` tables
2. Seed `spark_packs` with initial tiers (Starter/Creator/Pro/Studio)
3. `backend/app/services/payment_gateway.py`: Abstract `PaymentGateway` interface + `StripeGateway` implementation
4. `backend/app/services/payment_service.py`:
   - `create_checkout_session(user_id, pack_id)` -- creates PENDING txn, returns checkout URL
   - `handle_webhook(provider, payload, signature)` -- stores event, processes payment
   - `get_purchase_history(user_id)` -- returns past purchases with status
5. `backend/app/api/webhooks.py`: Webhook endpoint (no auth, signature-verified)
6. `backend/app/api/billing.py`: Add `POST /billing/checkout`, `GET /billing/packs`, `GET /billing/purchases`
7. Environment variables: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`, `PAYMENT_PROVIDER`

**Frontend:**

8. `frontend/src/app/billing/page.tsx`: Add "Buy Sparks" section with pack cards (featured pack highlighted)
9. Redirect to Stripe Checkout on pack selection
10. Handle `?purchase=success` redirect with balance polling
11. Add purchase history to billing page

**Infrastructure:**

12. Configure webhook URL in provider dashboard (or via CLI for dev)
13. Set up webhook forwarding for local development (`stripe listen --forward-to`)

### Phase 2: Improved Billing UX (1-2 weeks)

1. Custom checkout page using Stripe Elements (embed payment form in-app)
2. Saved payment methods (Link wallet / Stripe Customer portal)
3. Email receipts on successful purchase
4. Low balance warning banner ("47 sparks remaining -- buy more?")
5. Admin dashboard: purchase analytics, revenue metrics, abandoned checkout rate
6. Reconciliation Celery beat task (daily provider vs local check)
7. New account purchase cooldown (max $20 for accounts < 24h old)

### Phase 3: Subscriptions & Auto-Top-Up (2-3 weeks)

1. Subscription plans (e.g., "Pro Plan: 50,000 sparks/month for $35")
2. Auto-top-up: when balance drops below threshold, charge saved card
3. Stripe Customer Portal for subscription management
4. Usage-based billing option (monthly invoice based on actual consumption)
5. Promotional credits / coupon codes (with shorter expiration)
6. Referral credits
7. Credit expiration policy (optional, 12-month default for purchased, 30-day for promotional)
8. Secondary payment provider (PayPal or Lemon Squeezy) via `PaymentGateway` abstraction

### New API Endpoints (Phase 1)

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `GET /billing/packs` | GET | User | List available spark packs |
| `POST /billing/checkout` | POST | User | Create checkout session, returns URL |
| `GET /billing/purchases` | GET | User | Purchase history |
| `POST /webhooks/stripe` | POST | None* | Stripe webhook (*signature-verified) |
| `GET /billing/admin/purchases` | GET | Admin | All purchases, filterable |
| `POST /billing/admin/refund/{payment_id}` | POST | Admin | Issue refund |
| `GET /billing/admin/abandoned` | GET | Admin | Abandoned checkouts (PENDING/EXPIRED) |
| `GET /billing/admin/webhook-events` | GET | Admin | Raw webhook event log |

### New Environment Variables

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
PAYMENT_PROVIDER=stripe          # or "lemon_squeezy"
```
