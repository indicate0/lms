# High-Level Design — Alpha LMS v3
## Alpha LMS — Post-Disbursal Lifecycle

> **Version:** 4.0 | **Previous version:** LMS_HLD_v3.md
> **Changes in v4:** master table seed data · composite indexes · loan_ledger partitioning DDL · standardised API error envelope · loan_account_number sequence DDL · interest accrual module · bounce charge module · account statement module · due date change module · moratorium module · prepayment / foreclosure lock-in · TDS module · GST tax invoice module
>
> **Changes in v3:** holiday_calendar module · partial payment / suspense handling · DLQ strategy · API pagination · health & readiness endpoints · circuit breaker for Digio/Razorpay

> **Scope:** This document describes the architecture, modules, integrations, and compliance framework of the LMS only.
> The LOS (Loan Origination System) is a separate service; it ends at disbursal confirmation + UTR receipt and hands off to the LMS via event.
>
> **Regulatory basis:** RBI Digital Lending Guidelines 2022 · RBI Master Direction NBFC-ND-SI 2016 · RBI Fair Practice Code · Penal Charges Circular (Aug 2023, eff. 01-Jan-2024) · Floating Rate Reset Circular (Aug 2023) · NPA / Prudential Norms · SARFAESI Act 2002 · CERSAI Act · CGST Act 2017 · IT Act 2000 · DPDP Act 2023 · RBI Ombudsman Scheme 2021

---

## 1. System Overview

The LMS is the financial backbone of the Lending Platform from the moment a loan is disbursed until it is fully repaid, foreclosed, settled, or written off. It is the authoritative source of truth for every rupee owed, paid, and charged across all loan accounts.

**Boundary:**

```
LOS → [loan.disbursed event] → LMS owns everything from here
                                └── Repayment · Collection · Closure · Reporting
```

**Key responsibilities:**

| Responsibility | Description |
|---|---|
| Loan account ledger | Double-entry, tamper-proof financial record for every loan |
| Schedule generation | Amortisation table for EMI (reducing & flat), and payday bullet loans |
| Interest accrual | Daily accrual on outstanding principal |
| EMI collection | Auto-debit orchestration via eNACH and UPI Autopay |
| Penalty engine | Late payment penalty and penal interest per RBI norms |
| DPD tracking | Daily DPD update and SMA classification (SMA-0 / SMA-1 / SMA-2) |
| NPA management | NPA classification, provisioning, credit bureau reporting |
| Foreclosure | Quote generation, payment processing, mandate cancellation |
| Part-prepayment | Eligibility check, charge calculation, schedule recalculation |
| Restructuring | Loan restructuring with revised amortisation and maker-checker |
| OTS settlement | One-time settlement with tiered approval workflow |
| NOC issuance | Tamper-proof NOC within 72 hours of closure |
| Collection escalation | Automated escalation through tele-call, field, legal, SARFAESI |
| Collection agency | External agency assignment and performance tracking |
| Legal proceedings | Legal notice, SARFAESI proceedings, recovery suit tracking |
| Regulatory reporting | RBI monthly return, CRILC SMA report, bureau submission |
| Float rate reset | Rate change notification and schedule recalculation |
| Waiver governance | Tiered approval workflow for all charge waivers |
| Interest accrual | Daily accrual with state-aware behaviour (moratorium, NPA suspense, write-off) |
| Bounce charge | Charge application on mandate failure, same-day waiver, GST tracking |
| Account statement | On-demand and scheduled statements; annual interest certificate for ITR |
| Due date change | Customer-initiated EMI date shift with broken-period interest and mandate amendment |
| Moratorium | Standalone payment suspension (full / interest-only) with deferred interest spreading |
| Lock-in enforcement | Prepayment and foreclosure eligibility gate per product and RBI rules |
| TDS | Tax deduction at source on interest; Form 16A generation; TRACES reconciliation |
| GST invoice | Statutory tax invoice for fees and charges; GSTR-1 monthly export |

---

## 2. LMS in the Lending Platform Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Lending PLATFORM                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      CLIENT LAYER                                   │    │
│  │   Flutter App (Android/iOS)    ·    React.js Web Portal             │    │
│  └─────────────────────────┬───────────────────────────────────────────┘    │
│                            │ HTTPS / TLS 1.3                                │
│  ┌─────────────────────────▼───────────────────────────────────────────┐    │
│  │           API GATEWAY  (AWS API GW / Kong)                          │    │
│  │       JWT Auth · Rate Limiting · Load Balancing · WAF               │    │
│  └────┬────────────────────┬────────────────────────────┬──────────────┘    │
│       │                    │                            │                   │
│  ┌────▼──────┐      ┌──────▼──────┐             ┌───────▼────────┐          │
│  │   LOS     │      │  ── LMS ──  │             │  AI/ML Risk    │          │
│  │ (Loan     │event►│  (THIS DOC) │             │  Engine        │          │
│  │  Origin.) │      │             │             │  (Underwriting)│          │
│  └───────────┘      └──────┬──────┘             └────────────────┘          │
│                            │                                                │
│  ┌─────────────────────────▼───────────────────────────────────────────┐    │
│  │                    SHARED CORE SERVICES                             │    │
│  │  Payment Svc · Notification Svc · Audit Svc · PDF Svc              │    │
│  │  DSA Engine · Grievance Svc · Collection Agency Svc                │    │
│  └─────────────────────────┬───────────────────────────────────────────┘    │
│                            │                                                │
│  ┌─────────────────────────▼───────────────────────────────────────────┐    │
│  │                        DATA LAYER                                   │    │
│  │  PostgreSQL (Core) · Redis (Cache) · S3 (Docs) · MongoDB (Logs)    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. LMS Internal Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        LMS SERVICE  (Node.js / FastAPI)                      │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │  Loan Account   │  │  Schedule Engine  │  │   Payment & Reconcil.   │   │
│  │  Module         │  │  • EMI gen        │  │   Module                │   │
│  │  • Ledger       │  │  • Broken period  │  │   • EMI posting         │   │
│  │  • Outstanding  │  │  • Restructure    │  │   • Allocation logic    │   │
│  │  • KFS access   │  │  • Payday bullet  │  │   • Webhook handler     │   │
│  │  • Float reset  │  │  • Post-prepay    │  │   • Reconciliation      │   │
│  └─────────────────┘  └──────────────────┘  └──────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │  DPD & SMA      │  │  Penalty Engine  │  │   NPA & Provisioning    │   │
│  │  Engine (Cron)  │  │  (Cron)          │  │   Engine (Cron)         │   │
│  │  • DPD calc     │  │  • Late penalty  │  │   • NPA classification  │   │
│  │  • SMA tagging  │  │  • Penal interest│  │   • Provisioning %      │   │
│  │  • Overdue flag │  │  • Legal charges │  │   • Write-off           │   │
│  └─────────────────┘  └──────────────────┘  └──────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │  Closure Module │  │  Reporting &     │  │   Collection Module     │   │
│  │  • Foreclosure  │  │  Compliance      │  │   • Tele-call queue     │   │
│  │  • Part-prepay  │  │  • RBI return    │  │   • Agency assignment   │   │
│  │  • OTS settle   │  │  • Bureau report │  │   • Legal pipeline      │   │
│  │  • NOC gen      │  │  • CRILC SMA     │  │   • SARFAESI tracker    │   │
│  └─────────────────┘  └──────────────────┘  └──────────────────────────┘   │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │   Waiver Governance Module  (tiered approval)                          │  │
│  │   • Waiver request intake  • Approval routing  • Ledger application   │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │  Interest       │  │  Bounce Charge   │  │   Account Statement     │   │
│  │  Accrual Module │  │  Module          │  │   Module                │   │
│  │  • Daily 00:05  │  │  • Charge apply  │  │   • On-demand PDF       │   │
│  │  • State-aware  │  │  • GST compute   │  │   • Monthly statement   │   │
│  │  • NPA suspense │  │  • Same-day waiv │  │   • Interest cert (ITR) │   │
│  └─────────────────┘  └──────────────────┘  └──────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │  Moratorium     │  │  Due Date Change │  │   Lock-in Enforcement   │   │
│  │  Module         │  │  Module          │  │   Module                │   │
│  │  • Full / IO    │  │  • Eligibility   │  │   • Foreclosure gate    │   │
│  │  • Deferred int │  │  • Broken period │  │   • Prepayment gate     │   │
│  │  • DPD suppress │  │  • Mandate amend │  │   • Floating-rate rule  │   │
│  └─────────────────┘  └──────────────────┘  └──────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐                                  │
│  │  TDS Module     │  │  GST Invoice     │                                  │
│  │  • TDS deduct   │  │  Module          │                                  │
│  │  • Form 16A gen │  │  • Invoice gen   │                                  │
│  │  • TRACES recon │  │  • GSTR-1 export │                                  │
│  └─────────────────┘  └──────────────────┘                                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Loan Lifecycle State Machine

