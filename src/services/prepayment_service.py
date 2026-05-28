"""
Part-prepayment engine — §4.12 of LMS_LLD.md.

Flow:
  1. Eligibility check (product rules + lock-in)
  2. Compute prepayment charge from charge_master
  3. Post payment via allocation engine
  4. Recalculate remaining schedule (reduce_tenure | reduce_emi)
  5. Soft-delete old schedule, insert revised schedule
  6. Update loan master + ledger
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import LoanNotActiveError, NotFoundError, ValidationError
from src.models.loan import Loan, LoanLedger, PartPrepaymentRequest, RepaymentSchedule
from src.models.master import ChargeMaster, ProductMaster
from src.services.schedule_generator import generate_schedule, next_working_day

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_GST = Decimal("0.18")


def _round2(v: Decimal) -> Decimal:
    return v.quantize(_TWO, rounding=ROUND_HALF_UP)


async def _get_product(
    session: AsyncSession, tenant_id: uuid.UUID, product_code: str
) -> Optional[ProductMaster]:
    today = date.today()
    result = await session.execute(
        select(ProductMaster)
        .where(
            ProductMaster.product_code == product_code,
            ProductMaster.effective_from <= today,
            (ProductMaster.effective_till.is_(None)) | (ProductMaster.effective_till > today),
            ProductMaster.is_active.is_(True),
            (ProductMaster.tenant_id == tenant_id) | (ProductMaster.tenant_id.is_(None)),
        )
        .order_by(ProductMaster.tenant_id.nulls_last())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_prepay_charge_rule(
    session: AsyncSession, tenant_id: uuid.UUID
) -> Optional[ChargeMaster]:
    today = date.today()
    result = await session.execute(
        select(ChargeMaster)
        .where(
            ChargeMaster.charge_code == "PART_PREPAYMENT_CHARGE",
            ChargeMaster.effective_from <= today,
            (ChargeMaster.effective_till.is_(None)) | (ChargeMaster.effective_till > today),
            ChargeMaster.is_active.is_(True),
            (ChargeMaster.tenant_id == tenant_id) | (ChargeMaster.tenant_id.is_(None)),
        )
        .order_by(ChargeMaster.tenant_id.nulls_last())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_prepayment_quote(
    session: AsyncSession,
    loan_id: uuid.UUID,
    prepay_amount: Decimal,
    customer_choice: str,
) -> PartPrepaymentRequest:
    loan_result = await session.execute(select(Loan).where(Loan.id == loan_id))
    loan = loan_result.scalar_one_or_none()
    if not loan:
        raise NotFoundError(f"Loan {loan_id} not found")
    if loan.status != "active":
        raise LoanNotActiveError(f"Loan {loan_id} is not active")

    product = await _get_product(session, loan.tenant_id, loan.product_code)

    # Eligibility
    if product and not product.part_prepayment_allowed:
        raise ValidationError("Part-prepayment is not allowed for this product")

    if product and product.part_prepayment_lock_months > 0:
        months_elapsed = (
            relativedelta(date.today(), loan.disbursal_date).years * 12
            + relativedelta(date.today(), loan.disbursal_date).months
        )
        if months_elapsed < product.part_prepayment_lock_months:
            raise ValidationError(
                f"Prepayment locked for first {product.part_prepayment_lock_months} months"
            )

    if product and product.part_prepayment_min_pct:
        min_amount = _round2(
            Decimal(str(loan.outstanding_principal))
            * Decimal(str(product.part_prepayment_min_pct)) / 100
        )
        if prepay_amount < min_amount:
            raise ValidationError(f"Minimum prepayment amount is ₹{min_amount}")

    # Compute charge
    charge_rule = await _get_prepay_charge_rule(session, loan.tenant_id)
    prepay_charge = _ZERO
    gst_amount = _ZERO

    if charge_rule:
        if charge_rule.calc_type == "flat":
            prepay_charge = _round2(Decimal(str(charge_rule.fixed_amount or 0)))
        elif charge_rule.calc_type == "pct_outstanding":
            prepay_charge = _round2(
                Decimal(str(loan.outstanding_principal))
                * Decimal(str(charge_rule.pct_rate or 0)) / 100
            )
        elif charge_rule.calc_type == "pct_emi":
            # get first pending EMI amount
            emi_result = await session.execute(
                select(RepaymentSchedule)
                .where(RepaymentSchedule.loan_id == loan_id, RepaymentSchedule.status == "pending")
                .order_by(RepaymentSchedule.due_date)
                .limit(1)
            )
            emi_row = emi_result.scalar_one_or_none()
            emi_amount = Decimal(str(emi_row.emi_amount)) if emi_row else _ZERO
            prepay_charge = _round2(emi_amount * Decimal(str(charge_rule.pct_rate or 0)) / 100)

        gst_rate = Decimal(str(charge_rule.gst_rate)) / 100 if charge_rule.gst_applicable else _ZERO
        gst_amount = _round2(prepay_charge * gst_rate)

    total_payable = prepay_amount + prepay_charge + gst_amount
    new_outstanding = Decimal(str(loan.outstanding_principal)) - (prepay_amount - prepay_charge - gst_amount)

    req = PartPrepaymentRequest(
        loan_id=loan_id,
        tenant_id=loan.tenant_id,
        request_date=date.today(),
        prepay_amount=prepay_amount,
        prepay_charge=prepay_charge,
        gst_on_charge=gst_amount,
        total_payable=total_payable,
        new_outstanding=new_outstanding,
        recalc_option=customer_choice,
        status="pending",
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


async def process_prepayment(
    session: AsyncSession,
    prepayment_request_id: uuid.UUID,
    utr_ref: str,
    channel: str = "neft",
) -> Loan:
    req_result = await session.execute(
        select(PartPrepaymentRequest).where(PartPrepaymentRequest.id == prepayment_request_id)
    )
    req = req_result.scalar_one_or_none()
    if not req:
        raise NotFoundError(f"Prepayment request {prepayment_request_id} not found")
    if req.status != "pending":
        raise ValidationError(f"Prepayment request is already {req.status}")

    loan_result = await session.execute(
        select(Loan).where(Loan.id == req.loan_id).with_for_update()
    )
    loan = loan_result.scalar_one_or_none()

    # Post payment via allocation engine
    from src.services.payment_service import post_payment
    await post_payment(
        session=session,
        loan_id=loan.id,
        amount=req.total_payable,
        channel=channel,
        payment_type="part_prepayment",
        utr_ref=utr_ref,
    )

    # Re-fetch loan after payment
    await session.refresh(loan)
    net_prepaid = req.prepay_amount - req.prepay_charge - req.gst_on_charge
    new_outstanding = Decimal(str(loan.outstanding_principal))

    # Soft-delete pending schedules
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.status == "pending")
        .values(status="revised")
    )

    # Recalculate schedule
    pending_result = await session.execute(
        select(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.status == "revised")
        .order_by(RepaymentSchedule.installment_no)
    )
    old_schedules = pending_result.scalars().all()
    remaining_count = len(old_schedules)

    if remaining_count == 0:
        # Fully paid by prepayment — close loan
        loan.status = "closed"
        loan.closed_at = datetime.now(timezone.utc)
        loan.closure_type = "normal_repayment"
    else:
        # Create a temporary loan-like object to feed into the schedule generator
        class _LoanProxy:
            pass

        proxy = _LoanProxy()
        proxy.id = loan.id
        proxy.tenant_id = loan.tenant_id
        proxy.principal = new_outstanding
        proxy.outstanding_principal = new_outstanding
        proxy.interest_type = loan.interest_type
        proxy.roi_monthly = loan.roi_monthly
        proxy.roi_daily = loan.roi_daily
        proxy.disbursal_date = old_schedules[0].due_date  # first pending due = "start"

        if req.recalc_option == "reduce_tenure":
            # Keep original EMI, shorten tenure
            original_emi = old_schedules[0].emi_amount
            r = Decimal(str(loan.roi_monthly)) / 100
            import math
            if r > 0 and original_emi > new_outstanding * r:
                n = math.ceil(
                    math.log(float(original_emi / (original_emi - new_outstanding * r)))
                    / math.log(float(1 + r))
                )
            else:
                n = remaining_count
            proxy.tenure_months = n
            proxy.tenure_days = None
        else:
            # reduce_emi: keep same tenure
            proxy.tenure_months = remaining_count
            proxy.tenure_days = None

        proxy.maturity_date = loan.maturity_date  # will be updated after schedule gen

        new_schedules = await generate_schedule(session, proxy)  # type: ignore[arg-type]
        session.add_all(new_schedules)

        # Update loan maturity date
        if new_schedules:
            loan.maturity_date = new_schedules[-1].due_date
        loan.outstanding_principal = new_outstanding

    today = date.today()
    session.add(LoanLedger(
        loan_id=loan.id, tenant_id=loan.tenant_id,
        entry_type="part_prepayment",
        debit=net_prepaid, credit=_ZERO,
        running_balance=loan.outstanding_principal,
        narration=f"Part-prepayment | option={req.recalc_option}",
        effective_date=today, reference_no=utr_ref,
    ))
    if req.prepay_charge > _ZERO:
        session.add(LoanLedger(
            loan_id=loan.id, tenant_id=loan.tenant_id,
            entry_type="prepayment_charge",
            debit=req.prepay_charge + req.gst_on_charge, credit=_ZERO,
            running_balance=loan.outstanding_principal,
            narration="Part-prepayment charge + GST",
            effective_date=today,
        ))

    req.status = "schedule_revised"
    req.completed_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(loan)
    return loan
