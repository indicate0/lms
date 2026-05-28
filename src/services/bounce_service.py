"""
Bounce handling engine — §4.14 of LMS_LLD.md.

Entry points:
  - handle_bounce()       called by eNACH/UPI Autopay webhook handlers
  - process_retry_queue() called by enach_retry cron (daily 08:00 IST)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import (
    BounceEvent, EmiDebitRetryQueue, Loan, LoanLedger, RepaymentSchedule,
)
from src.models.master import ChargeMaster, CollectionRuleMaster
from src.services.schedule_generator import next_working_day

log = get_logger(__name__)
_ZERO = Decimal("0")
_DEFAULT_BOUNCE_CHARGE = Decimal("500.00")
_DEFAULT_BOUNCE_GST = Decimal("90.00")
_GST_RATE = Decimal("0.18")


async def _get_bounce_charge(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[Decimal, Decimal]:
    today = date.today()
    result = await session.execute(
        select(ChargeMaster)
        .where(
            ChargeMaster.charge_code == "BOUNCE_CHARGE",
            ChargeMaster.effective_from <= today,
            (ChargeMaster.effective_till.is_(None)) | (ChargeMaster.effective_till > today),
            ChargeMaster.is_active.is_(True),
            (ChargeMaster.tenant_id == tenant_id) | (ChargeMaster.tenant_id.is_(None)),
        )
        .order_by(ChargeMaster.tenant_id.nulls_last())
        .limit(1)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        return _DEFAULT_BOUNCE_CHARGE, _DEFAULT_BOUNCE_GST

    charge = Decimal(str(rule.fixed_amount or _DEFAULT_BOUNCE_CHARGE))
    gst = charge * (Decimal(str(rule.gst_rate)) / 100) if rule.gst_applicable else _ZERO
    from decimal import ROUND_HALF_UP
    return charge, gst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _get_collection_rule(
    session: AsyncSession, tenant_id: uuid.UUID, dpd: int
) -> Optional[CollectionRuleMaster]:
    today = date.today()
    result = await session.execute(
        select(CollectionRuleMaster)
        .where(
            CollectionRuleMaster.dpd_from <= dpd,
            CollectionRuleMaster.dpd_to >= dpd,
            CollectionRuleMaster.effective_from <= today,
            (CollectionRuleMaster.effective_till.is_(None)) | (CollectionRuleMaster.effective_till > today),
            CollectionRuleMaster.is_active.is_(True),
            (CollectionRuleMaster.tenant_id == tenant_id) | (CollectionRuleMaster.tenant_id.is_(None)),
        )
        .order_by(CollectionRuleMaster.tenant_id.nulls_last())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def handle_bounce(
    session: AsyncSession,
    loan_id: uuid.UUID,
    schedule_id: uuid.UUID,
    mandate_id: Optional[uuid.UUID],
    gateway_ref: str,
    bounce_reason: str,
    attempt_no: int,
) -> BounceEvent:
    # Idempotency — silent ack if already processed
    dup_result = await session.execute(
        select(BounceEvent).where(BounceEvent.gateway_ref == gateway_ref)
    )
    existing = dup_result.scalar_one_or_none()
    if existing:
        return existing

    loan_result = await session.execute(
        select(Loan).where(Loan.id == loan_id).with_for_update()
    )
    loan = loan_result.scalar_one_or_none()
    if not loan:
        raise NotFoundError(f"Loan {loan_id} not found")

    sched_result = await session.execute(
        select(RepaymentSchedule).where(RepaymentSchedule.id == schedule_id)
    )
    schedule = sched_result.scalar_one_or_none()
    if not schedule:
        raise NotFoundError(f"Schedule {schedule_id} not found")

    bounce_charge, bounce_gst = await _get_bounce_charge(session, loan.tenant_id)

    # balance_due (python-side)
    balance_due = (
        schedule.emi_amount
        + schedule.bounce_charge + schedule.bounce_gst
        + schedule.penalty_amt + schedule.penalty_gst
        - schedule.waiver_amt
        - schedule.total_paid
    )

    today = date.today()

    bounce_event = BounceEvent(
        loan_id=loan_id,
        schedule_id=schedule_id,
        mandate_id=mandate_id,
        tenant_id=loan.tenant_id,
        attempt_no=attempt_no,
        attempted_at=datetime.now(timezone.utc),
        amount_attempted=balance_due,
        bounce_reason=bounce_reason,
        gateway_ref=gateway_ref,
        bounce_charge=bounce_charge,
        bounce_gst=bounce_gst,
    )
    session.add(bounce_event)

    # Apply to schedule + loan
    schedule.bounce_charge += bounce_charge
    schedule.bounce_gst += bounce_gst
    schedule.status = "overdue"
    loan.total_bounce_charges += bounce_charge + bounce_gst

    # Ledger
    session.add(LoanLedger(
        loan_id=loan.id,
        tenant_id=loan.tenant_id,
        schedule_id=schedule_id,
        entry_type="bounce_charge",
        debit=bounce_charge + bounce_gst,
        credit=_ZERO,
        running_balance=loan.outstanding_principal,
        narration=f"NACH/UPI bounce — attempt {attempt_no} | reason: {bounce_reason}",
        effective_date=today,
        reference_no=gateway_ref,
    ))

    # Retry scheduling via collection rules
    collection_rule = await _get_collection_rule(session, loan.tenant_id, loan.dpd)
    retry_count = collection_rule.enach_retry_count if collection_rule else 2
    retry_gap = collection_rule.enach_retry_gap_days if collection_rule else 2

    if attempt_no <= retry_count:
        from datetime import timedelta
        retry_date = await next_working_day(
            session, today + timedelta(days=retry_gap), loan.tenant_id
        )
        session.add(EmiDebitRetryQueue(
            tenant_id=loan.tenant_id,
            loan_id=loan.id,
            schedule_id=schedule_id,
            mandate_id=mandate_id,
            retry_date=retry_date,
            attempt_no=attempt_no + 1,
            reason="bounce",
        ))

    await write_audit_log(
        session,
        tenant_id=loan.tenant_id,
        actor_id=SYSTEM_ACTOR_ID,
        actor_role=SYSTEM_ROLE,
        action="bounce_recorded",
        entity_type="loan",
        entity_id=loan.id,
        payload_after={
            "schedule_id": str(schedule_id),
            "gateway_ref": gateway_ref,
            "bounce_reason": bounce_reason,
            "attempt_no": attempt_no,
            "charge_applied": str(bounce_charge),
        },
    )
    await session.commit()
    await session.refresh(bounce_event)
    log.warning(
        "bounce_recorded",
        loan_id=str(loan_id),
        schedule_id=str(schedule_id),
        gateway_ref=gateway_ref,
        bounce_reason=bounce_reason,
        attempt_no=attempt_no,
    )
    return bounce_event


async def process_retry_queue(session: AsyncSession) -> dict:
    """enach_retry cron — re-presents debits queued for today."""
    today = date.today()
    result = await session.execute(
        select(EmiDebitRetryQueue)
        .where(
            EmiDebitRetryQueue.retry_date == today,
            EmiDebitRetryQueue.processed.is_(False),
        )
    )
    retries = result.scalars().all()
    processed = 0
    for retry in retries:
        # Mark processed — actual debit presentation is handled by the
        # eNACH/UPI vendor integration layer (out of scope for this engine)
        retry.processed = True
        retry.processed_at = datetime.now(timezone.utc)
        processed += 1

    await session.commit()
    return {"processed": processed, "date": str(today)}
