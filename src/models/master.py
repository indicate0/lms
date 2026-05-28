import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class ChargeMaster(Base):
    __tablename__ = "charge_master"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    charge_code: Mapped[str] = mapped_column(String(50), nullable=False)
    charge_name: Mapped[str] = mapped_column(String(100), nullable=False)
    calc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    fixed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    pct_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    min_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    max_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    gst_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="18.00")
    penal_capitalise: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_till: Mapped[Optional[date]] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "charge_code", "effective_from", name="ux_charge_master_active"),
    )


class ProductMaster(Base):
    __tablename__ = "product_master"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    product_name: Mapped[str] = mapped_column(String(100), nullable=False)

    interest_type: Mapped[str] = mapped_column(String(20), nullable=False)
    foreclosure_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    foreclosure_lock_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    grace_period_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    enach_presentation_lead_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    part_prepayment_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    part_prepayment_min_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    part_prepayment_lock_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    restructuring_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ots_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    noc_auto_issue_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    bureau_report_on_closure: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_till: Mapped[Optional[date]] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "product_code", "effective_from", name="ux_product_master_active"),
    )


class CollectionRuleMaster(Base):
    __tablename__ = "collection_rule_master"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("product_master.id"))
    dpd_from: Mapped[int] = mapped_column(Integer, nullable=False)
    dpd_to: Mapped[int] = mapped_column(Integer, nullable=False)
    sma_bucket: Mapped[str] = mapped_column(String(10), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    escalate_to_field: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    legal_action_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    enach_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    enach_retry_gap_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    notify_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    notify_guarantor: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_till: Mapped[Optional[date]] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_collection_rule_dpd", "tenant_id", "dpd_from", "dpd_to", postgresql_where="is_active = TRUE"),
    )


class TenantConfig(Base):
    __tablename__ = "tenant_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    config_key: Mapped[str] = mapped_column(String(100), nullable=False)
    config_value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "config_key", name="uq_tenant_config"),)


class PaymentAllocationScheme(Base):
    __tablename__ = "payment_allocation_schemes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_type: Mapped[str] = mapped_column(String(50), nullable=False)
    step_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    bucket: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "product_type", "step_order", name="uq_scheme_step"),
        UniqueConstraint("tenant_id", "product_type", "bucket", name="uq_scheme_bucket"),
        Index("idx_alloc_scheme_lookup", "tenant_id", "product_type", "step_order", postgresql_where="is_active = TRUE"),
    )
