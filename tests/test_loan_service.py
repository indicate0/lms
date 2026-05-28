"""Tests for loan creation, schedule generation, and read queries."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.core.exceptions import NotFoundError
from src.services.loan_service import create_loan_from_disbursed_event, get_loan, get_outstanding
from src.schemas.loan import LoanDisbursedEvent
from tests.conftest import make_disbursal_event, TENANT_ID


async def test_create_loan_returns_active_loan(session):
    evt = LoanDisbursedEvent(**make_disbursal_event())
    loan = await create_loan_from_disbursed_event(session, evt)

    assert loan.status == "active"
    assert loan.outstanding_principal == Decimal("100000.00")
    assert loan.loan_account_number.startswith("ALMS-")
    assert loan.tenant_id == TENANT_ID
    assert loan.cooling_off_until == date.today() + timedelta(days=3)


async def test_create_loan_generates_repayment_schedule(session):
    from sqlalchemy import select
    from src.models.loan import RepaymentSchedule

    evt = LoanDisbursedEvent(**make_disbursal_event(tenure_months=6))
    loan = await create_loan_from_disbursed_event(session, evt)

    result = await session.execute(
        select(RepaymentSchedule).where(RepaymentSchedule.loan_id == loan.id)
    )
    installments = result.scalars().all()
    assert len(installments) == 6
    assert all(inst.status == "pending" for inst in installments)
    # EMI amounts should be positive and consistent
    emis = [inst.emi_amount for inst in installments]
    assert all(e > 0 for e in emis)


async def test_create_loan_books_opening_ledger_entry(session):
    from sqlalchemy import select
    from src.models.loan import LoanLedger

    evt = LoanDisbursedEvent(**make_disbursal_event())
    loan = await create_loan_from_disbursed_event(session, evt)

    result = await session.execute(
        select(LoanLedger).where(
            LoanLedger.loan_id == loan.id,
            LoanLedger.entry_type == "principal_due",
        )
    )
    entry = result.scalar_one()
    assert entry.debit == Decimal("100000.00")
    assert entry.reference_no == evt.disbursal_utr


async def test_create_loan_account_number_is_unique(session):
    evt1 = LoanDisbursedEvent(**make_disbursal_event())
    evt2 = LoanDisbursedEvent(**make_disbursal_event(disbursal_utr="UTR999999999999"))

    loan1 = await create_loan_from_disbursed_event(session, evt1)
    loan2 = await create_loan_from_disbursed_event(session, evt2)

    assert loan1.loan_account_number != loan2.loan_account_number


async def test_get_loan_not_found_raises(session):
    with pytest.raises(NotFoundError):
        await get_loan(session, uuid.uuid4())


async def test_get_outstanding_sums_correctly(session):
    from tests.conftest import seed_active_loan

    loan = await seed_active_loan(session)
    outstanding = await get_outstanding(session, loan.id)

    assert outstanding.outstanding_principal == Decimal("100000.00")
    assert outstanding.total_payable == Decimal("100000.00")  # no interest accrued yet


async def test_reducing_balance_emi_formula(session):
    """EMI for ₹1,00,000 @ 1.5%/mo × 12 months ≈ ₹9168.
    Disbursal on 1st of month avoids broken-period interest on installment 1.
    """
    from sqlalchemy import select
    from src.models.loan import RepaymentSchedule

    today = date.today()
    first_of_month = today.replace(day=1)
    maturity = first_of_month.replace(year=first_of_month.year + 1)

    evt = LoanDisbursedEvent(**make_disbursal_event(
        principal="100000.00",
        roi_monthly="1.50",
        tenure_months=12,
        disbursal_date=str(first_of_month),
        maturity_date=str(maturity),
    ))
    loan = await create_loan_from_disbursed_event(session, evt)

    result = await session.execute(
        select(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id)
        .order_by(RepaymentSchedule.installment_no)
    )
    installs = result.scalars().all()
    # Standard EMI formula: P×r×(1+r)^n / ((1+r)^n - 1) ≈ 9168 at 1.5%/mo × 12mo.
    # Use installment 2 (no broken-period interest) for a clean assertion.
    assert abs(installs[1].emi_amount - Decimal("9168.00")) < Decimal("1.00")

    # Sum of all principal components must equal loan principal (± rounding)
    total_principal = sum(i.principal_amt for i in installs)
    assert abs(total_principal - Decimal("100000.00")) < Decimal("1.00")


async def test_flat_rate_schedule(session):
    """Flat-rate loans: equal interest per installment."""
    from sqlalchemy import select
    from src.models.loan import RepaymentSchedule

    evt = LoanDisbursedEvent(**make_disbursal_event(
        interest_type="flat",
        principal="60000.00",
        roi_monthly="2.00",
        tenure_months=6,
    ))
    loan = await create_loan_from_disbursed_event(session, evt)

    result = await session.execute(
        select(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id)
        .order_by(RepaymentSchedule.installment_no)
    )
    installs = result.scalars().all()
    interest_amounts = [i.interest_amt for i in installs]
    # Flat rate: interest is the same each month (except possibly last due to rounding)
    assert len(set(str(i) for i in interest_amounts[:-1])) == 1
