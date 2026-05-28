"""Tests for foreclosure quote generation and processing."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import insert

from src.core.exceptions import LoanNotActiveError, ValidationError
from src.models.master import ChargeMaster
from src.services.foreclosure_service import generate_foreclosure_quote, process_foreclosure
from tests.conftest import seed_active_loan, TENANT_ID


_SYS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _seed_charge(session, code, pct_rate):
    """Seed a percentage-of-outstanding foreclosure charge."""
    session.add(ChargeMaster(
        tenant_id=TENANT_ID,
        charge_code=code,
        charge_name=code,
        calc_type="pct_outstanding",
        pct_rate=pct_rate,
        gst_applicable=False,
        gst_rate=Decimal("0"),
        effective_from=date.today(),
        created_by=_SYS_UUID,
    ))
    await session.flush()


async def test_foreclosure_quote_generated(session):
    await _seed_charge(session, "FORECLOSURE_CHARGE", Decimal("2"))
    loan = await seed_active_loan(session)

    req = await generate_foreclosure_quote(session, loan.id)

    assert req.status == "pending"
    assert req.loan_id == loan.id
    assert req.total_payable > Decimal("0")
    assert req.valid_until >= date.today()


async def test_foreclosure_quote_zero_charge_for_floating_rate(session):
    """RBI mandate: no foreclosure charge on floating-rate loans."""
    await _seed_charge(session, "FORECLOSURE_CHARGE", Decimal("2"))
    loan = await seed_active_loan(session, rate_type="floating")

    req = await generate_foreclosure_quote(session, loan.id)

    assert req.foreclosure_charge == Decimal("0")
    assert req.gst_on_charge == Decimal("0")


async def test_foreclosure_charge_surcharge_within_3_months(session):
    """Within first 3 months: +1% surcharge on fixed-rate loan."""
    await _seed_charge(session, "FORECLOSURE_CHARGE", Decimal("2"))  # 2% pct_outstanding
    loan = await seed_active_loan(session)

    req = await generate_foreclosure_quote(session, loan.id)
    # Disbursal is today → months_active < 3 → +1% surcharge → total 3%
    expected_charge = (loan.outstanding_principal * Decimal("0.03")).quantize(Decimal("0.01"))
    assert req.foreclosure_charge == expected_charge


async def test_foreclosure_process_closes_loan(session):
    await _seed_charge(session, "FORECLOSURE_CHARGE", Decimal("0"))  # zero charge for simplicity
    loan = await seed_active_loan(session)
    req = await generate_foreclosure_quote(session, loan.id)

    closed_loan = await process_foreclosure(
        session,
        req.id,
        utr_ref=f"UTR{uuid.uuid4().hex[:10].upper()}",
        channel="neft",
    )

    assert closed_loan.status == "foreclosed"
    assert closed_loan.outstanding_principal == Decimal("0")
    assert closed_loan.closed_at is not None


async def test_foreclosure_quote_on_npa_loan_raises(session):
    from sqlalchemy import update
    from src.models.loan import RepaymentSchedule
    from src.services.dpd_service import recalculate_dpd

    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=91))
    )
    await session.flush()
    await recalculate_dpd(session, loan)

    with pytest.raises(LoanNotActiveError):
        await generate_foreclosure_quote(session, loan.id)
