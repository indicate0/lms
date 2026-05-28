import math
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import Permission, Principal, get_current_principal, require, require_any, require_roles, Role
from src.db.session import get_db
from src.schemas.loan import (
    LedgerEntryResponse,
    LoanDisbursedEvent,
    LoanResponse,
    OutstandingResponse,
    PaginatedResponse,
    ScheduleInstallmentResponse,
)
from src.services import loan_service

router = APIRouter()


@router.post(
    "",
    response_model=LoanResponse,
    status_code=201,
    dependencies=[Depends(require_roles(Role.SYSTEM, Role.INTEGRATION))],
)
async def ingest_disbursed_event(
    event: LoanDisbursedEvent,
    db: AsyncSession = Depends(get_db),
):
    """Internal — called by the Kafka consumer when loan.disbursed arrives from LOS."""
    loan = await loan_service.create_loan_from_disbursed_event(db, event)
    return LoanResponse.model_validate(loan)


@router.get(
    "/{loan_id}",
    response_model=LoanResponse,
    dependencies=[Depends(require_any(Permission.LOAN_VIEW_OWN, Permission.LOAN_VIEW_ALL))],
)
async def get_loan(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    loan = await loan_service.get_loan(db, loan_id)
    # Scope enforcement: BORROWER can only view their own loan
    if principal.scope == "own" and loan.customer_id != principal.customer_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error": "SCOPE_VIOLATION", "message": "Access denied"})
    return LoanResponse.model_validate(loan)


@router.get(
    "/{loan_id}/schedule",
    response_model=PaginatedResponse,
    dependencies=[Depends(require_any(Permission.LOAN_VIEW_OWN, Permission.LOAN_VIEW_ALL))],
)
async def get_schedule(
    loan_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    await loan_service.get_loan(db, loan_id)
    items, total = await loan_service.get_schedule(db, loan_id, page, limit)
    return PaginatedResponse(
        items=[ScheduleInstallmentResponse.model_validate(i) for i in items],
        total=total, page=page, limit=limit,
        pages=math.ceil(total / limit) if total else 0,
    )


@router.get(
    "/{loan_id}/ledger",
    response_model=PaginatedResponse,
    dependencies=[Depends(require_any(Permission.LOAN_VIEW_OWN, Permission.LOAN_VIEW_ALL))],
)
async def get_ledger(
    loan_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await loan_service.get_loan(db, loan_id)
    items, total = await loan_service.get_ledger(db, loan_id, page, limit, from_date, to_date)
    return PaginatedResponse(
        items=[LedgerEntryResponse.model_validate(i) for i in items],
        total=total, page=page, limit=limit,
        pages=math.ceil(total / limit) if total else 0,
    )


@router.get(
    "/{loan_id}/outstanding",
    response_model=OutstandingResponse,
    dependencies=[Depends(require_any(Permission.LOAN_VIEW_OWN, Permission.LOAN_VIEW_ALL))],
)
async def get_outstanding(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return await loan_service.get_outstanding(db, loan_id)
