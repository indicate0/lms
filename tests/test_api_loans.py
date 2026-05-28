"""HTTP-level tests for the loans and repayments API endpoints."""
import uuid
from decimal import Decimal

import pytest

from tests.conftest import make_disbursal_event, seed_active_loan, seed_allocation_scheme


async def test_create_loan_via_api(client):
    payload = make_disbursal_event()
    resp = await client.post("/api/v1/lms/loans", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "active"
    assert data["loan_account_number"].startswith("ALMS-")


async def test_get_loan_via_api(client, session):
    loan = await seed_active_loan(session)
    resp = await client.get(f"/api/v1/lms/loans/{loan.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(loan.id)


async def test_get_loan_not_found(client):
    resp = await client.get(f"/api/v1/lms/loans/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"] == "NOT_FOUND"


async def test_get_schedule_via_api(client, session):
    loan = await seed_active_loan(session)
    resp = await client.get(f"/api/v1/lms/loans/{loan.id}/schedule")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 12
    assert len(data["items"]) == 12


async def test_get_outstanding_via_api(client, session):
    loan = await seed_active_loan(session)
    resp = await client.get(f"/api/v1/lms/loans/{loan.id}/outstanding")
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(data["outstanding_principal"]) == Decimal("100000.00")


async def test_post_payment_via_api(client, session):
    from datetime import date, timedelta
    from sqlalchemy import update
    from src.models.loan import RepaymentSchedule

    await seed_allocation_scheme(session)
    loan = await seed_active_loan(session)
    await session.execute(
        update(RepaymentSchedule)
        .where(RepaymentSchedule.loan_id == loan.id, RepaymentSchedule.installment_no == 1)
        .values(status="overdue", due_date=date.today() - timedelta(days=1))
    )
    await session.flush()

    resp = await client.post(
        "/api/v1/lms/repayments/pay",
        json={
            "loan_id": str(loan.id),
            "amount": "9168.00",
            "channel": "neft",
            "payment_type": "emi",
            "utr_ref": f"UTR{uuid.uuid4().hex[:10].upper()}",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["status"] in ("success", "suspense")


async def test_health_endpoint(client):
    resp = await client.get("/api/v1/lms/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_error_response_includes_request_id(client):
    resp = await client.get(
        f"/api/v1/lms/loans/{uuid.uuid4()}",
        headers={"x-request-id": "test-req-123"},
    )
    assert resp.status_code == 404
    assert resp.json()["request_id"] == "test-req-123"


async def test_response_echoes_request_id_header(client):
    resp = await client.get(
        "/api/v1/lms/health",
        headers={"x-request-id": "my-trace-id"},
    )
    assert resp.headers.get("x-request-id") == "my-trace-id"