```
                   ┌──────────────────┐
 [loan.disbursed]─►│     ACTIVE        │◄─── normal ongoing state
                   └────────┬─────────┘
                            │
         ┌──────────────────┼──────────────────────┐
         │                  │                      │
         ▼                  ▼                      ▼
 ┌───────────────┐  ┌────────────────┐  ┌──────────────────┐
 │  CLOSED       │  │  FORECLOSED    │  │  RESTRUCTURED    │
 │ (normal repay)│  │ (early closure)│  │ (revised terms)  │──► ACTIVE
 └───────────────┘  └────────────────┘  └──────────────────┘
         │                  │
         │    ┌─────────────┘
         ▼    ▼
 ┌──────────────────┐
 │  NOC GENERATED   │  ← final state for CLOSED and FORECLOSED
 └──────────────────┘

 ACTIVE ──(DPD 90+)──► NPA
                         │
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
 ┌──────────────┐  ┌──────────────┐  ┌────────────────┐
 │  RECOVERED   │  │  SETTLED_OTS │  │  WRITTEN_OFF   │
 │ (full repay) │  │ (OTS paid)   │  │ (provisioned)  │
 └──────────────┘  └──────────────┘  └────────────────┘

 NPA ──(SARFAESI)──► LEGAL_PROCEEDINGS
                             │
                   ┌─────────┴──────────┐
                   ▼                    ▼
              SETTLED_LEGAL        WRITTEN_OFF
```

**Valid status values:** `active` · `closed` · `foreclosed` · `restructured` · `npa` · `settled_ots` · `settled_legal` · `written_off`

---

## 5. Post-Disbursal Customer Journey

```
[LOS] loan.disbursed event
         │
         ▼
[LMS] Loan account created
      Repayment schedule generated (reducing / flat / bullet)
      Mandate activated
         │
         ├────────────────────────────────────────────┐
         ▼                                            │
[T-1 before each due date]                            │
  Pre-debit notification → SMS + WhatsApp (NPCI mandate)│
         │                                            │
         ▼                                            │
[Due date]                                            │
  Auto-debit initiated (eNACH / UPI Autopay)          │
         │                                            │
    ┌────┴──────┐                                     │
    ▼ SUCCESS   ▼ FAILED                              │
  EMI posted  Bounce charge applied                   │
  DPD = 0     DPD clock starts                       │
    │              │                                  │
    │         Retry D+2, D+3                         │
    │              │                                  │
    │         [DPD 1–7]   Soft reminders             │
    │         [DPD 8–30]  Tele-calling + link        │
    │         [DPD 31–60] Field agent + agency       │
    │         [DPD 61–90] Legal notice + SARFAESI    │
    │         [DPD 90+]   NPA; agency + legal team   │
    │                                                 │
    └─────────────────────────────────────┐           │
                                          ▼           │
                                  All EMIs paid       │
                                  Outstanding = ₹0   │
                                          │           │
                                          ▼           │
                                  Loan CLOSED ◄───────┘
                                  NOC generated (72hr SLA)
                                  Bureau updated → CLOSED
                                  Cross-sell eligibility evaluated
```

---

## 6. Module Descriptions

### 6.1 Loan Account Module
Single source of truth for any loan. Maintains the running financial state: `outstanding_principal`, `accrued_interest`, `total_overdue`, `total_penalty`, `total_bounce_charges`, `total_paid`. All updates are transaction-safe and atomic. Exposes full ledger, outstanding breakup, and document access to customers and admins. Also handles floating rate reset events — when the base rate changes, the module recalculates EMI or tenure (per product configuration) and triggers notifications.

### 6.2 Schedule Engine
Generates the amortisation table at loan creation. Supports three product structures:
- **EMI (Reducing Balance):** Standard monthly instalment; interest computed on outstanding principal
- **EMI (Flat Rate):** Fixed interest on original principal; higher effective cost
- **Payday (Bullet):** Single repayment on maturity; daily flat rate applied

Also handles:
- **Broken-period interest:** when disbursal date is not the 1st of the month, the first EMI carries a short-period interest component
- **Post-part-prepayment recalculation:** customer may choose `reduce_tenure` (same EMI, fewer months) or `reduce_emi` (same tenure, lower EMI)
- **Restructuring recalculation:** full new schedule with optional moratorium months, revised ROI and tenure

### 6.3 Payment & Reconciliation Module
Receives payment signals from:
- Digio eNACH webhooks (auto-debit)
- Razorpay UPI Autopay webhooks (auto-debit)
- Razorpay Payment Link webhooks (manual pay)
- NEFT/IMPS/RTGS credit alerts (manual bank transfer)
- Collection agency remittances (batch)

Applies payments using RBI Fair Practice Code priority order: penalty charges → bounce charges → interest → principal. Runs nightly reconciliation against gateway settlement files; auto-flags mismatches. Unresolved mismatches after T+2 publish a `reconciliation.mismatch` event consumed by the Grievance Service.

### 6.4 DPD & SMA Engine
Runs daily at 00:30 IST. Computes Days Past Due (DPD) as the gap from the earliest unpaid installment due date to today. Tags loans with SMA category:

| DPD | RBI Classification | Internal Label |
|---|---|---|
| 0 | Standard | CURRENT |
| 1–30 | SMA-0 | EARLY DELINQUENT |
| 31–60 | SMA-1 | MID DELINQUENT |
| 61–90 | SMA-2 | LATE DELINQUENT |
| 90+ | NPA (Sub-Standard) | NPA |

### 6.5 Penalty Engine
Runs daily at 01:00 IST. Applies penalty on overdue installments. Per RBI Penal Charges Circular (effective 01-Jan-2024): penal charges are tracked separately from principal — they are never capitalised or added to outstanding principal.

| Stage | Rate | Basis | GST |
|---|---|---|---|
| DPD 1–29 | 2% / month (0.0667% / day) | Overdue EMI | 18% |
| DPD 30+ | 3% / month (0.10% / day) | Total overdue outstanding | 18% |
| DPD 60+ | ₹500 legal notice charge (one-off) | Flat | 18% |

All rates read from `charge_master` — none hardcoded.

### 6.6 NPA & Provisioning Engine
Classifies accounts as NPA at DPD 90. Maintains provisioning per RBI Prudential Norms:

| NPA Duration | Classification | Provisioning |
|---|---|---|
| < 12 months | Sub-Standard | 10% |
| 12–24 months | Doubtful-1 | 25% |
| 24–36 months | Doubtful-2 | 40% |
| > 36 months | Doubtful-3 | 100% |
| Identified as loss | Loss Asset | 100% |

