"""Payment gateway abstraction with Lemon Squeezy implementation."""
import hashlib
import hmac
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.models.payment import SparkPack, SubscriptionPlan

logger = logging.getLogger(__name__)

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]


@dataclass
class CheckoutResult:
    checkout_url: str
    provider_session_id: str | None = None


@dataclass
class RefundResult:
    success: bool
    provider_refund_id: str | None = None
    error: str | None = None


class PaymentGateway(ABC):
    """Abstract payment gateway interface."""

    @abstractmethod
    async def create_checkout_session(
        self,
        pack: SparkPack,
        purchase_id: uuid.UUID,
        user_id: int,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        ...

    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str, secret: str) -> dict:
        ...

    @abstractmethod
    async def create_refund(
        self, provider_payment_id: str, amount_cents: int | None = None
    ) -> RefundResult:
        ...

    @abstractmethod
    async def create_subscription_checkout(
        self,
        plan: SubscriptionPlan,
        user_id: int,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        ...

    @abstractmethod
    async def cancel_subscription(
        self, provider_subscription_id: str
    ) -> dict:
        ...


class LemonSqueezyGateway(PaymentGateway):
    """Lemon Squeezy payment gateway."""

    BASE_URL = "https://api.lemonsqueezy.com/v1"

    def __init__(self, api_key: str, store_id: str):
        self.api_key = api_key
        self.store_id = store_id

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }

    async def create_checkout_session(
        self,
        pack: SparkPack,
        purchase_id: uuid.UUID,
        user_id: int,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        if not pack.provider_variant_id:
            raise ValueError(
                f"Pack '{pack.name}' has no provider_variant_id configured. "
                "Set it in the spark_packs table to match a Lemon Squeezy variant."
            )

        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email": user_email,
                        "custom": {
                            "purchase_id": str(purchase_id),
                            "user_id": str(user_id),
                        },
                    },
                    "product_options": {
                        "redirect_url": success_url,
                    },
                    "expires_at": None,
                },
                "relationships": {
                    "store": {
                        "data": {"type": "stores", "id": self.store_id}
                    },
                    "variant": {
                        "data": {
                            "type": "variants",
                            "id": pack.provider_variant_id,
                        }
                    },
                },
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/checkouts",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("LS checkout API error: %s %s", e.response.status_code, e.response.text)
            if sentry_sdk:
                sentry_sdk.capture_exception(e)
            raise
        except httpx.HTTPError as e:
            logger.error("LS checkout network error: %s", e)
            if sentry_sdk:
                sentry_sdk.capture_exception(e)
            raise

        checkout_url = data["data"]["attributes"]["url"]
        session_id = data["data"]["id"]
        return CheckoutResult(checkout_url=checkout_url, provider_session_id=session_id)

    def verify_webhook(self, payload: bytes, signature: str, secret: str) -> dict:
        computed = hmac.new(
            secret.encode(), payload, hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(computed, signature):
            raise ValueError("Invalid webhook signature")
        import json

        return json.loads(payload)

    async def create_refund(
        self, provider_payment_id: str, amount_cents: int | None = None
    ) -> RefundResult:
        payload = {
            "data": {
                "type": "orders",
                "id": provider_payment_id,
            }
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.BASE_URL}/orders/{provider_payment_id}/refund",
                json=payload,
                headers=self._headers(),
            )

        if resp.status_code in (200, 201):
            return RefundResult(
                success=True,
                provider_refund_id=provider_payment_id,
            )
        return RefundResult(
            success=False,
            error=f"Refund failed: {resp.status_code} {resp.text}",
        )


    async def create_subscription_checkout(
        self,
        plan: SubscriptionPlan,
        user_id: int,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        if not plan.provider_variant_id:
            raise ValueError(
                f"Plan '{plan.name}' has no provider_variant_id configured."
            )

        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email": user_email,
                        "custom": {
                            "plan_id": str(plan.id),
                            "user_id": str(user_id),
                        },
                    },
                    "product_options": {
                        "redirect_url": success_url,
                    },
                    "expires_at": None,
                },
                "relationships": {
                    "store": {
                        "data": {"type": "stores", "id": self.store_id}
                    },
                    "variant": {
                        "data": {
                            "type": "variants",
                            "id": plan.provider_variant_id,
                        }
                    },
                },
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/checkouts",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("LS subscription checkout API error: %s %s", e.response.status_code, e.response.text)
            if sentry_sdk:
                sentry_sdk.capture_exception(e)
            raise
        except httpx.HTTPError as e:
            logger.error("LS subscription checkout network error: %s", e)
            if sentry_sdk:
                sentry_sdk.capture_exception(e)
            raise

        checkout_url = data["data"]["attributes"]["url"]
        session_id = data["data"]["id"]
        return CheckoutResult(checkout_url=checkout_url, provider_session_id=session_id)

    async def cancel_subscription(
        self, provider_subscription_id: str
    ) -> dict:
        payload = {
            "data": {
                "type": "subscriptions",
                "id": provider_subscription_id,
                "attributes": {"cancelled": True},
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.patch(
                    f"{self.BASE_URL}/subscriptions/{provider_subscription_id}",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("LS cancel subscription API error: %s %s", e.response.status_code, e.response.text)
            if sentry_sdk:
                sentry_sdk.capture_exception(e)
            raise
        except httpx.HTTPError as e:
            logger.error("LS cancel subscription network error: %s", e)
            if sentry_sdk:
                sentry_sdk.capture_exception(e)
            raise

        return {"success": True}


class MockPaymentGateway(PaymentGateway):
    """Mock gateway for local development without LS credentials."""

    async def create_checkout_session(
        self,
        pack: SparkPack,
        purchase_id: uuid.UUID,
        user_id: int,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        # Return the success URL directly for local testing
        mock_url = success_url
        logger.info(
            "Mock checkout: pack=%s purchase_id=%s user=%d → %s",
            pack.name, purchase_id, user_id, mock_url,
        )
        return CheckoutResult(
            checkout_url=mock_url,
            provider_session_id=f"mock_{purchase_id}",
        )

    def verify_webhook(self, payload: bytes, signature: str, secret: str) -> dict:
        import json

        return json.loads(payload)

    async def create_refund(
        self, provider_payment_id: str, amount_cents: int | None = None
    ) -> RefundResult:
        return RefundResult(success=True, provider_refund_id=provider_payment_id)

    async def create_subscription_checkout(
        self,
        plan: SubscriptionPlan,
        user_id: int,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        mock_url = success_url
        logger.info(
            "Mock subscription checkout: plan=%s user=%d → %s",
            plan.name, user_id, mock_url,
        )
        return CheckoutResult(
            checkout_url=mock_url,
            provider_session_id=f"mock_sub_{plan.id}_{user_id}",
        )

    async def cancel_subscription(
        self, provider_subscription_id: str
    ) -> dict:
        return {"success": True}


class PaymentsNotConfiguredError(RuntimeError):
    """No real payment gateway is configured and the mock is not allowed."""


def get_payment_gateway() -> PaymentGateway:
    """Factory: returns configured payment gateway.

    The mock gateway auto-completes purchases (credits sparks without any
    payment), so it is only returned in local dev or with an explicit
    PAYMENTS_ALLOW_MOCK opt-in. Cloud environments without Lemon Squeezy
    credentials raise PaymentsNotConfiguredError instead.
    """
    settings = get_settings()
    if settings.lemon_squeezy_api_key:
        return LemonSqueezyGateway(
            api_key=settings.lemon_squeezy_api_key,
            store_id=settings.lemon_squeezy_store_id,
        )
    if settings.environment == "local" or settings.payments_allow_mock:
        logger.warning("No Lemon Squeezy API key configured — using mock gateway")
        return MockPaymentGateway()
    raise PaymentsNotConfiguredError(
        "Automated payments are not configured in this environment"
    )
