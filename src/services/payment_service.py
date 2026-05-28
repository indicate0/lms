"""
Payment posting & allocation engine — §4.4 of LMS_LLD.md.

Waterfall order is driven by payment_allocation_schemes table (§2.30).
Falls back to emi_loan scheme when the loan's product_type has no override.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import DuplicatePaymentError, LoanNotActiveError, NotFoundError
from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import Loan, LoanLedger, Payment, PaymentSuspense, RepaymentSchedule
from src.models.master import PaymentAllocationScheme
from src.services.dpd_service import recalculate_dpd

log = get_logger(__name__)
_ZERO = Decimal("0")
_CENT = Decimal("0.01")


async def _load_scheme(
    session: AsyncSession, tenant_id: uuid.UUID, product_type: Optional[str]
) -> list[str]:
    """Return ordered list of bucket names for this product_type."""
    for ptype in [product_type or "emi_loan", "emi_loan"]:
        result = await session.execute(
            select(PaymentAllocationScheme.bucket)
            .where(
                PaymentAllocationScheme.tenant_id == tenant_id,
                PaymentAllocationScheme.product_type == ptype,
                PaymentAllocationScheme.is_active.is_(True),
            )
            .order_by(PaymentAllocationScheme.step_order)
        )
        buckets = result.scalars().all()
        if buckets:
            return list(buckets)
    # hard fallback if table is empty (new tenant, no seed)
    return ["penalty", "bounce", "overdue_interest", "overdue_principal", "interest", "principal"]


async def post_payment(
    session: AsyncSession,
    loan_id: uuid.UUID,
    amount: Decimal,
    channel: str,
    payment_type: str,
    utr_ref: Optional[str] = None,
    gateway_ref: Optional[str] = None,
    payer_account: Optional[str] = None,
) -> Payment:
    # ── Idempotency ────────────────────────────────────────────────────────
    if utr_ref:
        dup = await session.execute(
            select(Payment).where(
                Payment.utr_ref == utr_ref,
                Payment.status == "success",
            )
        )
        if dup.scalar_one_or_none():
            raise DuplicatePaymentError(f"Payment with UTR {utr_ref} already processed")

    # ── Lock loan ─────────────────────────────────────────────────────────
    result = await session.execute(
        select(Loan).where(Loan.id == loan_id).with_for_update()
    )
    loan = result.scalar_one_or_none()
    if not loan:
        raise NotFoundError(f"Loan {loan_id} not found")
    if loan.status not in ("active", "npa"):
        raise LoanNotActiveError(f"Loan {loan_id} has status '{loan.status}'")

    # ── Merge any held suspense ────────────────────────────────────────────
    suspense_result = await session.execute(
        select(PaymentSuspense).where(
            PaymentSuspense.loan_id == loan_id,
            PaymentSuspense.status == "holding",
        )
    )
    suspense = suspense_result.scalar_one_or_none()
    effective_amount = amount
    if suspense:
        effective_amount += suspense.amount
        suspense.status = "released"
        suspense.released_at = datetime.now(timezone.utc)

    # ── Create payment record ──────────────────────────────────────────────
    payment = Payment(
        loan_id=loan_id,
        tenant_id=loan.tenant_id,
        amount=amount,
        channel=channel,
        payment_type=payment_type,
        utr_ref=utr_ref,
        gateway_ref=gateway_ref,
        payer_account=payer_account,
        status="initiated",
    )
    session.add(payment)
    await session.flush()

    # ── Partial payment guard ─────────────────────────────────────────────
    oldest_overdue_result = await session.execute(
        select(RepaymentSchedule)
        .where(
            RepaymentSchedule.loan_id == loan_id,
            RepaymentSchedule.status.in_(["overdue", "partial"]),
        )
        .order_by(RepaymentSchedule.due_date.asc())
        .limit(1)
    )
    oldest = oldest_overdue_result.scalar_one_or_none()
    if oldest:
        minimum_due = (
            oldest.penalty_amt + oldest.penalty_gst
            + oldest.bounce_charge + oldest.bounce_gst
            - oldest.waiver_amt
        )
        if effective_amount < minimum_due and minimum_due > _ZERO:
            session.add(
                PaymentSuspense(
                    tenant_id=loan.tenant_id,
                    loan_id=loan_id,
                    amount=amount,
                    source_payment_id=payment.id,
                )
            )
            payment.status = "suspense"
            if suspense:
                suspense.released_to_payment_id = payment.id
            await session.commit()
            await session.refresh(payment)
            return payment

    # ── Load allocation scheme ─────────────────────────────────────────────
    scheme = await _load_scheme(session, loan.tenant_id, loan.product_type)

    # ── Outstanding installments (oldest first) ───────────────────────────
    installs_result = await session.execute(
        select(RepaymentSchedule)
        .where(
            RepaymentSchedule.loan_id == loan_id,
            RepaymentSchedule.status.in_(["overdue", "partial", "pending"]),
        )
        .order_by(RepaymentSchedule.due_date.asc())
    )
    installments = list(installs_result.scalars().all())

    remaining = effective_amount
    alloc = {"principal": _ZERO, "interest": _ZERO, "penalty": _ZERO, "bounce": _ZERO}

    for inst in installments:
        if remaining <= _ZERO:
            break
        waived = inst.waiver_amt or _ZERO
        remaining_before_inst = remaining

        for bucket in scheme:
            if remaining <= _ZERO:
                break

            if bucket == "penalty":
                due = inst.penalty_amt + inst.penalty_gst - waived
                if due > _ZERO:
                    settled = min(remaining, due)
                    alloc["penalty"] += settled
                    remaining -= settled
                    inst.penalty_amt = max(_ZERO, inst.penalty_amt - settled)

            elif bucket == "bounce":
                due = inst.bounce_charge + inst.bounce_gst
                if due > _ZERO:
                    settled = min(remaining, due)
                    alloc["bounce"] += settled
                    remaining -= settled
                    inst.bounce_charge = max(_ZERO, inst.bounce_charge - settled)

            elif bucket in ("interest", "overdue_interest"):
                due = inst.interest_amt
                if due > _ZERO:
                    settled = min(remaining, due)
                    alloc["interest"] += settled
                    remaining -= settled
                    inst.interest_amt = max(_ZERO, inst.interest_amt - settled)

            elif bucket in ("principal", "overdue_principal"):
                due = inst.principal_amt
                if due > _ZERO:
                    settled = min(remaining, due)
                    alloc["principal"] += settled
                    remaining -= settled
                    inst.principal_amt = max(_ZERO, inst.principal_amt - settled)

        # amount applied specifically to this installment
        inst.total_paid += remaining_before_inst - remaining

        # recompute balance_due check (balance_due is a generated column in DB,
        # but we use python calc here to decide status)
        balance = (
            inst.emi_amount
            + inst.bounce_charge + inst.bounce_gst
            + inst.penalty_amt + inst.penalty_gst
            - inst.waiver_amt
            - inst.total_paid
        )
        if balance <= _CENT:
            inst.status = "paid"
            inst.paid_at = datetime.now(timezone.utc)
            inst.dpd_on_payment = loan.dpd
        else:
            inst.status = "partial"

    excess = remaining

    # ── Update loan totals ────────────────────────────────────────────────
    loan.outstanding_principal = max(_ZERO, loan.outstanding_principal - alloc["principal"])
    loan.accrued_interest = max(_ZERO, loan.accrued_interest - alloc["interest"])
    loan.total_penalty = max(_ZERO, loan.total_penalty - alloc["penalty"])
    loan.total_bounce_charges = max(_ZERO, loan.total_bounce_charges - alloc["bounce"])
    loan.total_paid += amount

    # ── Stamp allocation on payment ───────────────────────────────────────
    payment.allocated_principal = alloc["principal"]
    payment.allocated_interest = alloc["interest"]
    payment.allocated_penalty = alloc["penalty"]
    payment.allocated_bounce = alloc["bounce"]
    payment.excess_amount = excess
    payment.status = "success"
    payment.settled_at = datetime.now(timezone.utc)

    # ── Ledger entry ──────────────────────────────────────────────────────
    session.add(
        LoanLedger(
            loan_id=loan.id,
            tenant_id=loan.tenant_id,
            payment_id=payment.id,
            entry_type="payment_received",
            credit=amount,
            debit=_ZERO,
            running_balance=loan.outstanding_principal,
            narration=f"Payment via {channel} | principal={alloc['principal']} interest={alloc['interest']} penalty={alloc['penalty']} bounce={alloc['bounce']} excess={excess}",
            effective_date=date.today(),
            reference_no=utr_ref,
            allocation_scheme=loan.product_type or "emi_loan",
        )
    )

    # ── Auto-close if fully paid ──────────────────────────────────────────
    if loan.outstanding_principal <= _CENT:
        loan.status = "closed"
        loan.closed_at = datetime.now(timezone.utc)
        loan.closure_type = "normal_repayment"
        session.add(
            LoanLedger(
                loan_id=loan.id,
                tenant_id=loan.tenant_id,
                entry_type="loan_closed",
                credit=_ZERO,
                debit=_ZERO,
                running_balance=_ZERO,
                narration="Loan closed — fully repaid",
                effective_date=date.today(),
            )
        )

    await session.flush()

    # ── Recalculate DPD ───────────────────────────────────────────────────
    if loan.status == "active":
        await recalculate_dpd(session, loan)

    if suspense:
        suspense.released_to_payment_id = payment.id

    await write_audit_log(
        session,
        tenant_id=loan.tenant_id,
        actor_id=SYSTEM_ACTOR_ID,
        actor_role=SYSTEM_ROLE,
        action="payment_posted",
        entity_type="payment",
        entity_id=payment.id,
        payload_after={
            "loan_id": str(loan.id),
            "amount": str(payment.amount),
            "channel": payment.channel,
            "utr_ref": payment.utr_ref,
            "status": payment.status,
        },
    )
    await session.commit()
    await session.refresh(payment)
    log.info(
        "payment_posted",
        loan_id=str(loan.id),
        payment_id=str(payment.id),
        amount=str(payment.amount),
        channel=payment.channel,
        status=payment.status,
    )
    return payment