On NPA classification: mandate is cancelled, bureau is updated (status = NPA), collection module escalates to agency/legal team.

### 6.7 Closure Module
Handles four closure paths:
1. **Normal closure** — all EMIs paid; auto-detected when `outstanding_principal ≤ ₹0.01`
2. **Foreclosure** — customer-initiated early closure; charge based on risk band (2–4% of OP); 3-business-day quote validity; zero charge in cooling-off period (3 days post-disbursal)
3. **OTS Settlement** — negotiated for NPA accounts; waiver components require tiered approval (see §6.11)
4. **Legal Recovery / SARFAESI** — settled amount after legal proceedings; tracked as `settled_legal`

On any closure: mandate cancelled, remaining schedule rows waived, NOC generated within 72 hours, bureau updated to `CLOSED` or `WRITTEN_OFF`.

### 6.8 NOC Generation
Generates a tamper-proof PDF using Puppeteer PDF Service. SHA-256 hash stored alongside the S3 key. Delivered to customer via:
- ZeptoMail (Zoho) email with PDF attachment
- WhatsApp (Razorpay / Interakt) with 7-day signed S3 link
- SMS (Tata DLT) confirmation

RBI requirement: NOC within 7 days of closure for digital lending. Internal SLA: 72 hours.

### 6.9 Collection Module (v2 — expanded)

The collection module manages the full escalation chain from first bounce through legal recovery.

**6.9.1 Internal Collection (DPD 0–60)**

- Auto-debit orchestrator handles due-date presentation and 2 retries (D+2, D+3)
- DPD 1–7: automated SMS + WhatsApp reminders with payment link
- DPD 8–30: tele-calling queue; agents send WhatsApp payment links
- DPD 31–60: field agent assigned from DSA / collection staff pool

**6.9.2 Collection Agency Assignment (DPD 45+)**

LMS integrates with registered third-party collection agencies (TRAI-compliant, RBI-registered). Assignment logic:
- Agency selected by `collection_agency_master` (zone, product type, DPD band)
- Assignment record created in `collection_assignments`
- Daily account-level export pushed to agency portal (SFTP / encrypted API)
- Agency remittances posted as batch payments; reconciled same day
- Agent visit records, call logs received from agency; stored in `collection_interactions`

**6.9.3 Legal Proceedings (DPD 60+)**

- DPD 60: one-off ₹500 legal notice charge applied; legal notice dispatched (registered post + digital copy)
- DPD 75: pre-NPA credit committee review; OTS may be offered
- DPD 90+: NPA confirmed; file moved to legal team
- Secured loans > ₹1 lakh: SARFAESI Section-13(2) notice issued (60-day response period)
- SARFAESI possession, sale tracked via `legal_proceedings` table
- Recovery amount posted to LMS on realisation; loan closed as `settled_legal` or `written_off`

### 6.10 Regulatory Reporting Module

| Report | Frequency | Destination | Deadline |
|---|---|---|---|
| Credit Bureau Data (CIBIL / Equifax / Experian) | Monthly | Bureau APIs | 5th of month |
| RBI Monthly Return (DNBS-02) | Monthly | RBI COSMOS portal | 7th of month |
| CRILC SMA Report | Monthly | RBI (for exposures > ₹5 crore) | 21st of month |
| NPA Provisioning Statement | Monthly | Internal / CFO | 5th of month |
| Interest Rate Disclosure | Quarterly | RBI website publication | Quarterly |
| Fraud Reporting (> ₹1 lakh) | Event-triggered | RBI fraud monitoring | Within 7 days |
| Ombudsman Quarterly Return | Quarterly | RBI Ombudsman | 15th of following month |

### 6.11 Waiver Governance Module (v2 — new)

All charge waivers follow a tiered maker-checker approval workflow. No waiver is posted to the ledger without an `approved_by` value from an authorised role.

| Waiver Amount | Approving Authority |
|---|---|
| Up to ₹1,000 | Relationship Manager (RM) |
| ₹1,001 – ₹10,000 | Branch Head / Collection Manager |
| ₹10,001 – ₹1,00,000 | Credit Committee |
| Above ₹1,00,000 or principal waiver | MD / CEO |

Waiver types: `penalty` · `bounce_charge` · `penal_interest` · `legal_charge` · `interest` · `principal` (OTS only)

Waivers can be initiated by:
- Grievance Service (GRO-approved complaint waivers via `POST /loans/:id/waiver`)
- Collection team (for settlement incentive)
- Admin (manual correction)

Once approved, the Waiver Module:
1. Inserts into `loan_waivers`
2. Updates `repayment_schedules` (reduces `penalty_amt` / `bounce_charge`)
3. Updates `loans.total_penalty` / `total_bounce_charges`
4. Posts `credit` entry to `loan_ledger` (`entry_type = 'waiver'`)
5. Publishes `waiver.applied` event

### 6.12 Float Rate Reset Handler (v2 — new)

For floating-rate loans, when the benchmark rate (e.g., RBI repo-linked) changes:

1. LOS / Risk Engine publishes `rate.changed` event with new ROI, effective date
2. LMS receives event; looks up all affected loans (matching `benchmark_code`)
3. Per `product_master.float_reset_option`:
   - `adjust_emi` → recalculate EMI on remaining principal; tenure unchanged
   - `adjust_tenure` → keep EMI same; recalculate tenure
4. New schedule generated; old rows marked `restructured`
5. Customer notified (SMS + Email) with new EMI / tenure per RBI Floating Rate Reset Circular
6. Audit entry created; KFS updated with revised terms

### 6.13 Grievance Service Interface (External)

Grievance Management is **not owned by the LMS**. It is a shared platform-level service. LMS exposes a narrow read + command interface.

**What LMS exposes to the Grievance Service:**

| LMS API | Purpose |
|---|---|
| `GET /loans/:id/outstanding` | Fetch penalty / interest breakup for dispute resolution |
| `GET /loans/:id/ledger` | Full transaction history for a charge dispute |
| `GET /loans/:id/noc` | Retrieve NOC for delivery complaints |
| `POST /loans/:id/waiver` | Apply a charge waiver approved by Grievance Officer |
| `GET /loans/:id/bureau-status` | Check bureau reporting status for correction requests |

**LMS publishes events the Grievance Service subscribes to:**
- `loan.closed` → auto-close any open NOC-delay ticket
- `noc.generated` → mark NOC delivery tickets resolved
- `payment.received` → auto-close unauthorised-debit tickets if refund confirmed
- `reconciliation.mismatch` → auto-open reconciliation dispute ticket

### 6.14 Master Tables (Configuration Layer)

Four master tables drive every LMS engine. No rate, charge, or rule is hardcoded.

| Governance rule | Implementation |
|---|---|
| Versioning | `effective_from` / `effective_till` — point-in-time lookup |
| Multi-tenant | `tenant_id` (NULL = system default; tenant row takes precedence) |
| Maker-checker | `created_by` + `approved_by` — four-eyes approval |
| Soft-disable | `is_active = FALSE` disables without data loss |
| Tax | GST rate stored per charge on `charge_master` |

| Master Table | Owned By | Drives |
|---|---|---|
| `charge_master` | Finance ops | Penalty · Bounce · Foreclosure · Part-prepayment |
| `product_master` | Product team | Schedule generator · Foreclosure rules · NOC SLA |
| `collection_rule_master` | Collections | DPD engine · Escalation workflow · Agency assignment thresholds |
| `collection_agency_master` | Collections | Agency selection · Contact routing · Remittance channels |

> **`interest_rate_master` is owned by LOS.** LMS reads `loans.roi_monthly` directly from the `loan.disbursed` event payload.

