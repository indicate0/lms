"""
DPD engine & SMA classifier — §4.5 of LMS_LLD.md.

Runs as a cron (daily 00:30 IST) but recalculate_dpd() is also called
inline after every payment posting so DPD is always current.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import LoanLedger, NpaProvisioning, RepaymentSchedule

log = get_logger(__name__)

if TYPE_CHECKING:
    from src.models.loan import Loan

_ZERO = Decimal("0")


async def recalculate_dpd(session: AsyncSession, loan: "Loan") -> None:
    today = date.today()

    # Mark newly-overdue pending installments
    await session.execute(
        update(RepaymentSchedule)
        .where(
            RepaymentSchedule.loan_id == loan.id,
            RepaymentSchedule.due_date < today,
            RepaymentSchedule.status == "pending",
        )
        .values(status="overdue")
    )

    # Oldest unsettled installment
    oldest_result = await session.execute(
        select(func.min(RepaymentSchedule.due_date)).where(
            RepaymentSchedule.loan_id == loan.id,
            RepaymentSchedule.status.in_(["overdue", "partial"]),
        )
    )
    oldest_due: date | None = oldest_result.scalar_one_or_none()

    if oldest_due is None:
        dpd = 0
        loan.first_default_date = None
    else:
        if loan.first_default_date is None:
            loan.first_default_date = oldest_due
        dpd = (today - oldest_due).days

    # SMA classification
    if dpd == 0:
        sma = None
    elif dpd <= 30:
        sma = "SMA-0"
    elif dpd <= 60:
        sma = "SMA-1"
    elif dpd <= 90:
        sma = "SMA-2"
    else:
        sma = None  # NPA overrides SMA

    # Authoritative total_overdue
    overdue_sum_result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    RepaymentSchedule.emi_amount
                    + RepaymentSchedule.bounce_charge
                    + RepaymentSchedule.bounce_gst
                    + RepaymentSchedule.penalty_amt
                    + RepaymentSchedule.penalty_gst
                    - RepaymentSchedule.waiver_amt
                    - RepaymentSchedule.total_paid
                ),
                Decimal("0"),
            )
        ).where(
            RepaymentSchedule.loan_id == loan.id,
            RepaymentSchedule.status.in_(["overdue", "partial"]),
        )
    )
    total_overdue: Decimal = overdue_sum_result.scalar_one()

    loan.dpd = dpd
    loan.sma_category = sma
    loan.total_overdue = total_overdue

    if dpd > 90 and loan.status not in ("npa", "written_off", "closed"):
        await _mark_npa(session, loan, dpd)


async def _mark_npa(session: AsyncSession, loan: "Loan", dpd: int) -> None:
    from datetime import timedelta

    today = date.today()
    npa_since = (loan.first_default_date + timedelta(days=90)) if loan.first_default_date else today

    loan.status = "npa"
    loan.npa_since = npa_since
    loan.npa_classification = "sub_standard"
    loan.provision_pct = Decimal("10.0")
    loan.provision_amount = loan.outstanding_principal * Decimal("0.10")
    loan.sma_category = None

    session.add(
        LoanLedger(
            loan_id=loan.id,
            tenant_id=loan.tenant_id,
            entry_type="npa_classification",
            debit=_ZERO,
            credit=_ZERO,
            running_balance=loan.outstanding_principal,
            narration=f"Account classified NPA — DPD {dpd}",
            effective_date=today,
        )
    )
    await write_audit_log(
        session,
        tenant_id=loan.tenant_id,
        actor_id=SYSTEM_ACTOR_ID,
        actor_role=SYSTEM_ROLE,
        action="npa_classified",
        entity_type="loan",
        entity_id=loan.id,
        payload_after={
            "dpd": dpd,
            "npa_since": str(npa_since),
            "outstanding_principal": str(loan.outstanding_principal),
            "provision_pct": str(loan.provision_pct),
        },
    )
    log.warning(
        "npa_classified",
        loan_id=str(loan.id),
        dpd=dpd,
        npa_since=str(npa_since),
        outstanding_principal=str(loan.outstanding_principal),
    )


async def run_dpd_cron(session: AsyncSession) -> dict:
    """Full daily DPD cron — processes all active loans."""
    from src.models.loan import Loan
    from sqlalchemy import select

    result = await session.execute(
        select(Loan).where(Loan.status == "active").with_for_update(skip_locked=True)
    )
    loans = result.scalars().all()

    processed = 0
    for loan in loans:
        await recalculate_dpd(session, loan)
        processed += 1

    await session.commit()
    log.info("dpd_cron_complete", processed=processed, date=str(date.today()))
    return {"processed": processed, "date": str(date.today())}
