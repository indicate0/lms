"""Tests for write-off lifecycle: initiate → approve → recovery."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update

from src.core.exceptions import NotFoundError, ValidationError
from src.models.loan import RepaymentSchedule
from src.services.dpd_service import recalculate_dpd
from src.services.write_off_service import approve_write_off, initiate_write_off, post_recovery
from tests.conftest import seed_active_loan, TENANT_ID

ADMIN_ID = uuid.uuid4()
CREDIT_MGR_ID = uuid.uuid4()


async def _make_npa_loan(session):
    """Create a loan and force it to NPA status."""
    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=91))
    )
    await session.flush()
    await recalculate_dpd(session, loan)
    assert loan.status == "npa"
    return loan


async def test_initiate_write_off_creates_pending_record(session):
    loan = await _make_npa_loan(session)
    wo = await initiate_write_off(session, loan.id, "Borrower untraceable", CREDIT_MGR_ID)

    assert wo.status == "pending_approval"
    assert wo.loan_id == loan.id
    assert wo.write_off_amount > Decimal("0")
    assert wo.initiated_by == CREDIT_MGR_ID


async def test_initiate_write_off_requires_npa_status(session):
    loan = await seed_active_loan(session)
    with pytest.raises(ValidationError, match="NPA"):
        await initiate_write_off(session, loan.id, "reason", CREDIT_MGR_ID)


async def test_initiate_write_off_blocks_duplicate_pending(session):
    loan = await _make_npa_loan(session)
    await initiate_write_off(session, loan.id, "first", CREDIT_MGR_ID)

    with pytest.raises(ValidationError, match="already pending"):
        await initiate_write_off(session, loan.id, "duplicate", CREDIT_MGR_ID)


async def test_approve_write_off_closes_loan(session):
    loan = await _make_npa_loan(session)
    await initiate_write_off(session, loan.id, "NPA >180d", CREDIT_MGR_ID)

    wo = await approve_write_off(session, loan.id, "BR/2026/001", ADMIN_ID)

    await session.refresh(loan)
    assert wo.status == "approved"
    assert wo.board_resolution_ref == "BR/2026/001"
    assert loan.status == "written_off"
    assert loan.outstanding_principal == Decimal("0")
    assert loan.accrued_interest == Decimal("0")
    assert loan.closed_at is not None


async def test_approve_write_off_posts_double_entry_ledger(session):
    from sqlalchemy import select
    from src.models.loan import LoanLedger

    loan = await _make_npa_loan(session)
    await initiate_write_off(session, loan.id, "NPA >180d", CREDIT_MGR_ID)
    wo = await approve_write_off(session, loan.id, "BR/2026/002", ADMIN_ID)

    result = await session.execute(
        select(LoanLedger).where(
            LoanLedger.loan_id == loan.id,
            LoanLedger.entry_type == "write_off_debit",
        )
    )
    entry = result.scalar_one()
    assert entry.debit == wo.principal_written_off
    assert entry.reference_no == "BR/2026/002"


async def test_post_recovery_partial(session):
    loan = await _make_npa_loan(session)
    await initiate_write_off(session, loan.id, "reason", CREDIT_MGR_ID)
    wo = await approve_write_off(session, loan.id, "BR/2026/003", ADMIN_ID)

    recovery_amount = Decimal("10000.00")
    wo2 = await post_recovery(session, loan.id, recovery_amount, "RECOV001", ADMIN_ID)

    assert wo2.status == "recovered_partial"
    assert wo2.recovery_to_date == recovery_amount


async def test_post_recovery_full(session):
    loan = await _make_npa_loan(session)
    await initiate_write_off(session, loan.id, "reason", CREDIT_MGR_ID)
    wo = await approve_write_off(session, loan.id, "BR/2026/004", ADMIN_ID)
    total = wo.write_off_amount

    wo2 = await post_recovery(session, loan.id, total, "RECOV_FULL", ADMIN_ID)
    assert wo2.status == "recovered_full"


async def test_post_recovery_loan_stays_written_off(session):
    loan = await _make_npa_loan(session)
    await initiate_write_off(session, loan.id, "reason", CREDIT_MGR_ID)
    wo = await approve_write_off(session, loan.id, "BR/2026/005", ADMIN_ID)

    await post_recovery(session, loan.id, Decimal("5000.00"), "RECOV002", ADMIN_ID)

    await session.refresh(loan)
    # RBI rule: recovery never reinstates the loan
    assert loan.status == "written_off"


async def test_approve_write_off_unknown_loan_raises(session):
    with pytest.raises(NotFoundError):
        await approve_write_off(session, uuid.uuid4(), "BR/X", ADMIN_ID)