**`tenant_configs`** — key-value table for tenant-wide operational settings. Engines read from Redis (5-min TTL), falling back to DB on cache miss.

| Key | Default | Engine |
|---|---|---|
| `reconciliation_tolerance_inr` | ₹1.00 | Payment reconciliation |
| `statement_auto_generate_day` | 5th | Statement cron |
| `notification_timing_pre_due_days` | 3, 1 | Reminder cron |
| `notification_timing_post_due_days` | 1, 3, 7 | Overdue reminder cron |
| `npa_classification_dpd` | 90 | NPA engine (RBI floor) |
| `crilc_report_submission_day` | 15 | Regulatory reporting cron |
| `agency_assignment_dpd_trigger` | 45 | Collection agency assignment |
| `legal_notice_dpd_trigger` | 60 | Legal notice cron |
| `sarfaesi_threshold_inr` | 100000 | SARFAESI eligibility |
| `waiver_rm_limit_inr` | 1000 | Waiver governance |
| `waiver_branch_head_limit_inr` | 10000 | Waiver governance |
| `waiver_credit_committee_limit_inr` | 100000 | Waiver governance |

---

### 6.15 Holiday Calendar Module (v3 — new)

Provides a working-day lookup service consumed by the schedule generator and auto-debit orchestrator.

**Responsibility:** Determine the next working day for any given date. Every computed EMI due date and every mandate presentation date is passed through this module before being stored or submitted.

**Table:** `bank_holiday_calendar` — stores national, bank, RBI, and state holidays per tenant. System defaults (national + RBI holidays) apply to all tenants; tenant can add state-specific holidays.

**Key rule (RBI FPC):** If a due date falls on a bank holiday or weekend, it moves to the next working day. Grace period (`grace_period_days` from `product_master`) starts counting from the adjusted due date — not the original calendar date.

---

### 6.16 Partial Payment & Suspense Module (v3 — new)

Handles payments that are less than the minimum required to settle any single charge tier.

**Policy:**
- Amount ≥ minimum due (penalty + bounce of oldest overdue) → allocate normally per priority order
- Amount < minimum due → move to `payment_suspense`; notify customer to top up; DPD continues to accrue
- Suspense + next payment combined and re-run through allocation engine
- Unclaimed suspense auto-refunded after 30 days

**RBI FPC requirement:** Lender cannot reject a partial payment. Suspense is an acceptance mechanism — not a rejection.

---

### 6.17 Circuit Breaker Module (v3 — new)

Wraps all outbound calls to Digio (eNACH) and Razorpay (UPI Autopay) in a circuit breaker.

**States:** `CLOSED` (normal) → `OPEN` (5 failures in 60s; block calls for 5 min) → `HALF_OPEN` (probe one call) → `CLOSED` on success.

**State store:** Redis key `circuit:{vendor}` — shared across all LMS pod instances.

**Fallback:** Failed debit presentations are enqueued to `emi_debit_retry_queue` for replay when circuit closes. Ops alerted via Slack on circuit open.

---

### 6.18 Interest Accrual Module (v4 — new)

Runs daily at 00:05 IST before any other engine, making accrued interest available for DPD and penalty engines in the same day's batch.

**Accrual method:** Actual/365 (daily rate = `roi_annual / 365`). Applied on `outstanding_principal` as of end-of-prior-day.

**Ledger entry:** `entry_type = 'interest_accrual'` posted to `loan_ledger`; `loans.accrued_interest` incremented atomically within the same transaction.

**State-specific behaviour:**

| Loan State | Accrual Behaviour |
|---|---|
| `active` | Normal daily accrual on outstanding principal |
| `restructured` | Accrues on revised outstanding from restructure effective date |
| `moratorium` | Accrues to `loan_moratoriums.deferred_interest` (not to EMI immediately) |
| `npa` | Accrues but posted to shadow `npa_interest_suspense`; not added to customer demand |
| `written_off` | Accrual suspended; already-accrued suspense amount noted in provisioning record |
| `closed` / `foreclosed` | No accrual; final interest settled at closure |

**Interest on overdue principal:** If an EMI's principal component is unpaid beyond due date, interest continues accruing on that component until collected. This is tracked via `repayment_schedules.overdue_principal`.

---

### 6.19 Bounce Charge Module (v4 — new)

Triggered by a `payment.failed` webhook from Digio (eNACH) or Razorpay (UPI Autopay). Applies a bounce charge per `charge_master` (`charge_type = 'bounce'`) with GST.

**Trigger conditions:**
- `nach.debit.failed` (Digio) or `payment.failed` (Razorpay) for a scheduled auto-debit
- Manual payment link failure is **not** subject to bounce charge (no mandate presentation)

**Same-day waiver rule:** If the mandate is re-presented and succeeds on the same calendar day (via a retry that the auto-debit orchestrator initiates within 4 hours), the bounce charge is automatically reversed. Configurable via `product_master.same_day_retry_waiver = TRUE`.

**Charge cap:** `charge_master.max_bounce_charges_per_loan` caps the total bounce charges chargeable over the loan lifetime (per product). Once cap is reached, charge is ₹0 but the bounce event is still recorded.

**GST:** 18% GST computed and tracked in `bounce_events.gst_amount`. GST invoice generated by §6.25 module.

**Table:** `bounce_events` — one row per bounce event; linked to `payments.id` (the failed payment attempt) and `loan_id`.

**Events published:** `payment.bounced` → Notification Service (SMS + WhatsApp to customer), Collection Engine (DPD clock starts), `bounce_charge.applied` → Audit Service.

---

### 6.20 Account Statement Module (v4 — new)

Provides on-demand and scheduled loan account statements.

**Statement types:**

| Type | Trigger | Content |
|---|---|---|
| Full account statement | Customer / admin API request | All ledger entries, schedule, outstanding breakup |
| Monthly statement | 5th of month cron | Transactions in prior month + closing balance |
| Repayment schedule | Any time post-disbursal | Full amortisation table, remaining EMIs |
| Interest / provisional certificate | On-demand (for ITR filing) | Total interest paid in a financial year (Apr–Mar) |

**API endpoints:**

| Endpoint | Description |
|---|---|
| `GET /loans/:id/statement?from=&to=` | On-demand statement (PDF + JSON) |
| `GET /loans/:id/statement/schedule` | Current repayment schedule as PDF |
| `GET /loans/:id/statement/interest-certificate?fy=2024-25` | Interest certificate for a financial year |

**Delivery:** PDF generated via Puppeteer PDF Service → stored in S3 → signed URL (7-day TTL) returned in API response. Monthly statements also delivered via ZeptoMail email.

**RBI FPC requirement:** At least one free statement per year. Additional on-demand statements may be charged per `charge_master` (`charge_type = 'statement_reissue'`).

**Table:** `loan_statements` — tracks each generated statement (type, period, S3 key, SHA-256 hash, generated_at, delivered_at).

---

### 6.21 Due Date Change Module (v4 — new)

Allows a borrower to shift their monthly EMI due date once during the loan lifetime.

**Eligibility rules (all must pass):**
- Loan status is `active`
- No overdue amount (`total_overdue = 0`)
- No existing due-date change on this loan (`loan_due_date_changes` table is empty for this `loan_id`)
- Requested new due date is between 1st and 28th of month (no 29th–31st to avoid month-end issues)
- Minimum 5 calendar days gap between request date and next existing due date (to avoid mandate conflict)

**Processing steps:**
1. Validate eligibility
2. Compute broken-period interest from old due date to new due date; post as one-time `interest_adjustment` entry in `loan_ledger`
3. Regenerate repayment schedule from next EMI onwards with new due date
4. Trigger mandate amendment (via eNACH / UPI Autopay) to reflect new presentation date
5. Notify customer (SMS + email) with new due date and first EMI under new schedule
6. Record in `loan_due_date_changes`

