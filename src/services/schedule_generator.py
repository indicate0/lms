"""
Repayment schedule generator — §4.1 of LMS_LLD.md.

Handles three interest types:
  - daily_flat      → payday / bullet (single installment)
  - reducing_balance → standard EMI with broken-period interest
  - flat            → flat-rate EMI
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.loan import BankHolidayCalendar, RepaymentSchedule

if TYPE_CHECKING:
    from src.models.loan import Loan


_TWO = Decimal("0.01")


def _round2(v: Decimal) -> Decimal:
    return v.quantize(_TWO, rounding=ROUND_HALF_UP)


async def _is_holiday(session: AsyncSession, d: date, tenant_id) -> bool:
    result = await session.execute(
        select(BankHolidayCalendar).where(
            BankHolidayCalendar.holiday_date == d,
            BankHolidayCalendar.is_active.is_(True),
            (BankHolidayCalendar.tenant_id == tenant_id)
            | (BankHolidayCalendar.tenant_id.is_(None)),
        )
    )
    return result.scalar_one_or_none() is not None


async def next_working_day(session: AsyncSession, d: date, tenant_id) -> date:
    while d.weekday() >= 5 or await _is_holiday(session, d, tenant_id):
        d += timedelta(days=1)
    return d


def _next_emi_date(disbursal: date) -> date:
    """First EMI falls on the same day-of-month in the next month."""
    month = disbursal.month + 1
    year = disbursal.year
    if month > 12:
        month = 1
        year += 1
    # clamp to valid day (e.g. Jan 31 → Feb 28)
    last_day = (date(year, month % 12 + 1, 1) - timedelta(days=1)).day if month < 12 else 31
    day = min(disbursal.day, last_day)
    return date(year, month, day)


async def generate_schedule(session: AsyncSession, loan: "Loan") -> list[RepaymentSchedule]:
    tenant_id = loan.tenant_id
    rows: list[RepaymentSchedule] = []

    if loan.interest_type == "daily_flat":
        assert loan.tenure_days and loan.roi_daily, "payday loan needs tenure_days + roi_daily"
        due = await next_working_day(
            session, loan.disbursal_date + timedelta(days=loan.tenure_days), tenant_id
        )
        interest = _round2(Decimal(str(loan.principal)) * Decimal(str(loan.roi_daily)) * loan.tenure_days)
        emi = _round2(Decimal(str(loan.principal)) + interest)
        rows.append(
            RepaymentSchedule(
                loan_id=loan.id,
                tenant_id=tenant_id,
                installment_no=1,
                due_date=due,
                principal_amt=loan.principal,
                interest_amt=interest,
                emi_amount=emi,
            )
        )

    elif loan.interest_type == "reducing_balance":
        assert loan.tenure_months, "EMI loan needs tenure_months"
        r = Decimal(str(loan.roi_monthly)) / 100
        n = loan.tenure_months
        p = Decimal(str(loan.principal))

        # EMI = P × r × (1+r)^n / ((1+r)^n - 1)
        factor = (1 + r) ** n
        emi = _round2(p * r * factor / (factor - 1))

        # Broken period interest
        first_emi_date = _next_emi_date(loan.disbursal_date)
        broken_days = (first_emi_date - loan.disbursal_date).days - 30
        # days between disbursal and first emi minus a standard 30-day period
        broken_days = max(0, (first_emi_date - loan.disbursal_date).days - 30)
        broken_int = _round2(p * (r / 30) * broken_days) if broken_days > 0 else Decimal("0")

        outstanding = p
        current_date = first_emi_date

        for i in range(1, n + 1):
            interest = _round2(outstanding * r)
            if i == n:
                principal = outstanding
            else:
                principal = _round2(emi - interest)
            emi_total = principal + interest
            if i == 1 and broken_int > 0:
                emi_total += broken_int

            due = await next_working_day(session, current_date, tenant_id)
            rows.append(
                RepaymentSchedule(
                    loan_id=loan.id,
                    tenant_id=tenant_id,
                    installment_no=i,
                    due_date=due,
                    principal_amt=principal,
                    interest_amt=interest + (broken_int if i == 1 else Decimal("0")),
                    emi_amount=emi_total,
                )
            )
            outstanding -= principal

            # advance to next month same day
            next_month = current_date.month + 1
            next_year = current_date.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            last = (date(next_year, next_month % 12 + 1, 1) - timedelta(days=1)).day if next_month < 12 else 31
            current_date = date(next_year, next_month, min(current_date.day, last))

    elif loan.interest_type == "flat":
        assert loan.tenure_months, "flat-rate loan needs tenure_months"
        p = Decimal(str(loan.principal))
        n = loan.tenure_months
        r = Decimal(str(loan.roi_monthly))
        total_interest = _round2(p * r * n / 100)
        emi = _round2((p + total_interest) / n)

        interest_per_emi = _round2(total_interest / n)
        principal_per_emi = _round2(p / n)

        current_date = _next_emi_date(loan.disbursal_date)
        outstanding_p = p

        for i in range(1, n + 1):
            if i == n:
                prin = outstanding_p
            else:
                prin = principal_per_emi
            emi_total = prin + interest_per_emi
            due = await next_working_day(session, current_date, tenant_id)
            rows.append(
                RepaymentSchedule(
                    loan_id=loan.id,
                    tenant_id=tenant_id,
                    installment_no=i,
                    due_date=due,
                    principal_amt=prin,
                    interest_amt=interest_per_emi,
                    emi_amount=emi_total,
                )
            )
            outstanding_p -= prin

            next_month = current_date.month + 1
            next_year = current_date.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            last = (date(next_year, next_month % 12 + 1, 1) - timedelta(days=1)).day if next_month < 12 else 31
            current_date = date(next_year, next_month, min(current_date.day, last))

    else:
        raise ValueError(f"Unknown interest_type: {loan.interest_type}")

    return rows
