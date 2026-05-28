"""
Foreclosure engine — §4.8 of LMS_LLD.md.

RBI rule: zero foreclosure charge on floating-rate loans to individual borrowers.
Fixed-rate: charge read from charge_master (FORECLOSURE_CHARGE).
Surcharge: extra 1% within first 3 months of disbursal.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import LoanNotActiveError, NotFoundError, ValidationError
from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import (
    ForeclosureRequest, Loan, LoanLedger, NocQueue, Payment, RepaymentSchedule,
)
from src.models.master import ChargeMaster
from src.services.schedule_generator import next_working_day

log = get_logger(__name__)
_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_GST = Decimal("0.18")
_CENT = Decimal("0.01")


def _round2(v: Decimal) -> Decimal:
    return v.quantize(_TWO, rounding=ROUND_HALF_UP)


async def _get_charge(
    session: AsyncSession, tenant_id: uuid.UUID, charge_code: str
) -> Optional[ChargeMaster]:
    today = date.today()
    result = await session.execute(
        select(ChargeMaster)
        .where(
            ChargeMaster.charge_code == charge_code,
            ChargeMaster.effective_from <= today,
            (ChargeMaster.effective_till.is_(None)) | (ChargeMaster.effective_till > today),
            ChargeMaster.is_active.is_(True),
            (ChargeMaster.tenant_id == tenant_id) | (ChargeMaster.tenant_id.is_(None)),
        )
        .order_by(ChargeMaster.tenant_id.nulls_last())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def generate_foreclosure_quote(
    session: AsyncSession, loan_id: uuid.UUID
) -> ForeclosureRequest:
    result = await session.execute(select(Loan).where(Loan.id == loan_id))
    loan = result.scalar_one_or_none()
    if not loan:
        raise NotFoundError(f"Loan {loan_id} not found")
    if loan.status != "active":
        raise LoanNotActiveError(f"Loan {loan_id} is not active (status={loan.status})")

    today = date.today()

    # Foreclosure charge — zero for floating-rate (RBI mandate)
    fc_charge = _ZERO
    gst_on_fc = _ZERO

    if loan.rate_type != "floating":
        charge_rule = await _get_charge(session, loan.tenant_id, "FORECLOSURE_CHARGE")
        if charge_rule:
            if charge_rule.calc_type == "flat":
                fc_charge = _round2(Decimal(str(charge_rule.fixed_amount or 0)))
            elif charge_rule.calc_type == "pct_outstanding":
                rate = Decimal(str(charge_rule.pct_rate or 0)) / 100
                fc_charge = _round2(Decimal(str(loan.outstanding_principal)) * rate)

            # 1% surcharge within first 3 months
            months_active = (
                relativedelta(today, loan.disbursal_date).years * 12
                + relativedelta(today, loan.disbursal_date).months
            )
            if months_active < 3:
                fc_charge += _round2(Decimal(str(loan.outstanding_principal)) * Decimal("0.01"))

            if charge_rule.max_amount:
                fc_charge = min(fc_charge, Decimal(str(charge_rule.max_amount)))
            if charge_rule.min_amount:
                fc_charge = max(fc_charge, Decimal(str(charge_rule.min_amount)))

            gst_rate = Decimal(str(charge_rule.gst_rate)) / 100 if charge_rule.gst_applicable else _ZERO
            gst_on_fc = _round2(fc_charge * gst_rate)

    total_payable = (
        Decimal(str(loan.outstanding_principal))
        + Decimal(str(loan.accrued_interest))
        + Decimal(str(loan.total_overdue))
        + fc_charge
        + gst_on_fc
    )

    # Quote valid for 3 business days
    valid_until = today
    for _ in range(3):
        valid_until = await next_working_day(session, valid_until, loan.tenant_id)
        from datetime import timedelta
        valid_until_next = valid_until + timedelta(days=1)
        valid_until = valid_until_next
    # step back one — we added one extra day in loop
    from datetime import timedelta
    valid_until = valid_until - timedelta(days=1)

    req = ForeclosureRequest(
        loan_id=loan.id,
        customer_id=loan.customer_id,
        tenant_id=loan.tenant_id,
        request_date=today,
        valid_until=valid_until,
        outstanding_principal=loan.outstanding_principal,
        accrued_interest=loan.accrued_interest,
        overdue_amount=loan.total_overdue,
        foreclosure_charge=fc_charge,
        gst_on_charge=gst_on_fc,
        total_payable=total_payable,
        status="pending",
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


async def process_foreclosure(
    session: AsyncSession,
    foreclosure_request_id: uuid.UUID,
    utr_ref: str,
    channel: str = "neft",
) -> Loan:
    """
    Accepts payment for a foreclosure quote and closes the loan.
    """
    req_result = await session.execute(
        select(ForeclosureRequest).where(ForeclosureRequest.id == foreclosure_request_id)
    )
    req = req_result.scalar_one_or_none()
    if not req:
        raise NotFoundError(f"Foreclosure request {foreclosure_request_id} not found")
    if req.status != "pending":
        raise ValidationError(f"Foreclosure request is already {req.status}")
    if req.valid_until < date.today():
        req.status = "expired"
        await session.commit()
        raise ValidationError("Foreclosure quote has expired — please generate a new quote")

    loan_result = await session.execute(
        select(Loan).where(Loan.id == req.loan_id).with_for_update()
    )
    loan = loan_result.scalar_one_or_none()

    # Post payment record
    payment = Payment(
        loan_id=loan.id,
        tenant_id=loan.tenant_id,
        amount=req.total_payable,
        channel=channel,
        payment_type="foreclosure",
        utr_ref=utr_ref,
        status="success",
        allocated_principal=req.outstanding_principal,
        allocated_interest=req.accrued_interest,
        settled_at=datetime.now(timezone.utc),
    )
    session.add(payment)
    await session.flush()

    # Update request
    req.status = "paid"
    req.payment_id = payment.id
    req.completed_at = datetime.now(timezone.utc)

    # Close loan
    loan.status = "foreclosed"
    loan.closed_at = datetime.now(timezone.utc)
    loan.closure_type = "foreclosure"
    loan.outstanding_principal = _ZERO
    loan.accrued_interest = _ZERO
    loan.total_paid += req.total_payable

    # Waive all remaining pending schedules
    await session.execute(
        select(RepaymentSchedule)
        .where(
            RepaymentSchedule.loan_id == loan.id,
            RepaymentSchedule.status.in_(["pending", "partial"]),
        )
    )
    remaining_result = await session.execute(
        select(RepaymentSchedule).where(
            RepaymentSchedule.loan_id == loan.id,
            RepaymentSchedule.status.in_(["pending", "partial"]),
        )
    )
    for sched in remaining_result.scalars().all():
        sched.status = "waived"

    today = date.today()

    # Ledger entries
    if req.foreclosure_charge > _ZERO:
        session.add(LoanLedger(
            loan_id=loan.id, tenant_id=loan.tenant_id,
            entry_type="foreclosure_charge",
            debit=req.foreclosure_charge + req.gst_on_charge,
            credit=_ZERO, running_balance=_ZERO,
            narration=f"Foreclosure charge + GST",
            effective_date=today, reference_no=utr_ref,
        ))

    session.add(LoanLedger(
        loan_id=loan.id, tenant_id=loan.tenant_id,
        payment_id=payment.id,
        entry_type="payment_received",
        debit=_ZERO, credit=req.total_payable,
        running_balance=_ZERO,
        narration=f"Foreclosure payment received via {channel}",
        effective_date=today, reference_no=utr_ref,
    ))
    session.add(LoanLedger(
        loan_id=loan.id, tenant_id=loan.tenant_id,
        entry_type="loan_closed",
        debit=_ZERO, credit=_ZERO, running_balance=_ZERO,
        narration="Loan foreclosed", effective_date=today,
    ))

    # Enqueue NOC generation
    session.add(NocQueue(
        tenant_id=loan.tenant_id, loan_id=loan.id, priority="normal",
    ))

    await write_audit_log(
        session,
        tenant_id=loan.tenant_id,
        actor_id=SYSTEM_ACTOR_ID,
        actor_role=SYSTEM_ROLE,
        action="loan_foreclosed",
        entity_type="loan",
        entity_id=loan.id,
        payload_before={"status": "active"},
        payload_after={
            "status": "foreclosed",
            "utr_ref": utr_ref,
            "total_paid": str(loan.total_paid),
        },
    )
    await session.commit()
    await session.refresh(loan)
    log.info(
        "loan_foreclosed",
        loan_id=str(loan.id),
        utr_ref=utr_ref,
        total_payable=str(req.total_payable),
    )
    return loan