**Mandate amendment dependency:** Due date change is held in `PENDING_MANDATE_AMENDMENT` status until the mandate vendor confirms the new presentation date. If mandate amendment fails within 72 hours, due date change is rolled back.

**Table:** `loan_due_date_changes` — `loan_id`, `old_due_day`, `new_due_day`, `broken_period_interest`, `status` (`pending_mandate` / `active` / `rolled_back`), `requested_by`, `approved_at`.

---

### 6.22 Moratorium Module (v4 — new)

A standalone moratorium is a temporary suspension of repayment obligations. It is **distinct from restructuring** — it does not revise the loan terms permanently and carries a different regulatory classification (no SMA upgrade protection unless RBI-mandated).

**Moratorium types:**

| Type | Principal | Interest |
|---|---|---|
| Full moratorium | Deferred | Deferred (accumulated) |
| Interest-only moratorium | Deferred | Collected monthly as-is |

**Trigger:** Admin / credit committee action. Requires maker-checker approval at Credit Committee level minimum (≥ Branch Head for ≤ 3 months; Credit Committee for > 3 months).

**Interest handling during moratorium:**
- Accrued daily per §6.18; credited to `loan_moratoriums.deferred_interest` instead of EMI demand
- On moratorium end, deferred interest is spread equally across remaining EMIs (revised EMI amount) — or collected as a lump sum on the first post-moratorium due date (configurable per `product_master.moratorium_interest_recovery`)

**Schedule behaviour:**
- EMIs due during moratorium are marked `status = 'moratorium'` in `repayment_schedules`; not treated as overdue
- Tenure extended by moratorium duration (default); or EMI amount increased to absorb deferred interest (per product config)
- DPD does **not** accrue during an approved moratorium

**Table:** `loan_moratoriums` — `loan_id`, `type`, `start_date`, `end_date`, `deferred_principal`, `deferred_interest`, `status` (`active` / `ended` / `cancelled`), `approved_by`, `approval_role`.

**Events:** `moratorium.started` → Notification Service, DPD Engine (suppress DPD); `moratorium.ended` → Schedule Engine (recalculate), Notification Service.

---

### 6.23 Prepayment & Foreclosure Lock-in Enforcement (v4 — new)

Many products prohibit or penalise early repayment within a lock-in window. This module enforces those rules at the Closure Module and Part-prepayment Module boundaries.

**Configuration (in `product_master`):**

| Field | Description |
|---|---|
| `lock_in_months` | Months from disbursal during which prepayment / foreclosure is blocked or charged |
| `lock_in_action` | `block` (request rejected) or `charge` (higher foreclosure fee applies) |
| `foreclosure_charge_within_lockin_pct` | Charge % if `lock_in_action = 'charge'` |
| `foreclosure_charge_post_lockin_pct` | Charge % after lock-in window |
| `prepayment_min_amount_inr` | Minimum part-prepayment amount |
| `prepayment_max_pct_per_year` | Max % of outstanding principal that can be prepaid in a 12-month window |

**RBI rules enforced:**
- Floating-rate retail loans: zero foreclosure charge after lock-in (RBI Master Direction)
- Fixed-rate loans: charge allowed but must be disclosed in KFS
- Cooling-off period (3 days post-disbursal): no foreclosure charge regardless of lock-in

**Lock-in check flow:**
1. Closure / part-prepayment request received
2. Compute `months_since_disbursal` = months between `loans.disbursed_at` and today
3. If `months_since_disbursal < lock_in_months`:
   - `lock_in_action = 'block'` → return `HTTP 422` with reason `WITHIN_LOCK_IN_PERIOD`
   - `lock_in_action = 'charge'` → apply `foreclosure_charge_within_lockin_pct`; quote shown to customer for confirmation
4. If `months_since_disbursal >= lock_in_months` and loan is floating-rate → zero charge
5. All charge overrides recorded in `foreclosure_requests.lock_in_override_reason`

---

### 6.24 TDS (Tax Deducted at Source) Module (v4 — new)

Applicable where the borrower is a corporate entity or where annual interest paid exceeds the statutory threshold (currently ₹40,000 for NBFCs under Section 194A of the Income Tax Act, 1961).

**TDS deduction flag:** `loans.tds_applicable = TRUE` set by LOS at disbursal based on borrower PAN category (individual vs. company) and expected annual interest.

**TDS deduction flow:**
1. At each EMI posting, if `tds_applicable = TRUE`, compute TDS on interest component at prevailing rate (10% standard; lower if borrower submits Form 15G/15H)
2. Net EMI demand = EMI – TDS amount; payment link raised for net amount
3. TDS amount recorded in `tds_deductions` table; NBFC remits to Income Tax Department by 7th of following month
4. Form 26AS reconciliation: match `tds_deductions` against TRACES portal data quarterly

**Form 15G / 15H handling:** Borrower submits declaration → `loans.tds_rate_override = 0`; stored in S3; valid for one financial year.

**Form 16A generation:** Quarterly; generated by TDS Module as PDF (via Puppeteer), stored in S3, delivered to borrower via email and accessible at `GET /loans/:id/tds/form16a?quarter=Q1-2025`.

**Table:** `tds_deductions` — `loan_id`, `payment_id`, `interest_amount`, `tds_rate_pct`, `tds_amount`, `remittance_challan_no`, `quarter`, `form16a_s3_key`.

**Cron:** `tds_remittance_report` — runs on 5th of each month; generates challan data for NBFC finance team.

---

### 6.25 GST Tax Invoice Module (v4 — new)

Generates statutory tax invoices for all fee and charge events. Required under CGST Act 2017. **Note: GST does not apply to interest income; it applies to processing fees, bounce charges, penalty charges, foreclosure charges, statement reissue fees, and legal charges.**

**Invoice trigger events:**

| Charge Event | Invoice Type |
|---|---|
| Bounce charge applied | Tax Invoice |
| Penalty charge applied (daily accrual above threshold, or on-demand) | Tax Invoice |
| Foreclosure charge collected | Tax Invoice |
| Part-prepayment charge collected | Tax Invoice |
| Legal notice charge applied | Tax Invoice |
| Statement reissue fee charged | Tax Invoice |

**Invoice content:** NBFC GSTIN, borrower name, loan account number, charge description, base amount, CGST (9%), SGST (9%) or IGST (18%) based on state of supply, invoice date, sequential invoice number.

**Invoice number sequence:** `GST-{tenant_code}-{YYYY}-{NNNNNN}` per tenant per financial year; stored in `gst_invoice_sequences` table.

**Delivery:** PDF stored in S3; linked from `gst_invoices.s3_key`; delivered via ZeptoMail email at time of charge application. Accessible at `GET /loans/:id/invoices` (list) and `GET /loans/:id/invoices/:invoice_id` (download).

**GSTR-1 export:** Monthly cron on 5th generates a CSV extract of all `gst_invoices` for the prior month, formatted per GSTN portal specification, delivered to finance team via S3 + email.

**Table:** `gst_invoices` — `loan_id`, `charge_event_id`, `charge_type`, `base_amount`, `gst_rate_pct`, `cgst`, `sgst`, `igst`, `invoice_number`, `invoice_date`, `s3_key`, `delivered_at`.

---

### 6.26 Cross-Sell Engine (Phase 6 — placeholder)

Evaluates closed or active loans for cross-sell eligibility daily and publishes signals to the LOS / marketing layer. Owned by LMS (data source) but acts only as a signal emitter — product decisions and offer rendering are outside LMS scope.

**Eligibility signals emitted (via `crosssell.eligible` event):**

