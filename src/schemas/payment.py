import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class PaymentRequest(BaseModel):
    loan_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    channel: str           # 'upi_manual' | 'neft' | 'imps' | 'rtgs' | 'cash'
    payment_type: str      # 'emi' | 'penalty' | 'foreclosure' | 'part_prepayment' | 'ots'
    utr_ref: Optional[str] = None
    gateway_ref: Optional[str] = None
    payer_account: Optional[str] = None


class PaymentResponse(BaseModel):
    id: uuid.UUID
    loan_id: uuid.UUID
    amount: Decimal
    channel: str
    payment_type: str
    utr_ref: Optional[str]
    status: str
    allocated_principal: Decimal
    allocated_interest: Decimal
    allocated_penalty: Decimal
    allocated_bounce: Decimal
    excess_amount: Decimal
    initiated_at: datetime
    settled_at: Optional[datetime]

    model_config = {"from_attributes": True}
