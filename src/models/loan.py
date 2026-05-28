import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class Loan(Base):
    __tablename__ = "loans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    loan_account_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)

    sanctioned_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    disbursed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    disbursal_utr: Mapped[str] = mapped_column(String(50), nullable=False)
    disbursal_date: Mapped[date] = mapped_column(Date, nullable=False)
    disbursal_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    principal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    interest_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="fixed")
    benchmark_code: Mapped[Optional[str]] = mapped_column(String(50))
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    product_type: Mapped[Optional[str]] = mapped_column(String(50))
    roi_monthly: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    roi_daily: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6))
    tenure_months: Mapped[Optional[int]] = mapped_column(Integer)
    tenure_days: Mapped[Optional[int]] = mapped_column(Integer)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)

    outstanding_principal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    accrued_interest: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    total_overdue: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    total_penalty: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    total_bounce_charges: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    total_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")

    active_mandate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    cooling_off_until: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", index=True)
    dpd: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sma_category: Mapped[Optional[str]] = mapped_column(String(10))
    npa_classification: Mapped[Optional[str]] = mapped_column(String(20))
    npa_since: Mapped[Optional[date]] = mapped_column(Date)
    first_default_date: Mapped[Optional[date]] = mapped_column(Date)

    provision_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), server_default="0")
    provision_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), server_default="0")

    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closure_type: Mapped[Optional[str]] = mapped_column(String(20))
    noc_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    noc_s3_key: Mapped[Optional[str]] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    schedules: Mapped[list["RepaymentSchedule"]] = relationship(back_populates="loan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="loan")
    ledger_entries: Mapped[list["LoanLedger"]] = relationship(back_populates="loan")
    mandates: Mapped[list["Mandate"]] = relationship(back_populates="loan")

    __table_args__ = (
        Index("idx_loans_dpd", "dpd", postgresql_where="status = 'active'"),
        Index("idx_loans_maturity", "maturity_date", postgresql_where="status = 'active'"),
    )


class RepaymentSchedule(Base):
    __tablename__ = "repayment_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    installment_no: Mapped[int] = mapped_column(Integer, nullable=False)

    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    principal_amt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    interest_amt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    emi_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    bounce_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    bounce_gst: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    penalty_amt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    penalty_gst: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    waiver_amt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")

    total_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    dpd_on_payment: Mapped[Optional[int]] = mapped_column(Integer)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    loan: Mapped["Loan"] = relationship(back_populates="schedules")

    __table_args__ = (
        UniqueConstraint("loan_id", "installment_no"),
        Index(
            "idx_sched_due_date", "due_date",
            postgresql_where="status IN ('pending', 'overdue', 'partial')",
        ),
    )


class LoanLedger(Base):
    __tablename__ = "loan_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("repayment_schedules.id"))
    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))

    entry_type: Mapped[str] = mapped_column(String(40), nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    running_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    narration: Mapped[Optional[str]] = mapped_column(Text)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    reference_no: Mapped[Optional[str]] = mapped_column(String(100))
    allocation_scheme: Mapped[Optional[str]] = mapped_column(String(50))

    loan: Mapped["Loan"] = relationship(back_populates="ledger_entries")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("repayment_schedules.id"))
    mandate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    utr_ref: Mapped[Optional[str]] = mapped_column(String(100))
    gateway_ref: Mapped[Optional[str]] = mapped_column(String(100))
    payer_account: Mapped[Optional[str]] = mapped_column(String(30))

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="initiated", index=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(200))

    allocated_principal: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    allocated_interest: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    allocated_penalty: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    allocated_bounce: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    excess_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")

    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    loan: Mapped["Loan"] = relationship(back_populates="payments")

    __table_args__ = (
        Index("idx_payments_utr", "utr_ref", postgresql_where="utr_ref IS NOT NULL"),
    )


