# High-Level Design — Loan Management System (LMS) v3
## True Loan Bazaar (TLB) — Post-Disbursal Lifecycle

> **Version:** 3.0 | **Previous version:** LMS_HLD_v2.md
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
│  │  PostgreSQL 15  (Primary — RDS Multi-AZ, ap-south-1)         │    │
│  │                                                              │    │
│  │  Core tables:                                                │    │
│  │  loans · repayment_schedules · loan_ledger (partitioned)     │    │
│  │  payments · mandates · bounce_events · penalty_ledger        │    │
│  │  foreclosure_requests · part_prepayment_requests             │    │
│  │  loan_restructuring · ots_settlements · npa_provisioning     │    │
│  │  credit_bureau_reports · regulatory_reports · loan_waivers   │    │
│  │  collection_assignments · collection_interactions            │    │
│  │  legal_proceedings · rate_reset_events                       │    │
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
│  │  Redis 7  (ElastiCache)   │  │  AWS S3  (ap-south-1)         │    │
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
| API service | Node.js (Express) — primary; Python (FastAPI) — calculation-heavy engines |
| Database | PostgreSQL 15 (RDS Multi-AZ) |
| Cache / Dedup | Redis 7 (ElastiCache) |
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
