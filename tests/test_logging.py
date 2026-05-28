"""Tests for the logging module — masking, request_id propagation, audit trail."""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.logging import _mask, request_id_ctx, write_audit_log, SYSTEM_ACTOR_ID, SYSTEM_ROLE


# ── Sensitive data masking ────────────────────────────────────────────────────

def test_pan_is_masked():
    assert "***PAN***" in _mask("Customer PAN is ABCDE1234F")
    assert "ABCDE1234F" not in _mask("Customer PAN is ABCDE1234F")


def test_aadhaar_is_masked():
    result = _mask("Aadhaar: 1234 5678 9012")
    assert "***AADHAAR***" in result
    assert "1234 5678 9012" not in result


def test_aadhaar_with_hyphens_is_masked():
    result = _mask("1234-5678-9012")
    assert "***AADHAAR***" in result


def test_normal_text_not_affected():
    text = "Payment of ₹5000 received for loan ALMS-2026-00000001"
    assert _mask(text) == text


def test_multiple_pans_all_masked():
    text = "PAN1: ABCDE1234F and PAN2: XYZAB9876G"
    result = _mask(text)
    assert result.count("***PAN***") == 2


# ── Request-ID context var ────────────────────────────────────────────────────

def test_request_id_ctx_default_is_none():
    assert request_id_ctx.get() is None


def test_request_id_ctx_can_be_set():
    token = request_id_ctx.set("req-abc-123")
    assert request_id_ctx.get() == "req-abc-123"
    request_id_ctx.reset(token)
    assert request_id_ctx.get() is None


# ── write_audit_log ───────────────────────────────────────────────────────────

async def test_write_audit_log_adds_to_session(session):
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    entity_id = uuid.uuid4()

    await write_audit_log(
        session,
        tenant_id=tenant_id,
        actor_id=SYSTEM_ACTOR_ID,
        actor_role=SYSTEM_ROLE,
        action="test_event",
        entity_type="loan",
        entity_id=entity_id,
        payload_after={"status": "active"},
    )
    await session.flush()

    from sqlalchemy import select
    from src.models.loan import AuditLog
    result = await session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == entity_id,
            AuditLog.action == "test_event",
        )
    )
    row = result.scalar_one()
    assert row.actor_role == "system"
    assert row.payload_after == {"status": "active"}


async def test_write_audit_log_captures_request_id(session):
    token = request_id_ctx.set("req-from-test")
    entity_id = uuid.uuid4()
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    await write_audit_log(
        session,
        tenant_id=tenant_id,
        actor_id=SYSTEM_ACTOR_ID,
        actor_role=SYSTEM_ROLE,
        action="test_with_rid",
        entity_type="loan",
        entity_id=entity_id,
    )
    await session.flush()
    request_id_ctx.reset(token)

    from sqlalchemy import select
    from src.models.loan import AuditLog
    result = await session.execute(
        select(AuditLog).where(AuditLog.entity_id == entity_id)
    )
    row = result.scalar_one()
    assert row.request_id == "req-from-test"