| Signal | Condition |
|---|---|
| `REPEAT_LOAN_ELIGIBLE` | Loan closed normally, DPD never exceeded 30, outstanding = ₹0 |
| `TOP_UP_SIGNAL` | Active loan, > 40% principal repaid, DPD = 0 for last 6 months |
| `UPGRADE_PRODUCT_SIGNAL` | Payday borrower, 3+ successful cycles, never NPA |
| `INELIGIBLE` | Any NPA, OTS, written-off, or settled_legal history |

The LOS / AI-ML Risk Engine consumes `crosssell.eligible` and decides whether to make an offer. LMS has no further involvement.

---

## 7. External Integrations (LMS-Specific)

| Integration | Vendor | Purpose | Direction |
|---|---|---|---|
| eNACH (auto-debit) | Digio | Register & execute EMI mandate debits | Outbound + Inbound webhook |
| UPI Autopay | Razorpay | UPI recurring mandate for EMI collection | Outbound + Inbound webhook |
| Payment Links | Razorpay | Manual EMI / penalty payment links | Outbound + Inbound webhook |
| Credit Bureau | TransUnion CIBIL | Monthly loan account status reporting | Outbound batch |
| Credit Bureau | Equifax India | Monthly loan account status reporting | Outbound batch |
| Credit Bureau | Experian India | Monthly loan account status reporting | Outbound batch |
| SMS | Tata DLT (TTBS) | EMI reminders, bounce alerts, NOC SMS | Outbound |
| Email | Zoho ZeptoMail | NOC, statements, foreclosure quotes, KFS | Outbound |
| WhatsApp | Razorpay / Interakt | Payment links, reminders, NOC delivery | Outbound |
| PDF Generation | Puppeteer (self-hosted) | NOC, statements, schedules, RBI reports | Internal |
| Object Storage | AWS S3 (ap-south-1) | Document storage (NOC, KFS, statements) | Internal |
| Collection Agencies | Partner SFTP / API | Account export + remittance ingestion | Outbound batch + Inbound batch |
| SARFAESI / Legal | Internal legal team portal | Proceedings tracking, recovery amounts | Internal API |
| CERSAI | CERSAI Web API | Register / release security interest for secured loans | Outbound |

---

## 8. Data Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                       LMS DATA STORES                                 │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  PostgreSQL 17  (Primary — RDS Multi-AZ, ap-south-1)         │    │
│  │                                                              │    │
│  │  Core tables:                                                │    │
│  │  loans · repayment_schedules · loan_ledger (partitioned)     │    │
│  │  payments · mandates · bounce_events · penalty_ledger        │    │
│  │  foreclosure_requests · part_prepayment_requests             │    │
│  │  loan_restructuring · ots_settlements · npa_provisioning     │    │
│  │  credit_bureau_reports · regulatory_reports · loan_waivers   │    │
│  │  collection_assignments · collection_interactions            │    │
│  │  legal_proceedings · rate_reset_events                       │    │
│  │  loan_moratoriums · loan_due_date_changes · loan_statements  │    │
│  │  tds_deductions · gst_invoices · gst_invoice_sequences       │    │
│  │                                                              │    │
│  │  Master / config tables:                                     │    │
│  │  charge_master · product_master · collection_rule_master      │    │
│  │  collection_agency_master · tenant_configs                   │    │
│  │  bank_holiday_calendar · payment_suspense                   │    │
│  │  (grievances table owned by Grievance Service, not LMS)      │    │
│  │                                                              │    │
│  │  PII fields: AES-256-GCM encrypted; keys in AWS KMS          │    │
│  │  loan_ledger: INSERT-only (row-level security enforced)      │    │
│  │  Read replica for reporting / dashboard queries              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌───────────────────────────┐  ┌───────────────────────────────┐    │
│  │  Redis 8  (ElastiCache)   │  │  AWS S3  (ap-south-1)         │    │
│  │                           │  │                               │    │
│  │  • Idempotency keys (UTR) │  │  • NOC PDFs                   │    │
│  │  • Payment dedup cache    │  │  • Account statements         │    │
│  │  • DPD summary cache      │  │  • Signed loan agreements     │    │
│  │  • Rate-limit counters    │  │  • KFS documents              │    │
│  │  • Config cache (5m TTL)  │  │  • RBI reports                │    │
│  │  • Waiver approval locks  │  │  SSE-S3 + signed URLs         │    │
│  └───────────────────────────┘  └───────────────────────────────┘    │
│  ┌───────────────────────────────────────────────────────────────┐    │
│  │  MongoDB  (DocumentDB / Atlas)                                │    │
│  │  • notification_logs  • audit_trail_overflow                  │    │
│  │  • webhook_raw_payloads (Digio / Razorpay raw JSON)           │    │
│  │  • collection_interaction_logs (agency call notes, visits)    │    │
│  └───────────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────────┘
```

**Data residency:** All stores run in AWS `ap-south-1` (Mumbai) — mandatory per RBI data localisation circular.

---

## 9. Event-Driven Architecture

LMS is event-driven for all async operations. Events flow through Kafka (AWS MSK) / SQS.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     EVENT FLOW (LMS v2)                             │
│                                                                     │
│  LOS ──[loan.disbursed]──────────────────► LMS Schedule Engine     │
│  Risk Engine ──[rate.changed]────────────► LMS Float Reset Handler │
│                                                                     │
│  Digio ──[mandate.registered]────────────► LMS Mandate Module      │
│  Digio ──[nach.debit.success/failed]─────► LMS Payment Module      │
│  Razorpay ──[payment.captured]───────────► LMS Payment Module      │
│  Razorpay ──[payment.failed]─────────────► LMS Bounce Handler      │
│  Agency Portal ──[remittance.batch]──────► LMS Payment Module      │
│                                                                     │
│  LMS ──[payment.received]────────────────► Notification Svc        │
│  LMS ──[payment.failed]──────────────────► Notification Svc        │
│                                            Collection Engine        │
│  LMS ──[dpd.updated]─────────────────────► Notification Svc        │
│                                            Collection Engine        │
│                                            Reporting Svc            │
│  LMS ──[npa.classified]──────────────────► Collection Engine       │
│                                            Bureau Reporting         │
│                                            Legal Team               │
│  LMS ──[loan.closed]─────────────────────► NOC Service             │
│                                            Notification Svc         │
│                                            Bureau Reporting         │
│                                            Cross-sell Engine        │
│  LMS ──[noc.generated]───────────────────► Notification Svc        │
│                                            Grievance Service        │
│  LMS ──[reconciliation.mismatch]─────────► Grievance Service       │
│  LMS ──[waiver.applied]──────────────────► Audit Svc · Notif.      │
│  LMS ──[rate.reset.applied]──────────────► Notification Svc        │
│  LMS ──[agency.assigned]─────────────────► Collection Agency Svc   │
│  LMS ──[legal.notice.issued]─────────────► Legal Team Portal       │
│                                                                     │
│  Grievance Svc ──[waiver.approved]───────► LMS Waiver API          │
│  Legal Portal ──[recovery.realised]──────► LMS Payment Module      │
│                                                                     │
│  LMS ──[bounce.charge.applied]───────────► Notification Svc        │
│                                            GST Invoice Module       │
│  LMS ──[moratorium.started]──────────────► Notification Svc        │
│                                            DPD Engine (suppress)    │
│  LMS ──[moratorium.ended]────────────────► Schedule Engine         │
│                                            Notification Svc         │
│  LMS ──[statement.generated]─────────────► Notification Svc        │
│  LMS ──[crosssell.eligible]──────────────► LOS / AI-ML Risk Engine │
│  LMS ──[due_date.changed]────────────────► Notification Svc        │
│                                            Mandate Service          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 10. Background Processing Architecture

All time-based operations run as Kubernetes CronJobs on the same EKS cluster. Each job writes its result to `job_execution_logs` and publishes completion events.

```
00:05 IST  ── daily_interest_accrual
00:30 IST  ── dpd_engine  ─────────────── (core — highest priority)
01:00 IST  ── penalty_accrual_engine
01:30 IST  ── npa_classifier
02:00 IST  ── provisioning_update  (1st of month only)
08:00 IST  ── enach_orchestrator  ─────── (eNACH due-date debit)
08:00 IST  ── enach_retry_d2  (bounce retry day 2)
08:00 IST  ── enach_retry_d3  (bounce retry day 3 — final)
09:00 IST  ── pre_debit_notification  ─── (T-1 SMS+WA — NPCI rule)
10:00 IST  ── overdue_reminders  (DPD 1–7)
10:30 IST  ── collection_escalation  (DPD 8–30 tele-calling queue)
11:00 IST  ── agency_assignment  (DPD 45+ → assign to agency)
11:00 IST  ── legal_queue  (DPD 60+ flag + legal notice charge)
11:30 IST  ── sarfaesi_notice_check  (DPD 90+ secured loans > ₹1L)
23:30 IST  ── payment_reconciliation
02:00 IST  ── bureau_reporting  (5th of month)
09:00 IST  ── rbi_monthly_return  (7th of month)
10:00 IST  ── cross_sell_engine  (daily)
Every 30m  ── noc_generation_queue
Every 1hr  ── waiver_application_queue  (process pending approved waivers)
Every 4hr  ── agency_export  (push delinquent account list to agencies)
05:00 IST  ── tds_remittance_report  (5th of month — challan data for finance)
05:30 IST  ── gstr1_extract  (5th of month — GST invoice CSV for GSTN portal)
06:00 IST  ── monthly_statement_generation  (5th of month)
10:00 IST  ── cross_sell_engine  (daily)
Every 6hr  ── due_date_change_mandate_poll  (check pending mandate amendments; rollback if 72hr elapsed)
// grievance_sla_monitor: runs inside the Grievance Service, not LMS
```

---

## 11. Collection Escalation Architecture

```
DPD 0     [AUTO]  Pre-debit SMS + WhatsApp (T-1)
          [AUTO]  eNACH / UPI Autopay debit on due date
          │
