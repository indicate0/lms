"""Tests for NPA provisioning update and NPA upgrade engine."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update

from src.models.loan import RepaymentSchedule
from src.services.dpd_service import recalculate_dpd
from src.services.npa_service import run_npa_upgrade_check, run_provisioning_update
from tests.conftest import seed_active_loan


async def _make_npa_loan(session, dpd_days=91):
    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=dpd_days))
    )
    await session.flush()
    await recalculate_dpd(session, loan)
    assert loan.status == "npa"
    return loan


# ── Provisioning update ───────────────────────────────────────────────────────

async def test_provisioning_update_classifies_sub_standard(session):
    loan = await _make_npa_loan(session, dpd_days=91)
    result = await run_provisioning_update(session)
    assert result["updated"] >= 1

    await session.refresh(loan)
    assert loan.npa_classification == "sub_standard"
    assert loan.provision_pct == Decimal("10.0")


async def test_provisioning_update_classifies_doubtful_1(session):
    """Simulate a loan that's been NPA for over a year."""
    loan = await _make_npa_loan(session, dpd_days=91)
    # Manually backdate npa_since to 400 days ago
    loan.npa_since = date.today() - timedelta(days=400)
    await session.flush()

    await run_provisioning_update(session)
    await session.refresh(loan)
    assert loan.npa_classification == "doubtful_1"
    assert loan.provision_pct == Decimal("25.0")


async def test_provisioning_update_creates_npa_provisioning_row(session):
    from sqlalchemy import select
    from src.models.loan import NpaProvisioning

    loan = await _make_npa_loan(session)
    await run_provisioning_update(session)

    result = await session.execute(
        select(NpaProvisioning).where(NpaProvisioning.loan_id == loan.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].classification == "sub_standard"


async def test_provisioning_update_skips_active_loans(session):
    loan = await seed_active_loan(session)
    before_pct = loan.provision_pct
    await run_provisioning_update(session)
    await session.refresh(loan)
    # Active loan must not be touched
    assert loan.provision_pct == before_pct


# ── NPA upgrade check ─────────────────────────────────────────────────────────

async def test_npa_upgrade_skipped_if_overdues_not_cleared(session):
    loan = await _make_npa_loan(session)
    result = await run_npa_upgrade_check(session)
    assert result["skipped_not_cleared"] >= 1
    await session.refresh(loan)
    assert loan.status == "npa"


async def test_npa_upgrade_skipped_if_no_clearance_date(session):
    """NPA loan where no installment was ever overdue-when-paid."""
    loan = await _make_npa_loan(session)
    # Zero out overdues so condition 1 passes
    loan.total_overdue = Decimal("0")
    loan.accrued_interest = Decimal("0")
    loan.total_penalty = Decimal("0")
    await session.flush()

    result = await run_npa_upgrade_check(session)
    # Should skip because there's no arrear clearance date
    assert result["skipped_no_clearance_date"] >= 1


async def test_npa_upgrade_skipped_if_quarter_not_met(session):
    """Overdue cleared but not 3 on-time installments yet."""
    from sqlalchemy import select as sa_select
    from src.models.loan import RepaymentSchedule as RS

    loan = await _make_npa_loan(session)
    loan.total_overdue = Decimal("0")
    loan.accrued_interest = Decimal("0")
    loan.total_penalty = Decimal("0")

    # Mark one overdue installment as paid recently (within 3 months)
    result = await session.execute(
        sa_select(RS).where(RS.loan_id == loan.id, RS.installment_no == 1)
    )
    inst = result.scalar_one()
    inst.status = "paid"
    inst.dpd_on_payment = 5  # was overdue when paid
    inst.paid_at = date.today() - timedelta(days=30)  # only 1 month ago
    await session.flush()

    upgrade_result = await run_npa_upgrade_check(session)
    assert upgrade_result["skipped_quarter_not_met"] >= 1
    await session.refresh(loan)
    assert loan.status == "npa"
