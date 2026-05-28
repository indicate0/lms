"""
Webhook handlers for eNACH (Digio) and UPI Autopay (Razorpay).

These endpoints are NOT protected by Keycloak JWT auth — they are called by
external payment gateways. Authentication is via HMAC-SHA256 signature verification
of the raw request body against a shared secret (per LMS_AUTH.md §10 and
LMS_LLD.md §10 — Webhook verification).

HMAC verification is stubbed here. Plug in vendor-specific logic before go-live:
  Digio:    X-Digio-Signature  — HMAC-SHA256(secret, raw_body)
  Razorpay: X-Razorpay-Signature — HMAC-SHA256(webhook_secret, raw_body)
"""
import hashlib
import hmac
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import get_logger
from src.db.session import get_db
from src.services.bounce_service import handle_bounce

log = get_logger(__name__)
router = APIRouter()


# ── HMAC verification helpers ─────────────────────────────────────────────────

def _verify_hmac(secret: str, body: bytes, signature: str) -> bool:
    """Returns True if HMAC-SHA256(secret, body) matches signature."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# Webhook secrets — read from env; set in production via secrets manager
_DIGIO_WEBHOOK_SECRET: str = getattr(settings, "DIGIO_WEBHOOK_SECRET", "")
_RAZORPAY_WEBHOOK_SECRET: str = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")


# ── Payload schemas ───────────────────────────────────────────────────────────

class EnachWebhookPayload(BaseModel):
    loan_id: uuid.UUID
    schedule_id: uuid.UUID
    mandate_id: Optional[uuid.UUID] = None
    gateway_ref: str
    bounce_reason: str
    attempt_no: int = 1
    event: str  # 'nach.debit.failed'


class UpiWebhookPayload(BaseModel):
    loan_id: uuid.UUID
    schedule_id: uuid.UUID
    mandate_id: Optional[uuid.UUID] = None
    gateway_ref: str
    bounce_reason: str
    attempt_no: int = 1
    event: str  # 'payment.failed'


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/enach")
async def enach_webhook(
    request: Request,
    payload: EnachWebhookPayload,
    x_digio_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    # Signature verification — enforce in production when DIGIO_WEBHOOK_SECRET is set
    if _DIGIO_WEBHOOK_SECRET:
        if not x_digio_signature:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail={"error": "MISSING_SIGNATURE"})
        body = await request.body()
        if not _verify_hmac(_DIGIO_WEBHOOK_SECRET, body, x_digio_signature):
            log.warning("digio_signature_mismatch", gateway_ref=payload.gateway_ref)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail={"error": "INVALID_SIGNATURE"})

    if payload.event == "nach.debit.failed":
        bounce = await handle_bounce(
            session=db,
            loan_id=payload.loan_id,
            schedule_id=payload.schedule_id,
            mandate_id=payload.mandate_id,
            gateway_ref=payload.gateway_ref,
            bounce_reason=payload.bounce_reason,
            attempt_no=payload.attempt_no,
        )
        return {"status": "processed", "bounce_event_id": str(bounce.id)}
    return {"status": "ignored", "event": payload.event}


@router.post("/upi")
async def upi_webhook(
    request: Request,
    payload: UpiWebhookPayload,
    x_razorpay_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if _RAZORPAY_WEBHOOK_SECRET:
        if not x_razorpay_signature:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail={"error": "MISSING_SIGNATURE"})
        body = await request.body()
        if not _verify_hmac(_RAZORPAY_WEBHOOK_SECRET, body, x_razorpay_signature):
            log.warning("razorpay_signature_mismatch", gateway_ref=payload.gateway_ref)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail={"error": "INVALID_SIGNATURE"})

    if payload.event == "payment.failed":
        bounce = await handle_bounce(
            session=db,
            loan_id=payload.loan_id,
            schedule_id=payload.schedule_id,
            mandate_id=payload.mandate_id,
            gateway_ref=payload.gateway_ref,
            bounce_reason=payload.bounce_reason,
            attempt_no=payload.attempt_no,
        )
        return {"status": "processed", "bounce_event_id": str(bounce.id)}
    return {"status": "ignored", "event": payload.event}