DPD 1–3   [AUTO]  Bounce charge applied
          [AUTO]  Debit retry D+2, D+3
          [AUTO]  SMS + WhatsApp: "EMI bounce, please pay"
          │
DPD 4–7   [AUTO]  Daily push notification + SMS
          │
DPD 8–30  [SEMI-AUTO]  Tele-calling queue opened (internal team)
          [SEMI-AUTO]  WhatsApp payment link sent by agent
          [AUTO]  Penalty accruing daily
          │
DPD 31–44 [MANUAL]  Field agent assigned (internal DSA pool)
          [AUTO]   Penalty accruing; escalation log updated
          │
DPD 45–59 [AUTO]   Collection agency assignment triggered
          [MANUAL] Agency agent calls and visits
          [AUTO]   Daily account file pushed to agency portal
          │
DPD 60–89 [AUTO]   Legal notice charge ₹500 applied at DPD 60
          [MANUAL] Legal notice dispatched (registered post + digital)
          [MANUAL] Senior collection manager / legal team engaged
          [AUTO]   Pre-NPA flag; credit committee review window
          │
DPD 90+   [AUTO]   NPA classified
          [AUTO]   Mandate cancelled; bureau updated NPA
          [MANUAL] Legal team / SARFAESI proceedings initiated
          │
NPA       OTS offer (tiered approval — see §6.11)
          OR
          SARFAESI / Recovery Suit
          OR
          Write-off (after full provisioning)
```

---

## 12. Security Architecture (LMS-Specific)

| Layer | Control |
|---|---|
| API authentication | JWT (15 min access token) + Refresh Token (7 days); RBAC roles: `customer` / `agent` / `admin` / `credit_manager` / `collection_manager` / `legal_team` / `grievance_service` / `system` |
| PII protection | PAN / Aadhaar decrypted only in LMS service memory; never logged; never in API response as plaintext |
| Ledger integrity | `loan_ledger` is INSERT-only enforced via PostgreSQL row-level security; no UPDATE or DELETE |
| Payment idempotency | UTR-based dedup in Redis (TTL 7 days); duplicate webhooks silently acknowledged |
| Race condition prevention | `SELECT ... FOR UPDATE` on `loans` row during every payment posting transaction |
| Webhook verification | HMAC-SHA256 signature verification on all Digio and Razorpay inbound webhooks |
| Document integrity | SHA-256 hash stored for every NOC and KFS; verified on download |
| Waiver integrity | Waiver record locked in Redis while approval in-flight; double-approval prevented |
| Data residency | All data stores in `ap-south-1` Mumbai; no cross-region replication outside India |
| Encryption at rest | AES-256-GCM for PII fields; AWS KMS key per tenant; S3 SSE-S3 for documents |
| Audit trail | Every state transition emits to `audit_logs` with `actor_id`, `actor_role`, `ip_address`, `before_state`, `after_state`, `timestamp` |
| Secrets management | Digio / Razorpay / Bureau credentials in AWS Secrets Manager; rotated every 90 days |
| Agency data security | Collection agency exports encrypted (AES-256); transmitted over SFTP with SSH key auth; contains only non-PII fields; PAN masked |

---

## 13. Compliance Architecture Summary

```
┌────────────────────────────────────────────────────────────────────────┐
│                  RBI COMPLIANCE COVERAGE IN LMS v2                     │
│                                                                        │
│  RBI DLG 2022                                                          │
│    ✓ KFS accessible throughout lifecycle              (S3 + API)       │
│    ✓ 3-day cooling-off window                         (LOS field)      │
│    ✓ Pre-debit notification T-1                       (cron + DLT)    │
│    ✓ Grievance resolution ≤ 15 days                   (Grievance Svc) │
│    ✓ Full cost disclosure at any point                (outstanding API)│
│                                                                        │
│  Penal Charges Circular (Jan 2024)                                     │
│    ✓ Penalty NOT capitalised into principal           (separate tables)│
│    ✓ Penal charges disclosed in KFS                   (KFS template)  │
│    ✓ No compound penal interest                       (engine design) │
│                                                                        │
│  Floating Rate Reset Circular (Aug 2023)                               │
│    ✓ Borrower notified of EMI / tenure change on reset                 │
│    ✓ Option to switch product (if product allows)     (handled in LOS) │
│                                                                        │
│  NPA & Prudential Norms                                                │
│    ✓ 90-day NPA classification                        (npa_classifier) │
│    ✓ Tiered provisioning (10/25/40/100%)              (prov. engine)  │
│    ✓ Credit bureau NPA reporting                      (bureau batch)  │
│                                                                        │
│  Fair Practice Code                                                    │
│    ✓ Payment: penalty → interest → principal          (postPayment)   │
│    ✓ Free annual statement                            (statement API) │
│    ✓ NOC within 7 days of closure                     (NOC engine)    │
│                                                                        │
│  SARFAESI Act 2002 / CERSAI                                            │
│    ✓ Section-13(2) notice tracked before enforcement                   │
│    ✓ Security interest registered / released via CERSAI API            │
│                                                                        │
│  Monthly Bureau Reporting                                              │
│    ✓ CIBIL + Equifax + Experian on 5th of month       (bureau module) │
│                                                                        │
│  CGST Act 2017                                                         │
│    ✓ 18% GST on fees, penalty, bounce (not on interest)               │
│    ✓ GST tracked per charge row                                        │
│                                                                        │
│  DPDP Act 2023 / IT Act 2000                                           │
│    ✓ All data in India (ap-south-1)                                    │
│    ✓ PAN / Aadhaar AES-256 encrypted at field level                    │
│    ✓ Agency data exports — PAN masked, non-PII only                    │
│                                                                        │
│  RBI Ombudsman Scheme 2021                                             │
│    ✓ Escalation path in Grievance Service                              │
│    ✓ LMS publishes events; Grievance Svc tracks SLA                    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 14. Scalability & Availability

