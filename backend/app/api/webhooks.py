"""Webhook endpoints for payment providers (no auth — signature-verified)."""
import json
import logging
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/lemon-squeezy")
async def lemon_squeezy_webhook(
    request: Request,
    x_signature: str = Header(None, alias="X-Signature"),
):
    """Handle Lemon Squeezy webhook events. No auth — verified via HMAC signature."""
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")

    # Signature is required (except in local dev with mock gateway)
    from app.core.config import get_settings
    settings = get_settings()

    if settings.lemon_squeezy_webhook_secret and not x_signature:
        raise HTTPException(status_code=401, detail="Missing X-Signature header")

    from app.db.base import SessionLocal
    db = SessionLocal()
    try:
        from app.services.payment_service import PaymentService
        service = PaymentService(db)
        result = service.handle_webhook(
            provider="lemon_squeezy",
            payload=body,
            signature=x_signature or "",
        )
        return result
    except ValueError as e:
        logger.warning("Webhook validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed")
    finally:
        db.close()


class TestWebhookRequest(BaseModel):
    event: str  # order_created, subscription_created, etc.
    purchase_id: str | None = None  # Required for order_created
    user_id: int | None = None
    plan_id: int | None = None  # Required for subscription_created


@router.post("/test")
async def test_webhook(body: TestWebhookRequest):
    """Simulate a webhook event for local testing.

    Only available when MockPaymentGateway is active (no LS API key configured).
    """
    from app.services.payment_gateway import (
        MockPaymentGateway,
        PaymentsNotConfiguredError,
        get_payment_gateway,
    )

    try:
        gateway = get_payment_gateway()
    except PaymentsNotConfiguredError:
        gateway = None
    if not isinstance(gateway, MockPaymentGateway):
        raise HTTPException(
            status_code=403,
            detail="Test webhooks are only available with mock gateway (no LS API key set)",
        )

    event_id = f"test_evt_{uuid.uuid4().hex[:12]}"

    if body.event == "order_created":
        if not body.purchase_id:
            raise HTTPException(
                status_code=400,
                detail="purchase_id is required for order_created events",
            )
        payload = {
            "meta": {
                "event_name": "order_created",
                "webhook_id": event_id,
                "custom_data": {
                    "purchase_id": body.purchase_id,
                    "user_id": str(body.user_id or 1),
                },
            },
            "data": {"id": f"mock_order_{uuid.uuid4().hex[:8]}"},
        }
    elif body.event == "subscription_created":
        if not body.plan_id or not body.user_id:
            raise HTTPException(
                status_code=400,
                detail="plan_id and user_id are required for subscription_created events",
            )
        payload = {
            "meta": {
                "event_name": "subscription_created",
                "webhook_id": event_id,
                "custom_data": {
                    "plan_id": str(body.plan_id),
                    "user_id": str(body.user_id),
                },
            },
            "data": {"id": f"mock_sub_{uuid.uuid4().hex[:8]}"},
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported test event: {body.event}. Supported: order_created, subscription_created",
        )

    # Process as if it were a real webhook
    from app.db.base import SessionLocal
    db = SessionLocal()
    try:
        from app.services.payment_service import PaymentService
        service = PaymentService(db)
        result = service.handle_webhook(
            provider="mock",
            payload=json.dumps(payload).encode(),
            signature="",
        )
        return {"status": "ok", "event": body.event, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Test webhook processing failed")
        raise HTTPException(status_code=500, detail="Test webhook processing failed")
    finally:
        db.close()
