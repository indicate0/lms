"""
Write-Off Engine — §4.15 of LMS_LLD.md.

Two-step maker-checker flow:
  1. initiate_write_off()  — credit_manager creates the request
  2. approve_write_off()   — admin approves with board resolution reference
  3. post_recovery()       — recovery credit after write-off (does NOT reinstate loan)

RBI requirement: board-level approval mandatory for every write-off.
Loan status stays 'written_off' forever — recovery posts to P&L, not to loan.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import LoanNotActiveError, NotFoundError, ValidationError
from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import Loan, LoanLedger, LoanWriteOff

log = get_logger(__name__)
_ZERO = Decimal("0")
_CENT = Decimal("0.01")


async def initiate_write_off(
    session: AsyncSession,
    loan_id: uuid.UUID,
    reason: str,
    initiated_by: uuid.UUID,
) -> LoanWriteOff:
    """
    Creates a pending_approval write-off record.
    Only NPA loans qualify (RBI: write-off only after NPA classification).
    """
    result = await session.execute(select(Loan).where(Loan.id == loan_id))
    loan = result.scalar_one_or_none()
    if not loan:
        raise NotFoundError(f"Loan {loan_id} not found")
    if loan.status != "npa":
        raise ValidationError(
            f"Only NPA loans can be written off (current status: {loan.status})"
        )

    # Prevent duplicate pending write-off
    existing = await session.execute(
        select(LoanWriteOff).where(
            LoanWriteOff.loan_id == loan_id,
            LoanWriteOff.status == "pending_approval",
        )
    )
    if existing.scalar_one_or_none():
        raise ValidationError("A write-off request is already pending approval for this loan")

    total_outstanding = (
        loan.outstanding_principal
        + loan.accrued_interest
        + loan.total_penalty
        + loan.total_bounce_charges
    )

    wo = LoanWriteOff(
        tenant_id=loan.tenant_id,
        loan_id=loan.id,
        write_off_amount=total_outstanding,
        principal_written_off=loan.outstanding_principal,
        interest_written_off=loan.accrued_interest,
        penalty_written_off=loan.total_penalty + loan.total_bounce_charges,
        reason=reason,
        initiated_by=initiated_by,
        status="pending_approval",
    )
    session.add(wo)
    await write_audit_log(
        session,
        tenant_id=loan.tenant_id,
        actor_id=initiated_by,
        actor_role="credit_manager",
        action="write_off_initiated",
        entity_type="loan",
        entity_id=loan.id,
        payload_after={
            "write_off_amount": str(total_outstanding),
            "reason": reason,
            "status": "pending_approval",
        },
    )
    await session.commit()
    await session.refresh(wo)
    log.info(
        "write_off_initiated",
        loan_id=str(loan_id),
        write_off_amount=str(total_outstanding),
        initiated_by=str(initiated_by),
    )
    return wo


async def approve_write_off(
    session: AsyncSession,
    loan_id: uuid.UUID,
    board_resolution_ref: str,
    approved_by: uuid.UUID,
) -> LoanWriteOff:
    """
    Admin approves the write-off with a board resolution reference.
    Posts double-entry ledger, closes loan, cancels mandate.
    """
    loan_result = await session.execute(
        select(Loan).where(Loan.id == loan_id).with_for_update()
    )
    loan = loan_result.scalar_one_or_none()
    if not loan:
        raise NotFoundError(f"Loan {loan_id} not found")
    if loan.status != "npa":
        raise ValidationError(f"Loan is not in NPA status (current: {loan.status})")

    wo_result = await session.execute(
        select(LoanWriteOff).where(
            LoanWriteOff.loan_id == loan_id,
            LoanWriteOff.status == "pending_approval",
        )
    )
    wo = wo_result.scalar_one_or_none()
    if not wo:
        raise NotFoundError("No pending write-off request found — call initiate first")

    now = datetime.now(timezone.utc)
    today = date.today()

    # Update write-off record
    wo.status = "approved"
    wo.board_resolution_ref = board_resolution_ref
    wo.approved_by = approved_by
    wo.approval_date = now
    wo.write_off_date = today

    # Double-entry ledger
    # Debit: write-off loss (P&L charge)
    session.add(LoanLedger(
        loan_id=loan.id,
        tenant_id=loan.tenant_id,
        entry_type="write_off_debit",
        debit=wo.principal_written_off,
        credit=_ZERO,
        running_balance=_ZERO,
        narration=f"Write-off approved | board_res={board_resolution_ref} | principal={wo.principal_written_off}",
        effective_date=today,
        reference_no=board_resolution_ref,
    ))

    # Credit: release provision held against this loan
    if loan.provision_amount and loan.provision_amount > _ZERO:
        session.add(LoanLedger(
            loan_id=loan.id,
            tenant_id=loan.tenant_id,
            entry_type="provision_release",
            debit=_ZERO,
            credit=loan.provision_amount,
            running_balance=_ZERO,
            narration=f"Provision released on write-off | amount={loan.provision_amount}",
            effective_date=today,
        ))

    # If interest/penalty written off, record those too
    if wo.interest_written_off > _ZERO:
        session.add(LoanLedger(
            loan_id=loan.id,
            tenant_id=loan.tenant_id,
            entry_type="write_off_interest",
            debit=wo.interest_written_off,
            credit=_ZERO,
            running_balance=_ZERO,
            narration="Interest written off",
            effective_date=today,
        ))
    if wo.penalty_written_off > _ZERO:
        session.add(LoanLedger(
            loan_id=loan.id,
            tenant_id=loan.tenant_id,
            entry_type="write_off_penalty",
            debit=wo.penalty_written_off,
            credit=_ZERO,
            running_balance=_ZERO,
            narration="Penalty / bounce charges written off",
            effective_date=today,
        ))

    # Close the loan
    loan.status = "written_off"
    loan.closed_at = now
    loan.closure_type = "written_off"
    loan.outstanding_principal = _ZERO
    loan.accrued_interest = _ZERO
    loan.total_penalty = _ZERO
    loan.total_bounce_charges = _ZERO
    loan.npa_classification = loan.npa_classification  # retain for audit
    loan.provision_amount = _ZERO
    loan.provision_pct = _ZERO

    # Cancel active mandate if any
    if loan.active_mandate_id:
        from src.models.loan import Mandate
        mandate_result = await session.execute(
            select(Mandate).where(Mandate.id == loan.active_mandate_id)
        )
        mandate = mandate_result.scalar_one_or_none()
        if mandate and mandate.status not in ("cancelled", "expired"):
            mandate.status = "cancelled"
            mandate.cancellation_reason = "Loan written off"
            mandate.cancelled_at = now
        loan.active_mandate_id = None

    await write_audit_log(
        session,
        tenant_id=loan.tenant_id,
        actor_id=approved_by,
        actor_role="admin",
        action="write_off_approved",
        entity_type="loan",
        entity_id=loan.id,
        payload_before={"status": "npa"},
        payload_after={
            "status": "written_off",
            "write_off_amount": str(wo.write_off_amount),
            "board_resolution_ref": board_resolution_ref,
        },
    )
    await session.commit()
    await session.refresh(wo)
    log.info(
        "write_off_approved",
        loan_id=str(loan_id),
        write_off_amount=str(wo.write_off_amount),
        board_resolution_ref=board_resolution_ref,
        approved_by=str(approved_by),
    )
    return wo


async def post_recovery(
    session: AsyncSession,
    loan_id: uuid.UUID,
    amount: Decimal,
    payment_ref: str,
    recovered_by: uuid.UUID,
) -> LoanWriteOff:
    """
    Records a recovery payment on a written-off loan.
    Loan status stays 'written_off' — recovery flows to P&L, not to loan balance.
    """
    result = await session.execute(
        select(Loan).where(Loan.id == loan_id)
    )
    loan = result.scalar_one_or_none()
    if not loan:
        raise NotFoundError(f"Loan {loan_id} not found")
    if loan.status != "written_off":
        raise ValidationError(f"Loan is not written off (status: {loan.status})")

    wo_result = await session.execute(
        select(LoanWriteOff).where(
            LoanWriteOff.loan_id == loan_id,
            LoanWriteOff.status.in_(["approved", "recovered_partial"]),
        )
    )
    wo = wo_result.scalar_one_or_none()
    if not wo:
        raise NotFoundError("No approved write-off record found for this loan")

    today = date.today()

    # Ledger — recovery credit to P&L
    session.add(LoanLedger(
        loan_id=loan.id,
        tenant_id=loan.tenant_id,
        entry_type="recovery_credit",
        debit=_ZERO,
        credit=amount,
        running_balance=_ZERO,
        narration=f"Recovery received | ref={payment_ref}",
        effective_date=today,
        reference_no=payment_ref,
    ))

    wo.recovery_to_date += amount

    if wo.recovery_to_date >= wo.write_off_amount:
        wo.status = "recovered_full"
    else:
        wo.status = "recovered_partial"

    # loan.total_paid tracks all cash received (including post-write-off)
    loan.total_paid += amount

    await write_audit_log(
        session,
        tenant_id=loan.tenant_id,
        actor_id=recovered_by,
        actor_role="admin",
        action="recovery_posted",
        entity_type="loan",
        entity_id=loan.id,
        payload_after={
            "amount": str(amount),
            "payment_ref": payment_ref,
            "recovery_to_date": str(wo.recovery_to_date),
            "write_off_status": wo.status,
        },
    )
    await session.commit()
    await session.refresh(wo)
    log.info(
        "recovery_posted",
        loan_id=str(loan_id),
        amount=str(amount),
        payment_ref=payment_ref,
        recovery_status=wo.status,
        recovery_to_date=str(wo.recovery_to_date),
    )
    return wo