| Concern | Design |
|---|---|
| Service scaling | LMS runs as Kubernetes Deployment (EKS); HPA scales pods on CPU > 70% |
| Database | RDS PostgreSQL Multi-AZ; `loan_ledger` partitioned by month |
| Read vs. write separation | All reporting / dashboard queries routed to read replica |
| Cron job reliability | Each cron is a K8s CronJob; idempotent design; dead-letter retry on failure |
| Webhook throughput | Webhook endpoints rate-limited at 500 req/min; async via SQS |
| Lock contention | Row-level lock on `loans` during payment posting; Redis lock for concurrent mandate ops and waiver approvals |
| Agency batch processing | Bulk inserts for agency remittances via COPY; processed in off-peak window (01:00–05:00 IST) |
| RPO / RTO | PostgreSQL: automated snapshots every 1 hour (RPO = 1hr); Multi-AZ failover < 60s (RTO) |
| Availability target | 99.9% uptime for payment-critical paths (debit, reconciliation, NOC) |

---

## 15. Technology Stack (LMS)

| Layer | Technology |
|---|---|
| API service | Node.js 22 LTS (Express 5) — primary; Python (FastAPI) — calculation-heavy engines |
| Database | PostgreSQL 17 (RDS Multi-AZ) |
| Cache / Dedup | Redis 8 (ElastiCache) |
| Document store | MongoDB (DocumentDB) — webhook logs, notification logs, collection interaction logs |
| Object storage | AWS S3 (server-side encrypted, ap-south-1) |
| Message queue | Apache Kafka (AWS MSK) / AWS SQS |
| Background jobs | Kubernetes CronJobs on AWS EKS |
| PDF generation | Puppeteer (self-hosted Node.js microservice) |
| Encryption | AES-256-GCM at field level; AWS KMS key management |
| Secrets | AWS Secrets Manager |
| Monitoring | Datadog APM + Sentry (error tracking) + AWS CloudWatch (infra) |
| Alerting | PagerDuty (for payment failures, cron failures, NPA classification spikes) |
| CI/CD | GitHub Actions → ECR → EKS (rolling deploy) |

---

## 16. Implementation Phases

| Phase | Milestone | Key LMS Deliverables |
|---|---|---|
| **Phase 1** | Weeks 1–4 | DB schema, loan account API, repayment schedule generator, manual payment posting, basic admin dashboard |
| **Phase 2** | Weeks 5–8 | eNACH / UPI Autopay webhook handlers, DPD engine, penalty engine, pre-debit notification cron |
| **Phase 3** | Weeks 9–12 | Foreclosure engine, part-prepayment (both recalc modes), NOC generator, NPA classifier, monthly bureau reporting |
| **Phase 4** | Weeks 13–16 | Loan restructuring (maker-checker), OTS settlement (tiered approval), RBI monthly return, CRILC reporting, reconciliation engine, waiver governance module, waiver API (consumed by Grievance Svc) |
| **Phase 5** | Weeks 17–20 | Collection agency integration (export + remittance), legal proceedings tracker, SARFAESI pipeline, CERSAI integration, float rate reset handler |
| **Phase 6** | Ongoing | Cross-sell engine, BI dashboards, provisioning automation, model-driven collection prioritisation, Ombudsman quarterly return |

---

## 17. Production Go-Live Checklist (v4 — new)

Before promoting LMS to production, all items below must be verified.

### 17.1 Database

| Item | Verified |
|---|---|
| All 25 table schemas applied via migration tool (Flyway / Liquibase) | ☐ |
| `loan_ledger` monthly partitions created for current year + next 3 months | ☐ |
| All composite indexes from Section 2.26.1 created | ☐ |
| `loan_account_number` sequence created per tenant | ☐ |
| PostgreSQL RLS enabled on all tables (`loan_ledger`, `audit_trail`, `consent_log`) | ☐ |
| Read replica configured for dashboard/reporting queries | ☐ |
| Automated monthly partition creation job scheduled (pg_cron or Lambda) | ☐ |

### 17.2 Seed Data

| Item | Verified |
|---|---|
| `product_master` seeded (PAYDAY_30D, EMI_6M, EMI_12M, EMI_24M) | ☐ |
| `charge_master` seeded (5 charge types with GST rates) | ☐ |
| `collection_rule_master` seeded (DPD 0 → 999 coverage, no gaps) | ☐ |
| `tenant_configs` seeded (10 system defaults) | ☐ |
| `bank_holiday_calendar` seeded for current year | ☐ |
| All seed `created_by` UUIDs point to a real system user record | ☐ |

### 17.3 Integrations

| Item | Verified |
|---|---|
| Digio eNACH API credentials configured in AWS Secrets Manager | ☐ |
| Razorpay UPI Autopay API credentials configured | ☐ |
| HMAC-SHA256 webhook secrets configured for Digio + Razorpay | ☐ |
| CIBIL / Equifax / Experian API credentials and IP whitelist configured | ☐ |
| Tata DLT SMS sender ID approved and configured | ☐ |
| Zoho ZeptoMail API token configured | ☐ |
| All integration health checks passing in staging | ☐ |

### 17.4 Infrastructure

| Item | Verified |
|---|---|
| All 18 CronJobs deployed to K8s with correct IST schedules | ☐ |
| All 16 Kafka/SQS topics created with DLQ topics paired | ☐ |
| DLQ depth alerts configured (PagerDuty P1 for critical topics) | ☐ |
| Circuit breaker Redis keys initialised (`circuit:digio`, `circuit:razorpay`) | ☐ |
| `GET /health` and `GET /ready` probes wired to K8s liveness/readiness | ☐ |
| Redis ElastiCache cluster running with correct TTLs | ☐ |
| S3 bucket created with SSE-S3 encryption and `ap-south-1` region | ☐ |

### 17.5 Compliance

| Item | Verified |
|---|---|
| All 20 RBI compliance checklist items in Section 9 verified | ☐ |
| Board-approved Credit Policy with LSA limits in place | ☐ |
| Data Protection Officer (DPO) appointed under DPDP Act 2023 | ☐ |
| `audit_trail` INSERT-only policy tested (UPDATE/DELETE returns error) | ☐ |
| NBFC RBI registration number confirmed for use in all communications | ☐ |

### 17.6 New Modules (v4)

| Item | Verified |
|---|---|
| `loan_moratoriums` table created; moratorium DPD suppression tested end-to-end | ☐ |
| `loan_due_date_changes` table created; mandate amendment rollback at 72hr tested | ☐ |
| `loan_statements` table created; interest certificate PDF verified for a financial year | ☐ |
| `tds_deductions` table created; Form 16A PDF generated and delivered for a test loan | ☐ |
| `gst_invoices` + `gst_invoice_sequences` tables created; GSTIN configured in `tenant_configs` | ☐ |
| GST invoice generated for bounce charge and foreclosure charge in staging | ☐ |
| Lock-in enforcement tested: block and charge modes; floating-rate zero-charge post-lock-in verified | ☐ |
| `product_master` seeded with `lock_in_months`, `lock_in_action`, foreclosure charge % fields | ☐ |
| Bounce charge same-day waiver logic tested (payment success within 4hr of bounce) | ☐ |
| GSTR-1 CSV extract format validated against GSTN portal specification | ☐ |
