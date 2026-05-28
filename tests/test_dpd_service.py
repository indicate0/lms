"""Tests for DPD engine, SMA classification, and NPA auto-trigger."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import update

from src.models.loan import RepaymentSchedule
from src.services.dpd_service import recalculate_dpd
from tests.conftest import seed_active_loan


async def test_no_overdue_dpd_is_zero(session):
    loan = await seed_active_loan(session)
    await recalculate_dpd(session, loan)
    assert loan.dpd == 0
    assert loan.sma_category is None


async def test_dpd_calculated_from_oldest_overdue(session):
    loan = await seed_active_loan(session)
    overdue_date = date.today() - timedelta(days=15)

    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=overdue_date)
    )
    await session.flush()

    await recalculate_dpd(session, loan)
    assert loan.dpd == 15
    assert loan.sma_category == "SMA-0"


async def test_sma1_at_dpd_45(session):
    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=45))
    )
    await session.flush()
    await recalculate_dpd(session, loan)
    assert loan.sma_category == "SMA-1"


async def test_sma2_at_dpd_75(session):
    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=75))
    )
    await session.flush()
    await recalculate_dpd(session, loan)
    assert loan.sma_category == "SMA-2"


async def test_npa_triggered_at_dpd_91(session):
    """DPD > 90 must auto-classify loan as NPA."""
    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=91))
    )
    await session.flush()
    await recalculate_dpd(session, loan)

    assert loan.status == "npa"
    assert loan.npa_since is not None
    assert loan.npa_classification == "sub_standard"
    assert loan.provision_pct == Decimal("10.0")
    assert loan.sma_category is None  # SMA cleared when NPA


async def test_npa_not_triggered_at_dpd_90(session):
    """DPD exactly 90 is SMA-2, not NPA."""
    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=90))
    )
    await session.flush()
    await recalculate_dpd(session, loan)

    assert loan.status == "active"
    assert loan.dpd == 90


async def test_total_overdue_reflects_unpaid_installments(session):
    loan = await seed_active_loan(session)
    from sqlalchemy import select
    from src.models.loan import RepaymentSchedule as RS

    result = await session.execute(
        select(RS).where(RS.loan_id == loan.id).order_by(RS.installment_no).limit(2)
    )
    insts = result.scalars().all()
    for inst in insts:
        inst.status = "overdue"
        inst.due_date = date.today() - timedelta(days=10)
    await session.flush()

    await recalculate_dpd(session, loan)
    assert loan.total_overdue > Decimal("0")
