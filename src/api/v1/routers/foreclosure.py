import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import Permission, require, require_any
from src.db.session import get_db
from src.schemas.loan import LoanResponse
from src.services import foreclosure_service

router = APIRouter()


class ForeclosureQuoteResponse(BaseModel):
    id: uuid.UUID
    loan_id: uuid.UUID
    request_date: object
    valid_until: object
    outstanding_principal: Decimal
    accrued_interest: Decimal
    overdue_amount: Decimal
    foreclosure_charge: Decimal
    gst_on_charge: Decimal
    total_payable: Decimal
    status: str

    model_config = {"from_attributes": True}


class ForeclosurePayRequest(BaseModel):
    utr_ref: str
    channel: str = "neft"


@router.get(
    "/{loan_id}/quote",
    response_model=ForeclosureQuoteResponse,
    dependencies=[Depends(require_any(Permission.LOAN_VIEW_OWN, Permission.LOAN_VIEW_ALL))],
)
async def get_foreclosure_quote(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    req = await foreclosure_service.generate_foreclosure_quote(db, loan_id)
    return ForeclosureQuoteResponse.model_validate(req)


@router.post(
    "/{loan_id}/initiate",
    response_model=LoanResponse,
    dependencies=[Depends(require(Permission.PAYMENT_POST))],
)
async def initiate_foreclosure(
    loan_id: uuid.UUID,
    body: ForeclosurePayRequest,
    request_id: uuid.UUID = Query(..., description="Foreclosure request ID from /quote"),
    db: AsyncSession = Depends(get_db),
):
    loan = await foreclosure_service.process_foreclosure(db, request_id, body.utr_ref, body.channel)
    return LoanResponse.model_validate(loan)