class Mandate(Base):
    __tablename__ = "mandates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    type: Mapped[str] = mapped_column(String(20), nullable=False)
    umrn: Mapped[Optional[str]] = mapped_column(String(100))
    vendor_mandate_id: Mapped[Optional[str]] = mapped_column(String(100))
    bank_name: Mapped[Optional[str]] = mapped_column(String(100))
    account_masked: Mapped[Optional[str]] = mapped_column(String(20))
    ifsc: Mapped[Optional[str]] = mapped_column(String(15))
    account_type: Mapped[Optional[str]] = mapped_column(String(20))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, server_default="monthly")
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(200))
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    loan: Mapped["Loan"] = relationship(back_populates="mandates")


class BounceEvent(Base):
    __tablename__ = "bounce_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repayment_schedules.id"), nullable=False)
    mandate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("mandates.id"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_attempted: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    bounce_reason: Mapped[Optional[str]] = mapped_column(String(200))
    npci_ref: Mapped[Optional[str]] = mapped_column(String(100))
    gateway_ref: Mapped[Optional[str]] = mapped_column(String(100))

    bounce_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    bounce_gst: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    charge_waived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    waiver_reason: Mapped[Optional[str]] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PenaltyLedger(Base):
    __tablename__ = "penalty_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repayment_schedules.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    accrual_date: Mapped[date] = mapped_column(Date, nullable=False)
    dpd_on_date: Mapped[int] = mapped_column(Integer, nullable=False)
    overdue_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    penalty_rate_pct: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    penalty_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    penalty_type: Mapped[str] = mapped_column(String(20), nullable=False)

    waived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    waiver_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), server_default="0")
    waiver_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    waiver_reason: Mapped[Optional[str]] = mapped_column(String(500))
    waiver_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("loan_id", "schedule_id", "accrual_date", "penalty_type", name="idx_penalty_date"),
    )


class ForeclosureRequest(Base):
    __tablename__ = "foreclosure_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)

    outstanding_principal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    accrued_interest: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    overdue_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    foreclosure_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gst_on_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_payable: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PartPrepaymentRequest(Base):
    __tablename__ = "part_prepayment_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    prepay_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    prepay_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gst_on_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_payable: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    new_outstanding: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    recalc_option: Mapped[Optional[str]] = mapped_column(String(20))
    new_emi: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    new_tenure_months: Mapped[Optional[int]] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LoanRestructuring(Base):
    __tablename__ = "loan_restructuring"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    restructure_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500))

    orig_outstanding: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    orig_tenure: Mapped[Optional[int]] = mapped_column(Integer)
    orig_roi: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    orig_emi: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))

    new_principal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    new_tenure: Mapped[int] = mapped_column(Integer, nullable=False)
    new_roi: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    new_emi: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    new_maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    moratorium_months: Mapped[int] = mapped_column(Integer, server_default="0")

    restructuring_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    gst_on_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OtsSettlement(Base):
    __tablename__ = "ots_settlements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    offer_date: Mapped[date] = mapped_column(Date, nullable=False)
    offer_valid_until: Mapped[date] = mapped_column(Date, nullable=False)

    total_outstanding: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    settlement_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    waiver_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    waiver_components: Mapped[Optional[dict]] = mapped_column(JSONB)

    approval_level: Mapped[Optional[str]] = mapped_column(String(20))
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="offered")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NpaProvisioning(Base):
    __tablename__ = "npa_provisioning"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    report_month: Mapped[date] = mapped_column(Date, nullable=False)

    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    dpd_at_eom: Mapped[int] = mapped_column(Integer, nullable=False)
    outstanding_eom: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    collateral_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    provision_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("loan_id", "report_month"),)


