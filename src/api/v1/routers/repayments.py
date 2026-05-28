import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import Permission, require, require_any
from src.db.session import get_db
from src.models.loan import RepaymentSchedule
from src.schemas.loan import ScheduleInstallmentResponse
from src.schemas.payment import PaymentRequest, PaymentResponse
from src.services import payment_service

router = APIRouter()


@router.post(
    "/pay",
    response_model=PaymentResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.PAYMENT_POST))],
)
async def post_payment(
    req: PaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    payment = await payment_service.post_payment(
        session=db,
        loan_id=req.loan_id,
        amount=req.amount,
        channel=req.channel,
        payment_type=req.payment_type,
        utr_ref=req.utr_ref,
        gateway_ref=req.gateway_ref,
        payer_account=req.payer_account,
    )
    return PaymentResponse.model_validate(payment)


@router.get(
    "/{loan_id}/next-due",
    response_model=ScheduleInstallmentResponse | None,
    dependencies=[Depends(require_any(Permission.LOAN_VIEW_OWN, Permission.LOAN_VIEW_ALL))],
)
async def get_next_due(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepaymentSchedule)
        .where(
            RepaymentSchedule.loan_id == loan_id,
            RepaymentSchedule.status.in_(["pending", "partial", "overdue"]),
        )
        .order_by(RepaymentSchedule.due_date.asc())
        .limit(1)
    )
    inst = result.scalar_one_or_none()
    return ScheduleInstallmentResponse.model_validate(inst) if inst else None


@router.get(
    "/{loan_id}/overdue",
    response_model=list[ScheduleInstallmentResponse],
    dependencies=[Depends(require_any(Permission.LOAN_VIEW_OWN, Permission.LOAN_VIEW_ALL))],
)
async def get_overdue(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepaymentSchedule)
        .where(
            RepaymentSchedule.loan_id == loan_id,
            RepaymentSchedule.status.in_(["overdue", "partial"]),
        )
        .order_by(RepaymentSchedule.due_date.asc())
    )
    return [ScheduleInstallmentResponse.model_validate(i) for i in result.scalars().all()]
