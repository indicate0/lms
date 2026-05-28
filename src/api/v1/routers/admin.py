"""
Admin router — write-off, NPA provisioning, and NPA upgrade endpoints.
All endpoints are internal; not exposed via public gateway.
"""
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import Permission, Principal, get_current_principal, require, require_roles, Role
from src.db.session import get_db
from src.services import write_off_service, npa_service

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class WriteOffInitiateRequest(BaseModel):
    reason: str


class WriteOffApproveRequest(BaseModel):
    board_resolution_ref: str


class RecoveryRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_ref: str


class WriteOffResponse(BaseModel):
    id: uuid.UUID
    loan_id: uuid.UUID
    status: str
    write_off_amount: Decimal
    principal_written_off: Decimal
    interest_written_off: Decimal
    penalty_written_off: Decimal
    recovery_to_date: Decimal
    reason: str | None
    board_resolution_ref: str | None
    initiated_by: uuid.UUID | None
    approved_by: uuid.UUID | None

    model_config = {"from_attributes": True}


# ── Write-off (maker-checker) ──────────────────────────────────────────────────

@router.post(
    "/loans/{loan_id}/write-off",
    response_model=WriteOffResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.LOAN_WRITEOFF_INITIATE))],
)
async def initiate_write_off(
    loan_id: uuid.UUID,
    body: WriteOffInitiateRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    wo = await write_off_service.initiate_write_off(
        db, loan_id, body.reason, uuid.UUID(principal.sub) if not principal.is_internal else uuid.uuid4()
    )
    return WriteOffResponse.model_validate(wo)


@router.post(
    "/loans/{loan_id}/write-off/approve",
    response_model=WriteOffResponse,
    dependencies=[Depends(require(Permission.LOAN_WRITEOFF_APPROVE))],
)
async def approve_write_off(
    loan_id: uuid.UUID,
    body: WriteOffApproveRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    wo = await write_off_service.approve_write_off(
        db, loan_id, body.board_resolution_ref,
        uuid.UUID(principal.sub) if not principal.is_internal else uuid.uuid4()
    )
    return WriteOffResponse.model_validate(wo)


@router.post(
    "/loans/{loan_id}/recovery",
    response_model=WriteOffResponse,
    dependencies=[Depends(require(Permission.LOAN_WRITEOFF_APPROVE))],
)
async def post_recovery(
    loan_id: uuid.UUID,
    body: RecoveryRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    wo = await write_off_service.post_recovery(
        db, loan_id, body.amount, body.payment_ref,
        uuid.UUID(principal.sub) if not principal.is_internal else uuid.uuid4()
    )
    return WriteOffResponse.model_validate(wo)


# ── NPA cron triggers (internal service token only) ───────────────────────────

@router.post(
    "/cron/npa-provisioning",
    dependencies=[Depends(require_roles(Role.SYSTEM))],
)
async def trigger_npa_provisioning(db: AsyncSession = Depends(get_db)):
    return await npa_service.run_provisioning_update(db)


@router.post(
    "/cron/npa-upgrade",
    dependencies=[Depends(require_roles(Role.SYSTEM))],
)
async def trigger_npa_upgrade(db: AsyncSession = Depends(get_db)):
    return await npa_service.run_npa_upgrade_check(db)