class CreditBureauReport(Base):
    __tablename__ = "credit_bureau_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    bureau: Mapped[str] = mapped_column(String(20), nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reporting_month: Mapped[date] = mapped_column(Date, nullable=False)
    dpd_reported: Mapped[Optional[int]] = mapped_column(Integer)
    account_status: Mapped[Optional[str]] = mapped_column(String(30))
    outstanding_reported: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))

    submission_ref: Mapped[Optional[str]] = mapped_column(String(100))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LoanWaiver(Base):
    __tablename__ = "loan_waivers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    schedule_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("repayment_schedules.id"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    grievance_ticket: Mapped[str] = mapped_column(String(30), nullable=False)
    waiver_type: Mapped[str] = mapped_column(String(30), nullable=False)
    waiver_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gst_reversal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    approved_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RegulatoryReport(Base):
    __tablename__ = "regulatory_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reporting_period: Mapped[date] = mapped_column(Date, nullable=False)
    report_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    file_s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    submission_ref: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PaymentSuspense(Base):
    __tablename__ = "payment_suspense"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source_payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False)
    held_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    released_to_payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="holding")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LoanWriteOff(Base):
    __tablename__ = "loan_write_offs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)

    write_off_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    principal_written_off: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    interest_written_off: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    penalty_written_off: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    write_off_date: Mapped[Optional[date]] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    board_resolution_ref: Mapped[Optional[str]] = mapped_column(String(100))
    initiated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approval_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    recovery_to_date: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending_approval")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PaymentLink(Base):
    __tablename__ = "payment_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    razorpay_link_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    razorpay_short_url: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrossSellFlag(Base):
    __tablename__ = "cross_sell_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ineligible_reason: Mapped[Optional[str]] = mapped_column(String(200))
    suggested_product_code: Mapped[Optional[str]] = mapped_column(String(50))
    suggested_max_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    flagged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actioned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "idx_cross_sell_eligible", "tenant_id", "eligible", "status",
            postgresql_where="eligible = TRUE AND status = 'pending'",
        ),
    )


class MandateAmendmentRequest(Base):
    __tablename__ = "mandate_amendment_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    old_mandate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("mandates.id"))
    new_mandate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("mandates.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    initiated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class LoanGuarantor(Base):
    __tablename__ = "loan_guarantors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    mobile: Mapped[str] = mapped_column(String(15), nullable=False)
    relationship: Mapped[Optional[str]] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RateResetRequest(Base):
    __tablename__ = "rate_reset_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    old_roi_monthly: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    new_roi_monthly: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    reset_date: Mapped[date] = mapped_column(Date, nullable=False)
    customer_choice: Mapped[Optional[str]] = mapped_column(String(30))
    consent_received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consent_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending_consent")
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    initiated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BankHolidayCalendar(Base):
    __tablename__ = "bank_holiday_calendar"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(100), nullable=False)
    holiday_type: Mapped[str] = mapped_column(String(30), nullable=False)
    state_code: Mapped[Optional[str]] = mapped_column(String(5))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "holiday_date"),
        Index("idx_holiday_date", "holiday_date", postgresql_where="is_active = TRUE"),
    )


class PendingApproval(Base):
    __tablename__ = "pending_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    maker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    maker_role: Mapped[str] = mapped_column(String(50), nullable=False)
    checker_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    checker_role: Mapped[Optional[str]] = mapped_column(String(50))

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "idx_pending_approvals_status", "tenant_id", "status", "expires_at",
            postgresql_where="status = 'pending'",
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload_before: Mapped[Optional[dict]] = mapped_column(JSONB)
    payload_after: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    request_id: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id", "created_at"),
        Index("idx_audit_actor", "actor_id", "created_at"),
    )


class EmiDebitRetryQueue(Base):
    __tablename__ = "emi_debit_retry_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repayment_schedules.id"), nullable=False)
    mandate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("mandates.id"))

    retry_date: Mapped[date] = mapped_column(Date, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_retry_queue_date", "retry_date", "processed", postgresql_where="processed = FALSE"),
    )


class NocQueue(Base):
    __tablename__ = "noc_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, server_default="normal")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_reason: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("loan_id", "status", name="uq_noc_queue_loan"),
        Index("idx_noc_queue_pending", "priority", "created_at", postgresql_where="status = 'pending'"),
    )


class JobExecutionLog(Base):
    __tablename__ = "job_execution_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")
    records_processed: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
