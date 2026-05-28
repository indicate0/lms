"""
NPA Provisioning Update and NPA Upgrade Engine — §4.16 of LMS_LLD.md.

Two monthly crons:
  1. run_provisioning_update() — 1st of month 02:00 IST
     Updates npa_classification, provision_pct, provision_amount on all NPA loans.
     Inserts a row into npa_provisioning for the current report month.

  2. run_npa_upgrade_check() — 1st of month 03:00 IST (after provisioning)
     RBI rule: upgrade NPA → active when:
       (a) all overdues cleared (total_overdue + accrued_interest + total_penalty ≤ ₹0.01)
       (b) 3 consecutive scheduled installments paid on-time (DPD == 0) after arrear clearance
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import SYSTEM_ACTOR_ID, SYSTEM_ROLE, get_logger, write_audit_log
from src.models.loan import Loan, LoanLedger, NpaProvisioning, RepaymentSchedule

log = get_logger(__name__)
_ZERO = Decimal("0")
_CENT = Decimal("0.01")


# ── helpers ────────────────────────────────────────────────────────────────────

def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _classify(days_npa: int) -> tuple[str, Decimal]:
    """Return (classification, provision_pct) per RBI prudential norms."""
    if days_npa <= 365:
        return "sub_standard", Decimal("10.0")
    if days_npa <= 730:
        return "doubtful_1", Decimal("25.0")
    if days_npa <= 1095:
        return "doubtful_2", Decimal("40.0")
    return "doubtful_3", Decimal("100.0")


# ── provisioning update ────────────────────────────────────────────────────────

async def run_provisioning_update(session: AsyncSession) -> dict:
    """
    Monthly cron: recalculates NPA classification and provision amounts.
    Inserts one npa_provisioning row per loan for the current report month.
    """
    today = date.today()
    report_month = _first_of_month(today)

    result = await session.execute(
        select(Loan).where(
            Loan.status == "npa",
            Loan.npa_since.is_not(None),
        )
    )
    loans = result.scalars().all()

    updated = 0
    for loan in loans:
        days_npa = (today - loan.npa_since).days
        cls, pct = _classify(days_npa)
        provision_amount = (loan.outstanding_principal * pct / Decimal("100")).quantize(_CENT)

        loan.npa_classification = cls
        loan.provision_pct = pct
        loan.provision_amount = provision_amount

        # Upsert: insert new row for this month (duplicates are OK — last write wins per report_month)
        existing = await session.execute(
            select(NpaProvisioning).where(
                NpaProvisioning.loan_id == loan.id,
                NpaProvisioning.report_month == report_month,
            )
        )
        prov_row = existing.scalar_one_or_none()
        if prov_row:
            prov_row.classification = cls
            prov_row.provision_pct = pct
            prov_row.outstanding_eom = loan.outstanding_principal
            prov_row.dpd_at_eom = days_npa
        else:
            session.add(NpaProvisioning(
                tenant_id=loan.tenant_id,
                loan_id=loan.id,
                report_month=report_month,
                classification=cls,
                provision_pct=pct,
                outstanding_eom=loan.outstanding_principal,
                dpd_at_eom=days_npa,
            ))
        updated += 1

    await session.commit()
    log.info("provisioning_update_complete", updated=updated, report_month=str(report_month))
    return {"updated": updated, "report_month": str(report_month)}


# ── NPA upgrade check ──────────────────────────────────────────────────────────

async def run_npa_upgrade_check(session: AsyncSession) -> dict:
    """
    Monthly cron: upgrades NPA loans to 'active' when RBI conditions are met.
    Conditions:
      1. All overdues cleared (total_overdue + accrued_interest + total_penalty ≤ ₹0.01)
      2. 3 consecutive scheduled installments paid on time after arrear clearance date
    """
    today = date.today()
    report_month = _first_of_month(today)
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(Loan).where(
            Loan.status == "npa",
            Loan.npa_since.is_not(None),
        )
    )
    loans = result.scalars().all()

    upgraded = 0
    skipped_not_cleared = 0
    skipped_no_clearance_date = 0
    skipped_quarter_not_met = 0

    for loan in loans:
        # Condition 1: all financial overdues cleared
        all_cleared = (
            loan.total_overdue <= _CENT
            and loan.accrued_interest <= _CENT
            and loan.total_penalty <= _CENT
        )
        if not all_cleared:
            skipped_not_cleared += 1
            continue

        # Find arrear clearance date: latest paid_at among overdue-when-paid installments
        clearance_result = await session.execute(
            select(func.max(RepaymentSchedule.paid_at)).where(
                RepaymentSchedule.loan_id == loan.id,
                RepaymentSchedule.status == "paid",
                RepaymentSchedule.dpd_on_payment > 0,
            )
        )
        arrear_clearance_date = clearance_result.scalar_one_or_none()
        if arrear_clearance_date is None:
            skipped_no_clearance_date += 1
            continue

        # Normalise to date
        if isinstance(arrear_clearance_date, datetime):
            acd = arrear_clearance_date.date()
        else:
            acd = arrear_clearance_date

        # Condition 2a: at least 3 calendar months since clearance
        months_since = (today.year - acd.year) * 12 + (today.month - acd.month)
        if months_since < 3:
            skipped_quarter_not_met += 1
            continue

        # Condition 2b: 3 consecutive on-time installments after clearance date
        post_result = await session.execute(
            select(RepaymentSchedule).where(
                RepaymentSchedule.loan_id == loan.id,
                RepaymentSchedule.due_date > acd,
                RepaymentSchedule.status == "paid",
            ).order_by(RepaymentSchedule.due_date.asc()).limit(3)
        )
        post_installs = post_result.scalars().all()

        if len(post_installs) < 3:
            skipped_quarter_not_met += 1
            continue

        any_late = any(
            (inst.dpd_on_payment or 0) > 0
            for inst in post_installs
        )
        if any_late:
            skipped_quarter_not_met += 1
            continue

        # ── All conditions met — upgrade ───────────────────────────────────
        # Re-fetch with lock
        locked_result = await session.execute(
            select(Loan).where(Loan.id == loan.id).with_for_update()
        )
        locked_loan = locked_result.scalar_one()

        locked_loan.status = "active"
        locked_loan.npa_classification = None
        locked_loan.npa_since = None
        locked_loan.sma_category = None
        locked_loan.provision_pct = _ZERO
        locked_loan.provision_amount = _ZERO
        locked_loan.dpd = 0

        session.add(LoanLedger(
            loan_id=locked_loan.id,
            tenant_id=locked_loan.tenant_id,
            entry_type="npa_upgrade",
            debit=_ZERO,
            credit=_ZERO,
            running_balance=_ZERO,
            narration=(
                f"Account upgraded from NPA to Standard — RBI Prudential Norms | "
                f"arrear_clearance={acd} | months_since={months_since}"
            ),
            effective_date=today,
        ))

        # Zero out provisioning row for this month
        prov_result = await session.execute(
            select(NpaProvisioning).where(
                NpaProvisioning.loan_id == locked_loan.id,
                NpaProvisioning.report_month == report_month,
            )
        )
        prov_row = prov_result.scalar_one_or_none()
        if prov_row:
            prov_row.provision_pct = _ZERO

        # Flag for ops if no active mandate (needs fresh mandate)
        if not locked_loan.active_mandate_id:
            log.warning(
                "npa_upgrade_no_mandate",
                loan_id=str(locked_loan.id),
                tenant_id=str(locked_loan.tenant_id),
            )

        await write_audit_log(
            session,
            tenant_id=locked_loan.tenant_id,
            actor_id=SYSTEM_ACTOR_ID,
            actor_role=SYSTEM_ROLE,
            action="npa_upgraded",
            entity_type="loan",
            entity_id=locked_loan.id,
            payload_before={"status": "npa", "npa_classification": locked_loan.npa_classification},
            payload_after={
                "status": "active",
                "arrear_clearance_date": str(acd),
                "months_since_clearance": months_since,
            },
        )
        log.info(
            "npa_upgraded",
            loan_id=str(locked_loan.id),
            arrear_clearance_date=str(acd),
            months_since_clearance=months_since,
        )
        upgraded += 1
        await session.flush()  # flush per loan to keep lock scope tight

    await session.commit()
    log.info(
        "npa_upgrade_cron_complete",
        upgraded=upgraded,
        skipped_not_cleared=skipped_not_cleared,
        skipped_no_clearance_date=skipped_no_clearance_date,
        skipped_quarter_not_met=skipped_quarter_not_met,
    )
    return {
        "upgraded": upgraded,
        "skipped_not_cleared": skipped_not_cleared,
        "skipped_no_clearance_date": skipped_no_clearance_date,
        "skipped_quarter_not_met": skipped_quarter_not_met,
    }
