"""
NOC Generation Engine + Loan Closure Detector — §4.9 and §4.13 of LMS_LLD.md.

NOC generation is stubbed: in production this calls a PDF microservice,
uploads to S3, and delivers to the customer. Here we mark the record and
write the ledger entry — the delivery layer is plugged in separately.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import Loan, LoanLedger, NocQueue

log = get_logger(__name__)
_ZERO = Decimal("0")
_CENT = Decimal("0.01")


async def process_noc_queue(session: AsyncSession) -> dict:
    """
    noc_generation_queue cron — runs every 30 min.
    Picks pending NOC jobs and marks them done (PDF delivery is external).
    """
    result = await session.execute(
        select(NocQueue)
        .where(NocQueue.status == "pending")
        .order_by(NocQueue.priority.desc(), NocQueue.created_at.asc())
        .limit(50)
        .with_for_update(skip_locked=True)
    )
    jobs = result.scalars().all()

    processed = 0
    failed = 0
    today = date.today()

    for job in jobs:
        job.status = "processing"
        job.attempts += 1
        job.last_attempted_at = datetime.now(timezone.utc)

        try:
            loan_result = await session.execute(
                select(Loan).where(Loan.id == job.loan_id)
            )
            loan = loan_result.scalar_one_or_none()

            if not loan:
                job.status = "failed"
                job.error_reason = "Loan not found"
                failed += 1
                continue

            if loan.outstanding_principal > _CENT:
                job.status = "failed"
                job.error_reason = f"Loan still has outstanding ₹{loan.outstanding_principal}"
                failed += 1
                continue

            # In production: call PDF service, upload to S3, email/WhatsApp customer
            # For now: mark as issued and write ledger entry
            s3_key = f"loans/{loan.id}/noc/{today.isoformat()}.pdf"
            loan.noc_generated_at = datetime.now(timezone.utc)
            loan.noc_s3_key = s3_key

            session.add(LoanLedger(
                loan_id=loan.id,
                tenant_id=loan.tenant_id,
                entry_type="noc_issued",
                debit=_ZERO,
                credit=_ZERO,
                running_balance=_ZERO,
                narration=f"NOC generated | s3_key={s3_key}",
                effective_date=today,
            ))

            job.status = "completed"
            processed += 1

        except Exception as e:
            job.status = "failed"
            job.error_reason = str(e)[:500]
            failed += 1

    await session.commit()
    log.info("noc_queue_processed", processed=processed, failed=failed, date=str(today))
    return {"processed": processed, "failed": failed, "date": str(today)}


async def run_closure_detector(session: AsyncSession) -> dict:
    """
    Loan closure detector cron — §4.13, runs daily at 02:00 IST.
    Catches edge cases (₹0.01 rounding residual) that payment engine may miss.
    """
    result = await session.execute(
        select(Loan)
        .where(
            Loan.status == "active",
            Loan.outstanding_principal <= _CENT,
            Loan.accrued_interest <= _CENT,
            Loan.total_overdue <= _CENT,
            Loan.total_penalty <= _CENT,
        )
        .with_for_update(skip_locked=True)
    )
    candidates = result.scalars().all()

    closed = 0
    today = date.today()

    for loan in candidates:
        # Re-check inside lock
        if (
            loan.outstanding_principal <= _CENT
            and loan.accrued_interest <= _CENT
            and loan.total_overdue <= _CENT
            and loan.total_penalty <= _CENT
        ):
            loan.status = "closed"
            loan.closure_type = "normal_repayment"
            loan.closed_at = datetime.now(timezone.utc)

            session.add(LoanLedger(
                loan_id=loan.id,
                tenant_id=loan.tenant_id,
                entry_type="loan_closed",
                debit=_ZERO,
                credit=_ZERO,
                running_balance=_ZERO,
                narration="Loan auto-closed by closure detector",
                effective_date=today,
            ))

            session.add(NocQueue(
                tenant_id=loan.tenant_id,
                loan_id=loan.id,
                priority="normal",
            ))
            closed += 1

    await session.commit()
    log.info("closure_detector_complete", closed=closed, date=str(today))
    return {"closed": closed, "date": str(today)}
