"""Service for subscription plan management and lifecycle."""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]

from app.models.payment import (
    SubscriptionPlan,
    SubscriptionStatus,
    UserSubscription,
)
from app.models.user import User
from app.services.billing_service import BillingService
from app.services.payment_gateway import MockPaymentGateway, get_payment_gateway

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Handles subscription checkout, webhook processing, and cancellation."""

    def __init__(self, db: Session, user_id: int | None = None):
        self.db = db
        self.user_id = user_id

    def list_plans(self) -> list[SubscriptionPlan]:
        """List active subscription plans sorted by sort_order."""
        return (
            self.db.query(SubscriptionPlan)
            .filter(SubscriptionPlan.is_active.is_(True))
            .order_by(SubscriptionPlan.sort_order)
            .all()
        )

    def get_user_subscription(self) -> UserSubscription | None:
        """Get current user's active or cancelled subscription."""
        if self.user_id is None:
            return None
        return (
            self.db.query(UserSubscription)
            .filter(
                UserSubscription.user_id == self.user_id,
                UserSubscription.status.in_([
                    SubscriptionStatus.ACTIVE,
                    SubscriptionStatus.CANCELLED,
                    SubscriptionStatus.PAST_DUE,
                    SubscriptionStatus.PAUSED,
                ]),
            )
            .first()
        )

    async def create_subscription_checkout(
        self,
        plan_id: int,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        """Create a subscription checkout session."""
        if self.user_id is None:
            raise ValueError("user_id is required for checkout")

        # Check for existing active subscription
        existing = self.get_user_subscription()
        if existing and existing.status == SubscriptionStatus.ACTIVE:
            raise ValueError(
                "You already have an active subscription. "
                "Cancel it before subscribing to a new plan."
            )

        plan = self.db.query(SubscriptionPlan).filter(
            SubscriptionPlan.id == plan_id,
            SubscriptionPlan.is_active.is_(True),
        ).first()
        if not plan:
            raise ValueError(f"Plan {plan_id} not found or inactive")

        gateway = get_payment_gateway()
        result = await gateway.create_subscription_checkout(
            plan=plan,
            user_id=self.user_id,
            user_email=user_email,
            success_url=success_url,
            cancel_url=cancel_url,
        )

        # For mock gateway, auto-create subscription + credit sparks immediately
        if isinstance(gateway, MockPaymentGateway):
            self._create_subscription_record(
                plan=plan,
                provider_subscription_id=result.provider_session_id or f"mock_sub_{plan.id}",
            )

        return {
            "checkout_url": result.checkout_url,
        }

    def _create_subscription_record(
        self,
        plan: SubscriptionPlan,
        provider_subscription_id: str,
    ) -> UserSubscription:
        """Create a subscription record and credit initial sparks."""
        now = datetime.utcnow()
        period_end = now + timedelta(days=30)

        sub = UserSubscription(
            user_id=self.user_id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            provider="lemon_squeezy",
            provider_subscription_id=provider_subscription_id,
            current_period_start=now,
            current_period_end=period_end,
            sparks_granted_this_period=plan.sparks_per_month,
        )
        self.db.add(sub)
        self.db.flush()

        # Credit sparks
        billing = BillingService(self.db, self.user_id)
        billing.add_credits(
            amount=Decimal(plan.sparks_per_month),
            description=f"Subscription: {plan.name} plan ({plan.sparks_per_month:,} sparks/month)",
        )
        self.db.commit()
        self.db.refresh(sub)

        logger.info(
            "Subscription created: user=%d plan=%s sparks=%d",
            self.user_id, plan.name, plan.sparks_per_month,
        )
        return sub

    async def cancel_subscription(self) -> dict:
        """Cancel the current user's subscription at period end."""
        if self.user_id is None:
            raise ValueError("user_id is required")

        sub = self.get_user_subscription()
        if not sub or sub.status != SubscriptionStatus.ACTIVE:
            raise ValueError("No active subscription to cancel")

        sub.cancel_at_period_end = True
        sub.cancelled_at = datetime.utcnow()

        # Call gateway to cancel on provider side
        gateway = get_payment_gateway()
        if sub.provider_subscription_id and not isinstance(gateway, MockPaymentGateway):
            await gateway.cancel_subscription(sub.provider_subscription_id)

        # For mock gateway, set status to cancelled immediately
        if isinstance(gateway, MockPaymentGateway):
            sub.status = SubscriptionStatus.CANCELLED

        self.db.commit()

        logger.info("Subscription cancelled: user=%d", self.user_id)
        return {"status": "cancelled"}

    # --- Webhook handlers ---

    def handle_subscription_created(
        self, data: dict, custom_data: dict, webhook_event: object
    ) -> None:
        """Handle subscription_created webhook."""
        plan_id_str = custom_data.get("plan_id")
        user_id_str = custom_data.get("user_id")
        if not plan_id_str or not user_id_str:
            raise ValueError("Webhook missing plan_id or user_id in custom_data")

        plan_id = int(plan_id_str)
        user_id = int(user_id_str)
        self.user_id = user_id

        plan = self.db.query(SubscriptionPlan).filter(
            SubscriptionPlan.id == plan_id
        ).first()
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")

        provider_sub_id = str(data.get("data", {}).get("id", ""))

        # Check if subscription already exists
        existing = (
            self.db.query(UserSubscription)
            .filter(UserSubscription.provider_subscription_id == provider_sub_id)
            .first()
        )
        if existing:
            logger.info("Subscription %s already exists, skipping", provider_sub_id)
            return

        self._create_subscription_record(
            plan=plan,
            provider_subscription_id=provider_sub_id,
        )

    def handle_subscription_payment_success(
        self, data: dict, webhook_event: object
    ) -> None:
        """Handle subscription renewal payment — credit next period sparks."""
        provider_sub_id = str(data.get("data", {}).get("attributes", {}).get("subscription_id", ""))
        if not provider_sub_id:
            provider_sub_id = str(data.get("data", {}).get("id", ""))

        sub = (
            self.db.query(UserSubscription)
            .filter(UserSubscription.provider_subscription_id == provider_sub_id)
            .first()
        )
        if not sub:
            logger.warning("No subscription found for provider_id=%s", provider_sub_id)
            return

        plan = self.db.query(SubscriptionPlan).filter(
            SubscriptionPlan.id == sub.plan_id
        ).first()
        if not plan:
            return

        # Update period
        now = datetime.utcnow()
        sub.current_period_start = now
        sub.current_period_end = now + timedelta(days=30)
        sub.sparks_granted_this_period = plan.sparks_per_month
        sub.status = SubscriptionStatus.ACTIVE

        # Credit renewal sparks
        billing = BillingService(self.db, sub.user_id)
        billing.add_credits(
            amount=Decimal(plan.sparks_per_month),
            description=f"Subscription renewal: {plan.name} plan ({plan.sparks_per_month:,} sparks)",
        )
        self.db.commit()

        logger.info(
            "Subscription renewed: user=%d plan=%s sparks=%d",
            sub.user_id, plan.name, plan.sparks_per_month,
        )

    def handle_subscription_cancelled(
        self, data: dict, webhook_event: object
    ) -> None:
        """Handle subscription cancellation webhook."""
        provider_sub_id = str(data.get("data", {}).get("id", ""))

        sub = (
            self.db.query(UserSubscription)
            .filter(UserSubscription.provider_subscription_id == provider_sub_id)
            .first()
        )
        if not sub:
            logger.warning("No subscription found for provider_id=%s", provider_sub_id)
            return

        sub.cancel_at_period_end = True
        sub.cancelled_at = datetime.utcnow()
        self.db.commit()

        logger.info("Subscription cancelled via webhook: user=%d", sub.user_id)

    def handle_subscription_expired(
        self, data: dict, webhook_event: object
    ) -> None:
        """Handle subscription expiry webhook."""
        provider_sub_id = str(data.get("data", {}).get("id", ""))

        sub = (
            self.db.query(UserSubscription)
            .filter(UserSubscription.provider_subscription_id == provider_sub_id)
            .first()
        )
        if not sub:
            return

        sub.status = SubscriptionStatus.EXPIRED
        self.db.commit()

        logger.info("Subscription expired: user=%d", sub.user_id)

    def handle_subscription_payment_failed(
        self, data: dict, webhook_event: object
    ) -> None:
        """Handle failed subscription payment — set to past_due."""
        provider_sub_id = str(data.get("data", {}).get("id", ""))

        sub = (
            self.db.query(UserSubscription)
            .filter(UserSubscription.provider_subscription_id == provider_sub_id)
            .first()
        )
        if not sub:
            return

        sub.status = SubscriptionStatus.PAST_DUE
        self.db.commit()

        logger.warning("Subscription payment failed: user=%d", sub.user_id)
        if sentry_sdk:
            sentry_sdk.capture_message(
                f"Subscription payment failed: user_id={sub.user_id} "
                f"provider_sub_id={provider_sub_id}",
                level="warning",
            )

    def handle_subscription_updated(
        self, data: dict, webhook_event: object
    ) -> None:
        """Catch-all handler for subscription_updated events."""
        provider_sub_id = str(data.get("data", {}).get("id", ""))
        attrs = data.get("data", {}).get("attributes", {})

        sub = (
            self.db.query(UserSubscription)
            .filter(UserSubscription.provider_subscription_id == provider_sub_id)
            .first()
        )
        if not sub:
            return

        # Sync status from provider
        status_map = {
            "active": SubscriptionStatus.ACTIVE,
            "cancelled": SubscriptionStatus.CANCELLED,
            "expired": SubscriptionStatus.EXPIRED,
            "paused": SubscriptionStatus.PAUSED,
            "past_due": SubscriptionStatus.PAST_DUE,
        }
        provider_status = attrs.get("status")
        if provider_status in status_map:
            sub.status = status_map[provider_status]

        self.db.commit()

    # --- Admin ---

    def admin_list_subscriptions(
        self, skip: int = 0, limit: int = 50
    ) -> dict:
        """List all subscriptions with user info (admin)."""
        query = (
            self.db.query(UserSubscription)
            .order_by(UserSubscription.created_at.desc())
        )
        total = query.count()
        items = query.offset(skip).limit(limit).all()

        user_ids = {s.user_id for s in items}
        plan_ids = {s.plan_id for s in items}

        users_map = {
            u.id: u.email
            for u in self.db.query(User).filter(User.id.in_(user_ids)).all()
        } if user_ids else {}

        plans_map = {
            p.id: p
            for p in self.db.query(SubscriptionPlan).filter(
                SubscriptionPlan.id.in_(plan_ids)
            ).all()
        } if plan_ids else {}

        return {
            "items": [
                {
                    "id": s.id,
                    "user_id": s.user_id,
                    "user_email": users_map.get(s.user_id, ""),
                    "plan_name": plans_map[s.plan_id].name if s.plan_id in plans_map else "Unknown",
                    "sparks_per_month": plans_map[s.plan_id].sparks_per_month if s.plan_id in plans_map else 0,
                    "status": s.status.value,
                    "current_period_start": s.current_period_start.isoformat() if s.current_period_start else None,
                    "current_period_end": s.current_period_end.isoformat() if s.current_period_end else None,
                    "cancel_at_period_end": s.cancel_at_period_end,
                    "created_at": s.created_at.isoformat(),
                }
                for s in items
            ],
            "total": total,
        }
