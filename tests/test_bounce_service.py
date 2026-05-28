"""Tests for bounce handling and retry queue."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from src.models.loan import BounceEvent, EmiDebitRetryQueue, RepaymentSchedule
from src.models.master import ChargeMaster, CollectionRuleMaster
from src.services.bounce_service import handle_bounce, process_retry_queue
from tests.conftest import seed_active_loan, TENANT_ID


_SYS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _seed_bounce_infra(session):
    session.add(ChargeMaster(
        tenant_id=TENANT_ID,
        charge_code="BOUNCE_CHARGE",
        charge_name="Bounce Charge",
        calc_type="fixed",
        fixed_amount=Decimal("500.00"),
        gst_applicable=True,
        gst_rate=Decimal("18"),
        effective_from=date.today(),
        created_by=_SYS_UUID,
    ))
    session.add(CollectionRuleMaster(
        tenant_id=TENANT_ID,
        dpd_from=0,
        dpd_to=90,
        sma_bucket="SMA-0",
        action_type="enach_retry",
        enach_retry_count=2,
        enach_retry_gap_days=3,
        notify_guarantor=False,
        effective_from=date.today(),
        created_by=_SYS_UUID,
    ))
    await session.flush()


async def _get_first_installment(session, loan_id):
    result = await session.execute(
        select(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan_id)
        .order_by(RepaymentSchedule.installment_no)
        .limit(1)
    )
    return result.scalar_one()


async def test_handle_bounce_creates_event(session):
    await _seed_bounce_infra(session)
    loan = await seed_active_loan(session)
    inst = await _get_first_installment(session, loan.id)

    bounce = await handle_bounce(
        session,
        loan_id=loan.id,
        schedule_id=inst.id,
        mandate_id=None,
        gateway_ref=f"GREF{uuid.uuid4().hex[:10].upper()}",
        bounce_reason="insufficient_funds",
        attempt_no=1,
    )

    assert bounce.loan_id == loan.id
    assert bounce.bounce_reason == "insufficient_funds"


async def test_handle_bounce_applies_charge_to_loan(session):
    await _seed_bounce_infra(session)
    loan = await seed_active_loan(session)
    inst = await _get_first_installment(session, loan.id)
    before = loan.total_bounce_charges

    await handle_bounce(
        session,
        loan_id=loan.id,
        schedule_id=inst.id,
        mandate_id=None,
        gateway_ref=f"GREF{uuid.uuid4().hex[:10].upper()}",
        bounce_reason="insufficient_funds",
        attempt_no=1,
    )

    await session.refresh(loan)
    assert loan.total_bounce_charges > before


async def test_handle_bounce_is_idempotent_on_gateway_ref(session):
    await _seed_bounce_infra(session)
    loan = await seed_active_loan(session)
    inst = await _get_first_installment(session, loan.id)
    ref = f"GREF{uuid.uuid4().hex[:10].upper()}"

    b1 = await handle_bounce(session, loan.id, inst.id, None, ref, "insufficient_funds", 1)

    # Second call with same gateway_ref should return the existing event, not create a new one
    b2 = await handle_bounce(session, loan.id, inst.id, None, ref, "insufficient_funds", 1)
    assert b1.id == b2.id


async def test_handle_bounce_queues_retry(session):
    await _seed_bounce_infra(session)
    loan = await seed_active_loan(session)
    inst = await _get_first_installment(session, loan.id)

    await handle_bounce(
        session,
        loan_id=loan.id,
        schedule_id=inst.id,
        mandate_id=None,
        gateway_ref=f"GREF{uuid.uuid4().hex[:10].upper()}",
        bounce_reason="insufficient_funds",
        attempt_no=1,
    )

    result = await session.execute(
        select(EmiDebitRetryQueue).where(EmiDebitRetryQueue.loan_id == loan.id)
    )
    retries = result.scalars().all()
    assert len(retries) >= 1
    assert retries[0].attempt_no == 2


async def test_process_retry_queue_marks_processed(session):
    from sqlalchemy import select as sa_select
    from src.models.loan import EmiDebitRetryQueue as Q, RepaymentSchedule

    loan = await seed_active_loan(session)
    sched_result = await session.execute(
        sa_select(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id)
        .limit(1)
    )
    sched = sched_result.scalar_one()

    session.add(Q(
        tenant_id=TENANT_ID,
        loan_id=loan.id,
        schedule_id=sched.id,
        retry_date=date.today(),
        attempt_no=2,
        reason="bounce",
    ))
    await session.flush()

    result = await process_retry_queue(session)
    assert result["processed"] >= 1
