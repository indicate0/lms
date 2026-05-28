"""
Daily interest accrual engine — §4.2 of LMS_LLD.md.
Runs daily at 00:05 IST via cron trigger.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.models.loan import Loan, LoanLedger

log = get_logger(__name__)
_ZERO = Decimal("0")
_TWO = Decimal("0.01")


def _round2(v: Decimal) -> Decimal:
    return v.quantize(_TWO, rounding=ROUND_HALF_UP)


async def run_interest_accrual_cron(session: AsyncSession) -> dict:
    today = date.today()
    result = await session.execute(
        select(Loan)
        .where(Loan.status == "active")
        .with_for_update(skip_locked=True)
    )
    loans = result.scalars().all()

    processed = 0
    for loan in loans:
        daily_rate = Decimal(str(loan.roi_monthly)) / 100 / 30
        daily_int = _round2(Decimal(str(loan.outstanding_principal)) * daily_rate)

        if daily_int <= _ZERO:
            continue

        loan.accrued_interest = (loan.accrued_interest or _ZERO) + daily_int

        session.add(
            LoanLedger(
                loan_id=loan.id,
                tenant_id=loan.tenant_id,
                entry_type="interest_due",
                debit=daily_int,
                credit=_ZERO,
                running_balance=loan.outstanding_principal,
                narration="Daily interest accrual",
                effective_date=today,
            )
        )
        processed += 1

    await session.commit()
    log.info("interest_accrual_complete", processed=processed, date=str(today))
    return {"processed": processed, "date": str(today)}
