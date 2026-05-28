"""
Test fixtures for Alpha LMS.

Strategy:
- One PostgreSQL schema per test session (created with psycopg2 sync).
- Each test gets a fresh AsyncSession from the pool.
- After each test, all tables are TRUNCATED (CASCADE) so the next test
  starts clean. Sequences are reset too.
- Real DB on port 5499 (no mocks) — consistent with the project's stance
  that mock/prod divergence has caused prod failures.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import AsyncGenerator

import psycopg2
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.session import Base
from src.models import loan as _loan_models  # noqa: F401
from src.models import master as _master_models  # noqa: F401


# ── Single event loop for the whole test session ──────────────────────────────
# Required so the async engine connection pool (asyncpg) is always attached
# to the same event loop that runs all tests.
@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

_SYNC_DSN = "dbname=alpha_lms user=lms password=lms_secret host=localhost port=5499"
_ASYNC_URL = "postgresql+asyncpg://lms:lms_secret@localhost:5499/alpha_lms"
_TEST_SCHEMA = f"test_lms_{uuid.uuid4().hex[:8]}"

_engine = create_async_engine(_ASYNC_URL, echo=False)
_SessionFactory = async_sessionmaker(_engine, expire_on_commit=False)


# ── Schema + tables (sync, once per session) ──────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _db_schema():
    from sqlalchemy import create_engine as sync_create_engine

    pg = psycopg2.connect(_SYNC_DSN)
    pg.autocommit = True
    cur = pg.cursor()
    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{_TEST_SCHEMA}"')
    cur.close()
    pg.close()

    from sqlalchemy import create_engine as _sync_create, text as _t
    sync_eng = _sync_create(
        "postgresql+psycopg2://lms:lms_secret@localhost:5499/alpha_lms",
        connect_args={"options": f"-csearch_path={_TEST_SCHEMA},public"},
    )
    Base.metadata.drop_all(sync_eng)
    Base.metadata.create_all(sync_eng)
    # Patch the penalty_ledger unique constraint to include penalty_type
    # so daily penal + legal_charge rows on the same date don't conflict.
    with sync_eng.begin() as conn:
        conn.execute(_t('ALTER TABLE penalty_ledger DROP CONSTRAINT IF EXISTS idx_penalty_date'))
        conn.execute(_t(
            'ALTER TABLE penalty_ledger '
            'ADD CONSTRAINT idx_penalty_date '
            'UNIQUE (loan_id, schedule_id, accrual_date, penalty_type)'
        ))
    sync_eng.dispose()

    yield

    pg2 = psycopg2.connect(_SYNC_DSN)
    pg2.autocommit = True
    cur2 = pg2.cursor()
    cur2.execute(f'DROP SCHEMA IF EXISTS "{_TEST_SCHEMA}" CASCADE')
    cur2.close()
    pg2.close()


# ── Table truncation between tests ────────────────────────────────────────────

# Tables in dependency-safe truncation order (children first).
_TRUNCATE_TABLES = [
    "audit_logs",
    "loan_write_offs",
    "penalty_ledger",
    "bounce_events",
    "emi_debit_retry_queue",
    "noc_queue",
    "npa_provisioning",
    "part_prepayment_requests",
    "foreclosure_requests",
    "loan_guarantors",
    "payment_suspense",
    "payment_links",
    "credit_bureau_reports",
    "regulatory_reports",
    "loan_waivers",
    "loan_restructuring",
    "ots_settlements",
    "cross_sell_flags",
    "rate_reset_requests",
    "mandate_amendment_requests",
    "job_execution_logs",
    "pending_approvals",
    "payments",
    "loan_ledger",
    "repayment_schedules",
    "mandates",
    "loans",
    "payment_allocation_schemes",
    "charge_master",
    "collection_rule_master",
    "product_master",
    "tenant_configs",
    "bank_holiday_calendar",
]


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    """Truncate all tables + reset the loan account sequence before each test."""
    async with _engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{_TEST_SCHEMA}", public'))
        tables_csv = ", ".join(f'"{t}"' for t in _TRUNCATE_TABLES)
        await conn.execute(text(f"TRUNCATE TABLE {tables_csv} RESTART IDENTITY CASCADE"))
        # Reset loan account sequences in both schemas
        await conn.execute(text(
            "SELECT setval(seq.relname::regclass, 1, false) "
            "FROM pg_class seq "
            "JOIN pg_namespace ns ON ns.oid = seq.relnamespace "
            "WHERE seq.relkind = 'S' AND seq.relname LIKE 'loan_account_seq_%'"
        ))
    yield


# ── Per-test async session ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    async with _SessionFactory() as s:
        await s.execute(text(f'SET search_path TO "{_TEST_SCHEMA}", public'))
        yield s


# ── HTTP test client ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from src.core.auth import Principal, Role, get_current_principal, _ROLE_PERMISSIONS
    from src.db.session import get_db
    from src.main import app

    async def _override_db():
        yield session

    # Give all tests a super-admin principal so every route passes auth
    def _override_auth():
        return Principal(
            sub=str(TENANT_ID),
            username="test-user",
            email="test@sudosys.org",
            roles=[Role.SUPER_ADMIN],
            permissions=_ROLE_PERMISSIONS[Role.SUPER_ADMIN],
            tenant_id=TENANT_ID,
            is_internal=False,
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_principal] = _override_auth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Shared test IDs ───────────────────────────────────────────────────────────

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
AGENT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


# ── Seed helpers ──────────────────────────────────────────────────────────────

def make_disbursal_event(**overrides) -> dict:
    today = date.today()
    base = {
        "application_id": str(uuid.uuid4()),
        "customer_id": str(CUSTOMER_ID),
        "tenant_id": str(TENANT_ID),
        "agent_id": str(AGENT_ID),
        "tenant_short_code": "TST",
        "sanctioned_amount": "100000.00",
        "disbursed_amount": "100000.00",
        "disbursal_utr": f"UTR{uuid.uuid4().hex[:12].upper()}",
        "disbursal_date": str(today),
        "disbursal_channel": "neft",
        "principal": "100000.00",
        "interest_type": "reducing_balance",
        "rate_type": "fixed",
        "product_code": "PL001",
        "product_type": "emi_loan",
        "roi_monthly": "1.50",
        "tenure_months": 12,
        "maturity_date": str(today + timedelta(days=365)),
    }
    base.update(overrides)
    return base


async def seed_active_loan(session: AsyncSession, **overrides):
    from src.schemas.loan import LoanDisbursedEvent
    from src.services.loan_service import create_loan_from_disbursed_event

    evt = LoanDisbursedEvent(**make_disbursal_event(**overrides))
    return await create_loan_from_disbursed_event(session, evt)


async def seed_allocation_scheme(session: AsyncSession):
    from src.models.master import PaymentAllocationScheme

    for i, bucket in enumerate(["bounce", "penalty", "interest", "principal"], 1):
        session.add(PaymentAllocationScheme(
            tenant_id=TENANT_ID,
            product_type="emi_loan",
            bucket=bucket,
            step_order=i,
        ))
    await session.flush()
