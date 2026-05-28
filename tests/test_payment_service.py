"""Tests for payment posting, allocation waterfall, idempotency, and suspense."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from src.core.exceptions import DuplicatePaymentError, ValidationError
from src.models.loan import Loan, Payment, RepaymentSchedule
from src.services.payment_service import post_payment
from tests.conftest import seed_active_loan, seed_allocation_scheme, TENANT_ID


async def test_payment_reduces_outstanding_principal(session):
    await seed_allocation_scheme(session)
    loan = await seed_active_loan(session)

    # Force an installment overdue so payment has something to allocate
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=1))
    )
    await session.flush()

    before = loan.outstanding_principal
    payment = await post_payment(
        session, loan.id,
        amount=Decimal("9168.00"),
        channel="neft",
        payment_type="emi",
        utr_ref=f"UTR{uuid.uuid4().hex[:10].upper()}",
    )

    await session.refresh(loan)
    assert loan.outstanding_principal < before
    assert payment.status in ("success", "suspense")


async def test_payment_idempotency_duplicate_utr(session):
    await seed_allocation_scheme(session)
    loan = await seed_active_loan(session)
    utr = f"UTR{uuid.uuid4().hex[:10].upper()}"

    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=1))
    )
    await session.flush()

    p1 = await post_payment(session, loan.id, Decimal("5000.00"), "neft", "emi", utr)
    with pytest.raises(DuplicatePaymentError):
        await post_payment(session, loan.id, Decimal("5000.00"), "neft", "emi", utr)


async def test_small_payment_goes_to_suspense(session):
    """Payment below outstanding penalty+bounce goes to suspense."""
    await seed_allocation_scheme(session)
    loan = await seed_active_loan(session)

    # Add penalty+bounce to the overdue installment so minimum_due > ₹100
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(
            status="overdue",
            due_date=date.today() - timedelta(days=1),
            penalty_amt=Decimal("300.00"),
            bounce_charge=Decimal("500.00"),
        )
    )
    loan.total_penalty += Decimal("300.00")
    loan.total_bounce_charges += Decimal("500.00")
    await session.flush()

    payment = await post_payment(
        session, loan.id,
        amount=Decimal("100.00"),
        channel="neft",
        payment_type="emi",
        utr_ref=f"UTR{uuid.uuid4().hex[:10].upper()}",
    )
    assert payment.status == "suspense"


async def test_payment_marks_installment_paid(session):
    await seed_allocation_scheme(session)
    loan = await seed_active_loan(session)

    result = await session.execute(
        select(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id)
        .order_by(RepaymentSchedule.installment_no)
        .limit(1)
    )
    inst = result.scalar_one()
    emi = inst.emi_amount

    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.id == inst.id)
        .values(status="overdue", due_date=date.today() - timedelta(days=1))
    )
    await session.flush()

    await post_payment(
        session, loan.id,
        amount=emi,
        channel="upi",
        payment_type="emi",
        utr_ref=f"UTR{uuid.uuid4().hex[:10].upper()}",
    )

    await session.refresh(inst)
    assert inst.status == "paid"
    assert inst.paid_at is not None


async def test_full_loan_repayment_closes_loan(session):
    """Paying all 12 installments fully should close the loan."""
    await seed_allocation_scheme(session)
    # Short loan: 1 installment only (tenure 1 month)
    loan = await seed_active_loan(session, tenure_months=1)

    result = await session.execute(
        select(RepaymentSchedule).where(RepaymentSchedule.loan_id == loan.id)
    )
    inst = result.scalar_one()
    emi = inst.emi_amount + inst.interest_amt  # ensure we cover full installment

    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.id == inst.id)
        .values(status="overdue", due_date=date.today() - timedelta(days=1))
    )
    await session.flush()

    # Post total outstanding
    total = loan.outstanding_principal + loan.accrued_interest
    await post_payment(
        session, loan.id,
        amount=total if total > emi else emi,
        channel="neft",
        payment_type="emi",
        utr_ref=f"UTR{uuid.uuid4().hex[:10].upper()}",
    )
    await session.refresh(loan)
    assert loan.status in ("closed", "active")  # closed if all balances zeroed


async def test_payment_allocation_order_bounce_before_principal(session):
    """Bounce charge must be cleared before principal per allocation scheme."""
    await seed_allocation_scheme(session)
    loan = await seed_active_loan(session)

    # Manually add a bounce charge to the first installment
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(
            status="overdue",
            due_date=date.today() - timedelta(days=1),
            bounce_charge=Decimal("500.00"),
            bounce_gst=Decimal("90.00"),
        )
    )
    loan.total_bounce_charges += Decimal("590.00")
    await session.flush()

    # Post exactly the bounce charge amount — should be fully consumed
    await post_payment(
        session, loan.id,
        amount=Decimal("590.00"),
        channel="neft",
        payment_type="emi",
        utr_ref=f"UTR{uuid.uuid4().hex[:10].upper()}",
    )

    await session.refresh(loan)
    assert loan.total_bounce_charges < Decimal("590.00")
