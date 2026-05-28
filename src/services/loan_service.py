"""
Loan service — handles loan.disbursed event ingestion and read queries.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import Loan, LoanLedger, RepaymentSchedule
from src.schemas.loan import LoanDisbursedEvent, OutstandingResponse
from src.services.schedule_generator import generate_schedule

log = get_logger(__name__)


async def _generate_loan_account_number(
    session: AsyncSession, tenant_short_code: str, year: int
) -> str:
    """
    Uses a per-tenant PostgreSQL sequence as per §2.30.3.
    Creates the sequence if it doesn't exist yet (idempotent).
    """
    seq_name = f"loan_account_seq_{tenant_short_code.lower()}"
    await session.execute(
        text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START WITH 1 INCREMENT BY 1 NO CYCLE")
    )
    result = await session.execute(text(f"SELECT nextval('{seq_name}')"))
    seq_val: int = result.scalar_one()
    return f"ALMS-{year}-{seq_val:08d}"


async def create_loan_from_disbursed_event(
    session: AsyncSession, event: LoanDisbursedEvent
) -> Loan:
    """
    Consumes a loan.disbursed event from LOS:
    1. Creates the loan record
    2. Generates the repayment schedule
    3. Posts the initial loan_ledger entry
    """
    year = event.disbursal_date.year
    loan_account_number = await _generate_loan_account_number(
        session, event.tenant_short_code, year
    )
    cooling_off_until = event.disbursal_date + timedelta(days=3)

    loan = Loan(
        id=uuid.uuid4(),
        tenant_id=event.tenant_id,
        application_id=event.application_id,
        customer_id=event.customer_id,
        agent_id=event.agent_id,
        loan_account_number=loan_account_number,
        sanctioned_amount=event.sanctioned_amount,
        disbursed_amount=event.disbursed_amount,
        disbursal_utr=event.disbursal_utr,
        disbursal_date=event.disbursal_date,
        disbursal_channel=event.disbursal_channel,
        principal=event.principal,
        interest_type=event.interest_type,
        rate_type=event.rate_type,
        benchmark_code=event.benchmark_code,
        product_code=event.product_code,
        product_type=event.product_type,
        roi_monthly=event.roi_monthly,
        roi_daily=event.roi_daily,
        tenure_months=event.tenure_months,
        tenure_days=event.tenure_days,
        maturity_date=event.maturity_date,
        outstanding_principal=event.principal,
        accrued_interest=Decimal("0"),
        total_overdue=Decimal("0"),
        total_penalty=Decimal("0"),
        total_bounce_charges=Decimal("0"),
        total_paid=Decimal("0"),
        cooling_off_until=cooling_off_until,
        status="active",
        dpd=0,
    )
    session.add(loan)
    await session.flush()  # get loan.id before generating schedule

    schedule = await generate_schedule(session, loan)
    session.add_all(schedule)

    # Opening ledger entry
    session.add(
        LoanLedger(
            loan_id=loan.id,
            tenant_id=loan.tenant_id,
            entry_type="principal_due",
            debit=loan.principal,
            credit=Decimal("0"),
            running_balance=loan.outstanding_principal,
            narration="Loan disbursed — principal booked",
            effective_date=loan.disbursal_date,
            reference_no=loan.disbursal_utr,
        )
    )

    await write_audit_log(
        session,
        tenant_id=loan.tenant_id,
        actor_id=SYSTEM_ACTOR_ID,
        actor_role=SYSTEM_ROLE,
        action="loan_created",
        entity_type="loan",
        entity_id=loan.id,
        payload_after={
            "loan_account_number": loan.loan_account_number,
            "principal": str(loan.principal),
            "tenure_months": loan.tenure_months,
            "status": loan.status,
        },
    )
    await session.commit()
    await session.refresh(loan)
    log.info(
        "loan_created",
        loan_id=str(loan.id),
        loan_account_number=loan.loan_account_number,
        principal=str(loan.principal),
        tenant_id=str(loan.tenant_id),
    )
    return loan


async def get_loan(session: AsyncSession, loan_id: uuid.UUID) -> Loan:
    result = await session.execute(select(Loan).where(Loan.id == loan_id))
    loan = result.scalar_one_or_none()
    if not loan:
        raise NotFoundError(f"Loan {loan_id} not found")
    return loan


async def get_schedule(
    session: AsyncSession, loan_id: uuid.UUID, page: int, limit: int
) -> tuple[list[RepaymentSchedule], int]:
    offset = (page - 1) * limit
    count_result = await session.execute(
        select(func.count()).where(RepaymentSchedule.loan_id == loan_id)
    )
    total = count_result.scalar_one()
    result = await session.execute(
        select(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan_id)
        .order_by(RepaymentSchedule.installment_no)
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all(), total


async def get_ledger(
    session: AsyncSession,
    loan_id: uuid.UUID,
    page: int,
    limit: int,
    from_date: Optional[date],
    to_date: Optional[date],
) -> tuple[list[LoanLedger], int]:
    offset = (page - 1) * limit
    filters = [LoanLedger.loan_id == loan_id]
    if from_date:
        filters.append(LoanLedger.effective_date >= from_date)
    if to_date:
        filters.append(LoanLedger.effective_date <= to_date)

    count_result = await session.execute(select(func.count()).where(*filters))
    total = count_result.scalar_one()
    result = await session.execute(
        select(LoanLedger)
        .where(*filters)
        .order_by(LoanLedger.effective_date.desc(), LoanLedger.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all(), total


async def get_outstanding(session: AsyncSession, loan_id: uuid.UUID) -> OutstandingResponse:
    loan = await get_loan(session, loan_id)
    total_payable = (
        loan.outstanding_principal
        + loan.accrued_interest
        + loan.total_penalty
        + loan.total_bounce_charges
    )
    return OutstandingResponse(
        loan_id=loan.id,
        loan_account_number=loan.loan_account_number,
        outstanding_principal=loan.outstanding_principal,
        accrued_interest=loan.accrued_interest,
        total_penalty=loan.total_penalty,
        total_bounce_charges=loan.total_bounce_charges,
        total_overdue=loan.total_overdue,
        total_payable=total_payable,
    )
