import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import Permission, require, require_any
from src.db.session import get_db
from src.schemas.loan import LoanResponse
from src.services import prepayment_service

router = APIRouter()


class PrepaymentQuoteResponse(BaseModel):
    id: uuid.UUID
    loan_id: uuid.UUID
    request_date: object
    prepay_amount: Decimal
    prepay_charge: Decimal
    gst_on_charge: Decimal
    total_payable: Decimal
    new_outstanding: Decimal | None
    recalc_option: str | None
    status: str

    model_config = {"from_attributes": True}


class PrepaymentQuoteRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    customer_choice: str = "reduce_tenure"  # 'reduce_tenure' | 'reduce_emi'


class PrepaymentInitiateRequest(BaseModel):
    request_id: uuid.UUID
    utr_ref: str
    channel: str = "neft"


@router.post(
    "/{loan_id}/quote",
    response_model=PrepaymentQuoteResponse,
    status_code=201,
    dependencies=[Depends(require_any(Permission.LOAN_VIEW_OWN, Permission.LOAN_VIEW_ALL))],
)
async def get_prepayment_quote(
    loan_id: uuid.UUID,
    body: PrepaymentQuoteRequest,
    db: AsyncSession = Depends(get_db),
):
    req = await prepayment_service.get_prepayment_quote(
        db, loan_id, body.amount, body.customer_choice
    )
    return PrepaymentQuoteResponse.model_validate(req)


@router.post(
    "/{loan_id}/initiate",
    response_model=LoanResponse,
    dependencies=[Depends(require(Permission.PAYMENT_POST))],
)
async def initiate_prepayment(
    loan_id: uuid.UUID,
    body: PrepaymentInitiateRequest,
    db: AsyncSession = Depends(get_db),
):
    loan = await prepayment_service.process_prepayment(
        db, body.request_id, body.utr_ref, body.channel
    )
    return LoanResponse.model_validate(loan)
