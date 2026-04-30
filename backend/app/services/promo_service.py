"""Service for promotional code management and redemption."""
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.payment import PromoCode, PromoRedemption
from app.services.billing_service import BillingService

logger = logging.getLogger(__name__)


class PromoService:
    """Handles promo code creation, redemption, and listing."""

    def __init__(self, db: Session, user_id: int | None = None):
        self.db = db
        self.user_id = user_id

    def redeem_code(self, code: str) -> dict:
        """Redeem a promo code and credit sparks to the user."""
        if self.user_id is None:
            raise ValueError("user_id is required")

        normalized = code.strip().upper()

        promo = (
            self.db.query(PromoCode)
            .filter(PromoCode.code == normalized)
            .first()
        )
        if not promo:
            raise ValueError("Invalid promo code")
        if not promo.is_active:
            raise ValueError("This promo code is no longer active")
        if promo.expires_at and promo.expires_at < datetime.utcnow():
            raise ValueError("This promo code has expired")
        if promo.max_uses is not None and promo.uses_count >= promo.max_uses:
            raise ValueError("This promo code has reached its maximum uses")

        # Check if user already redeemed
        existing = (
            self.db.query(PromoRedemption)
            .filter(
                PromoRedemption.promo_code_id == promo.id,
                PromoRedemption.user_id == self.user_id,
            )
            .first()
        )
        if existing:
            raise ValueError("You have already redeemed this code")

        # Credit sparks
        billing = BillingService(self.db, self.user_id)
        balance_txn = billing.add_credits(
            amount=Decimal(promo.sparks_amount),
            description=f"Promo code: {promo.code} ({promo.sparks_amount:,} sparks)",
        )

        # Create redemption record
        redemption = PromoRedemption(
            promo_code_id=promo.id,
            user_id=self.user_id,
            sparks_granted=promo.sparks_amount,
            balance_txn_id=balance_txn.id,
        )
        self.db.add(redemption)

        # Increment uses
        promo.uses_count += 1
        self.db.commit()

        # Get new balance
        new_balance = float(billing.get_available_balance())

        logger.info(
            "Promo redeemed: user=%d code=%s sparks=%d",
            self.user_id, promo.code, promo.sparks_amount,
        )

        return {
            "sparks_granted": promo.sparks_amount,
            "new_balance": new_balance,
        }

    def create_promo_code(
        self,
        code: str,
        sparks_amount: int,
        admin_id: int,
        expires_at: datetime | None = None,
        max_uses: int | None = None,
    ) -> PromoCode:
        """Create a new promo code (admin)."""
        normalized = code.strip().upper()

        existing = (
            self.db.query(PromoCode)
            .filter(PromoCode.code == normalized)
            .first()
        )
        if existing:
            raise ValueError(f"Promo code '{normalized}' already exists")

        promo = PromoCode(
            code=normalized,
            sparks_amount=sparks_amount,
            expires_at=expires_at,
            max_uses=max_uses,
            created_by=admin_id,
        )
        self.db.add(promo)
        self.db.commit()
        self.db.refresh(promo)

        logger.info("Promo code created: %s (%d sparks) by admin=%d", normalized, sparks_amount, admin_id)
        return promo

    def list_promo_codes(self, skip: int = 0, limit: int = 50) -> dict:
        """List all promo codes with stats (admin)."""
        query = self.db.query(PromoCode).order_by(PromoCode.created_at.desc())
        total = query.count()
        items = query.offset(skip).limit(limit).all()

        return {
            "items": [
                {
                    "id": p.id,
                    "code": p.code,
                    "sparks_amount": p.sparks_amount,
                    "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                    "max_uses": p.max_uses,
                    "uses_count": p.uses_count,
                    "is_active": p.is_active,
                    "created_at": p.created_at.isoformat(),
                }
                for p in items
            ],
            "total": total,
        }

    def deactivate_promo_code(self, code_id: int) -> dict:
        """Deactivate a promo code (admin)."""
        promo = self.db.query(PromoCode).filter(PromoCode.id == code_id).first()
        if not promo:
            raise ValueError(f"Promo code {code_id} not found")

        promo.is_active = False
        self.db.commit()

        logger.info("Promo code deactivated: %s", promo.code)
        return {"status": "deactivated", "code": promo.code}
