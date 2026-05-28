import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class LoanDisbursedEvent(BaseModel):
    """Payload of the loan.disbursed event published by LOS."""
    application_id: uuid.UUID
    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: Optional[uuid.UUID] = None

    sanctioned_amount: Decimal
    disbursed_amount: Decimal
    disbursal_utr: str
    disbursal_date: date
    disbursal_channel: str

    principal: Decimal
    interest_type: str          # 'reducing_balance' | 'flat' | 'daily_flat'
    rate_type: str = "fixed"    # 'fixed' | 'floating'
    benchmark_code: Optional[str] = None
    product_code: str
    product_type: Optional[str] = None  # 'emi_loan' | 'bullet_loan' etc.
    roi_monthly: Decimal
    roi_daily: Optional[Decimal] = None
    tenure_months: Optional[int] = None
    tenure_days: Optional[int] = None
    maturity_date: date

    tenant_short_code: str      # used to generate loan_account_number sequence


class LoanResponse(BaseModel):
    id: uuid.UUID
    loan_account_number: str
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    status: str
    product_code: str
    product_type: Optional[str]
    interest_type: str
    rate_type: str
    roi_monthly: Decimal
    principal: Decimal
    disbursed_amount: Decimal
    outstanding_principal: Decimal
    accrued_interest: Decimal
    total_overdue: Decimal
    total_penalty: Decimal
    total_bounce_charges: Decimal
    total_paid: Decimal
    dpd: int
    sma_category: Optional[str]
    npa_classification: Optional[str]
    disbursal_date: date
    maturity_date: date
    cooling_off_until: date
    closed_at: Optional[datetime]
    closure_type: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduleInstallmentResponse(BaseModel):
    id: uuid.UUID
    installment_no: int
    due_date: date
    principal_amt: Decimal
    interest_amt: Decimal
    emi_amount: Decimal
    bounce_charge: Decimal
    bounce_gst: Decimal
    penalty_amt: Decimal
    penalty_gst: Decimal
    waiver_amt: Decimal
    total_paid: Decimal
    status: str
    paid_at: Optional[datetime]

    model_config = {"from_attributes": True}


class LedgerEntryResponse(BaseModel):
    id: uuid.UUID
    entry_type: str
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    narration: Optional[str]
    effective_date: date
    reference_no: Optional[str]
    allocation_scheme: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class OutstandingResponse(BaseModel):
    loan_id: uuid.UUID
    loan_account_number: str
    outstanding_principal: Decimal
    accrued_interest: Decimal
    total_penalty: Decimal
    total_bounce_charges: Decimal
    total_overdue: Decimal
    total_payable: Decimal


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    limit: int
    pages: int
