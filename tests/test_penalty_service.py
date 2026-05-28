"""Tests for penalty accrual engine."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, update

from src.models.loan import PenaltyLedger, RepaymentSchedule
from src.services.penalty_service import accrue_penalty_for_loan
from tests.conftest import seed_active_loan


async def _make_overdue_loan(session, dpd_days):
    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=dpd_days))
    )
    loan.dpd = dpd_days
    await session.flush()
    return loan


async def test_no_penalty_when_no_overdue(session):
    loan = await seed_active_loan(session)
    await accrue_penalty_for_loan(session, loan, date.today())

    result = await session.execute(
        select(PenaltyLedger).where(PenaltyLedger.loan_id == loan.id)
    )
    assert result.scalars().all() == []


async def test_penalty_accrues_at_dpd_15(session):
    """DPD 1–29: 2%/month penal charge."""
    loan = await _make_overdue_loan(session, dpd_days=15)
    today = date.today()
    await accrue_penalty_for_loan(session, loan, today)

    result = await session.execute(
        select(PenaltyLedger).where(PenaltyLedger.loan_id == loan.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].penalty_amount > Decimal("0")


async def test_penalty_rate_increases_at_dpd_30(session):
    """DPD 30+: 3%/month — higher than DPD 1–29 rate."""
    loan_early = await _make_overdue_loan(session, dpd_days=15)
    loan_late = await _make_overdue_loan(session, dpd_days=35)
    today = date.today()

    await accrue_penalty_for_loan(session, loan_early, today)
    await accrue_penalty_for_loan(session, loan_late, today)

    r1 = await session.execute(
        select(PenaltyLedger).where(PenaltyLedger.loan_id == loan_early.id)
    )
    r2 = await session.execute(
        select(PenaltyLedger).where(PenaltyLedger.loan_id == loan_late.id)
    )
    p1 = r1.scalar_one().penalty_amount
    p2 = r2.scalar_one().penalty_amount
    # Both loans have same principal; DPD-30+ rate is 1.5× DPD-1-29 rate
    assert p2 > p1


async def test_penalty_is_idempotent_same_day(session):
    """Running accrual twice on the same day must not double-charge."""
    loan = await _make_overdue_loan(session, dpd_days=15)
    today = date.today()

    await accrue_penalty_for_loan(session, loan, today)
    await accrue_penalty_for_loan(session, loan, today)  # second call

    result = await session.execute(
        select(PenaltyLedger).where(PenaltyLedger.loan_id == loan.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1  # only one row for today


async def test_legal_charge_at_dpd_60(session):
    """DPD == 60: ₹500 flat legal notice charge applied once."""
    loan = await _make_overdue_loan(session, dpd_days=60)
    today = date.today()
    await accrue_penalty_for_loan(session, loan, today)

    result = await session.execute(
        select(PenaltyLedger).where(
            PenaltyLedger.loan_id == loan.id,
            PenaltyLedger.penalty_type == "legal_charge",
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].penalty_amount == Decimal("500.00")
