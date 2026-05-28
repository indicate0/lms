"""
Penalty accrual engine — §4.6 of LMS_LLD.md.

Rates:
  DPD 1–29  : late_payment        — 2%/month  = 0.02/30 per day
  DPD 30+   : penal_interest_dpd30 — 3%/month = 0.03/30 per day
  DPD == 60 : legal_notice_charge  — ₹500 flat + ₹90 GST (once-off)

RBI Penal Charges Circular (Aug 2023 / Jan 2024):
  - Cannot be capitalised onto principal
  - Separate line item; disclosed in KFS
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import LoanLedger, PenaltyLedger, RepaymentSchedule

log = get_logger(__name__)

if TYPE_CHECKING:
    from src.models.loan import Loan

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_GST_RATE = Decimal("0.18")
_RATE_DPD1_29 = Decimal("0.02") / 30
_RATE_DPD30_PLUS = Decimal("0.03") / 30
_LEGAL_CHARGE = Decimal("500.00")
_LEGAL_GST = Decimal("90.00")


def _round2(v: Decimal) -> Decimal:
    return v.quantize(_TWO, rounding=ROUND_HALF_UP)


async def accrue_penalty_for_loan(
    session: AsyncSession, loan: "Loan", today: date
) -> None:
    """Accrue daily penalty on all overdue/partial installments for one loan."""
    result = await session.execute(
        select(RepaymentSchedule).where(
            RepaymentSchedule.loan_id == loan.id,
            RepaymentSchedule.status.in_(["overdue", "partial"]),
            RepaymentSchedule.due_date < today,
        )
    )
    installments = result.scalars().all()

    for inst in installments:
        dpd = (today - inst.due_date).days

        # Idempotency — skip if already accrued today
        existing = await session.execute(
            select(PenaltyLedger).where(
                PenaltyLedger.loan_id == loan.id,
                PenaltyLedger.schedule_id == inst.id,
                PenaltyLedger.accrual_date == today,
            )
        )
        if existing.scalar_one_or_none():
            continue

        # Balance due on this installment (python-side since balance_due is generated)
        balance_due = (
            inst.emi_amount
            + inst.bounce_charge + inst.bounce_gst
            + inst.penalty_amt + inst.penalty_gst
            - inst.waiver_amt
            - inst.total_paid
        )
        if balance_due <= _ZERO:
            continue

        if dpd <= 29:
            daily_rate = _RATE_DPD1_29
            penalty_type = "late_payment"
        else:
            daily_rate = _RATE_DPD30_PLUS
            penalty_type = "penal_interest_dpd30"

        penalty = _round2(balance_due * daily_rate)
        gst = _round2(penalty * _GST_RATE)

        session.add(
            PenaltyLedger(
                loan_id=loan.id,
                schedule_id=inst.id,
                tenant_id=loan.tenant_id,
                accrual_date=today,
                dpd_on_date=dpd,
                overdue_amount=balance_due,
                penalty_rate_pct=daily_rate * 100,
                penalty_amount=penalty,
                gst_amount=gst,
                penalty_type=penalty_type,
            )
        )

        inst.penalty_amt += penalty
        inst.penalty_gst += gst
        loan.total_penalty += penalty + gst

        # Legal notice charge — once-off when DPD hits exactly 60
        if dpd == 60:
            session.add(
                PenaltyLedger(
                    loan_id=loan.id,
                    schedule_id=inst.id,
                    tenant_id=loan.tenant_id,
                    accrual_date=today,
                    dpd_on_date=dpd,
                    overdue_amount=balance_due,
                    penalty_rate_pct=_ZERO,
                    penalty_amount=_LEGAL_CHARGE,
                    gst_amount=_LEGAL_GST,
                    penalty_type="legal_charge",
                )
            )
            inst.penalty_amt += _LEGAL_CHARGE
            inst.penalty_gst += _LEGAL_GST
            loan.total_penalty += _LEGAL_CHARGE + _LEGAL_GST

            session.add(
                LoanLedger(
                    loan_id=loan.id,
                    tenant_id=loan.tenant_id,
                    entry_type="penalty_charge",
                    debit=_LEGAL_CHARGE + _LEGAL_GST,
                    credit=_ZERO,
                    running_balance=loan.outstanding_principal,
                    narration="Legal notice charge — DPD 60",
                    effective_date=today,
                )
            )


async def run_penalty_cron(session: AsyncSession) -> dict:
    """Full daily penalty accrual cron — §4.6."""
    from src.models.loan import Loan

    today = date.today()
    result = await session.execute(
        select(Loan)
        .where(Loan.status.in_(["active", "npa"]))
        .with_for_update(skip_locked=True)
    )
    loans = result.scalars().all()

    processed = 0
    for loan in loans:
        await accrue_penalty_for_loan(session, loan, today)
        processed += 1

    await session.commit()
    log.info("penalty_cron_complete", processed=processed, date=str(today))
    return {"processed": processed, "date": str(today)}
