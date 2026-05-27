# High-Level Design — Alpha LMS
## Post-Disbursal Lifecycle

> **Scope:** This document describes the architecture, modules, integrations, and compliance framework of the LMS only.
> The LOS (Loan Origination System) is a separate service; it ends at disbursal confirmation + UTR receipt and hands off to the LMS via event.
>
> **Regulatory basis:** RBI Digital Lending Guidelines 2022 · RBI Master Direction NBFC-ND-SI 2016 · RBI Fair Practice Code · Penal Charges Circular (Aug 2023, eff. 01-Jan-2024) · Floating Rate Reset Circular (Aug 2023) · NPA / Prudential Norms · SARFAESI Act 2002 · CGST Act 2017 · IT Act 2000 · DPDP Act 2023

---

## 1. System Overview

The LMS is the financial backbone of Lending Platform from the moment a loan is disbursed until it is fully repaid, foreclosed, settled, or written off. It is the authoritative source of truth for every rupee owed, paid, and charged across all loan accounts.

**Boundary:**

```
LOS → [loan.disbursed event] → LMS owns everything from here
                                └── Repayment · Collection · Closure · Reporting
```

**Key responsibilities:**

| Responsibility | Description |
|---|---|
| Loan account ledger | Double-entry, tamper-proof financial record for every loan |
| Schedule generation | Amortisation table for EMI, flat-rate, and payday bullet loans |
| Interest accrual | Daily accrual on outstanding principal |
| EMI collection | Auto-debit orchestration via eNACH and UPI Autopay |
| Penalty engine | Late payment penalty and penal interest per RBI norms |
| DPD tracking | Daily DPD update and SMA classification (SMA-0 / SMA-1 / SMA-2) |
| NPA management | NPA classification, provisioning, and credit bureau reporting |
| Foreclosure | Quote generation, payment processing, mandate cancellation |
| Part-prepayment | Eligibility check, charge calculation, schedule recalculation |
| Restructuring | Loan restructuring with revised amortisation |
| OTS settlement | One-time settlement with approval workflow |
| NOC issuance | Tamper-proof NOC within 72 hours of closure |
| Regulatory reporting | RBI monthly return, CRILC SMA report, bureau submission |

---

## 2. LMS in the Lending Platform Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Lending PLATFORM                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      CLIENT LAYER                                   │    │
│  │   Flutter App (Android/iOS)    ·    React.js Web Portal             │    │
│  └─────────────────────────────┬───────────────────────────────────────┘    │
│                                │ HTTPS / TLS 1.3                            │
│  ┌─────────────────────────────▼───────────────────────────────────────┐    │
│  │           API GATEWAY  (AWS API GW / Kong)                          │    │
│  │       JWT Auth · Rate Limiting · Load Balancing · WAF               │    │
│  └────┬────────────────────────┬────────────────────────────┬──────────┘    │
│       │                        │                            │               │
│  ┌────▼──────┐          ┌──────▼──────┐             ┌───────▼────────┐      │
│  │   LOS     │          │  ── LMS ──  │             │  AI/ML Risk    │      │
│  │ (Loan     │ event ──►│  (THIS DOC) │             │  Engine        │      │
│  │  Origin.) │          │             │             │  (Underwriting)│      │
│  └───────────┘          └──────┬──────┘             └────────────────┘      │
│                                │                                            │
│  ┌─────────────────────────────▼───────────────────────────────────────┐    │
│  │                    SHARED CORE SERVICES                             │    │
│  │  Payment Svc · Notification Svc · Audit Svc · PDF Svc · DSA Engine │    │
│  └─────────────────────────────┬───────────────────────────────────────┘    │
│                                │                                            │
│  ┌─────────────────────────────▼───────────────────────────────────────┐    │
│  │                        DATA LAYER                                   │    │
│  │  PostgreSQL (Core) · Redis (Cache) · S3 (Docs) · MongoDB (Logs)    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
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
│  └─────────────────┘  └──────────────────┘  │   • Reconciliation      │   │
│                                              └──────────────────────────┘   │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │  DPD & SMA      │  │  Penalty Engine  │  │   NPA & Provisioning    │   │
│  │  Engine (Cron)  │  │  (Cron)          │  │   Engine (Cron)         │   │
│  │  • DPD calc     │  │  • Late penalty  │  │   • NPA classification  │   │
│  │  • SMA tagging  │  │  • Penal interest│  │   • Provisioning %      │   │
│  │  • Overdue flag │  │  • Legal charges │  │   • Write-off           │   │
│  └─────────────────┘  └──────────────────┘  └──────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐                                  │
│  │  Closure Module │  │  Reporting &     │  ┌──────────────────────────┐   │
│  │  • Foreclosure  │  │  Compliance      │  │   Grievance Service      │   │
│  │  • Part-prepay  │  │  • RBI return    │  │   (external — shared)    │   │
│  │  • OTS settle   │  │  • Bureau report │  │   queries LMS read APIs  │   │
│  │  • NOC gen      │  │  • CRILC SMA     │  │   sends waiver commands  │   │
│  └─────────────────┘  └──────────────────┘  └──────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Loan Lifecycle State Machine

```
                       ┌──────────────────┐
   [loan.disbursed] ──►│     ACTIVE        │◄─── normal ongoing state
                       └────────┬─────────┘
                                │
           ┌────────────────────┼─────────────────────┐
           │                    │                     │
           ▼                    ▼                     ▼
   ┌───────────────┐   ┌────────────────┐   ┌─────────────────┐
   │  CLOSED       │   │  FORECLOSED    │   │  RESTRUCTURED   │
   │ (normal repay)│   │ (early closure)│   │ (revised terms) │──► ACTIVE
   └───────────────┘   └────────────────┘   └─────────────────┘
           │                    │
           │    ┌───────────────┘
           ▼    ▼
   ┌──────────────────┐
   │  NOC GENERATED   │  ← final state for CLOSED and FORECLOSED
   └──────────────────┘

   ACTIVE ──(DPD 90+)──► NPA
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │  RECOVERED   │  │  SETTLED_OTS │  │  WRITTEN_OFF │
   │ (full repay) │  │ (OTS paid)   │  │ (provisioned)│
   └──────────────┘  └──────────────┘  └──────────────┘
```

**Valid status values:** `active` · `closed` · `foreclosed` · `restructured` · `npa` · `settled_ots` · `written_off`

---

## 5. Post-Disbursal Customer Journey

```
[LOS] loan.disbursed event
         │
         ▼
[LMS] Loan account created
      Repayment schedule generated
      Mandate activated
         │
         ├──────────────────────────────────────────────────┐
         ▼                                                  │
[T-1 before each due date]                                  │
  Pre-debit notification → SMS + WhatsApp (NPCI mandate)    │
         │                                                  │
         ▼                                                  │
[Due date]                                                  │
  Auto-debit initiated (eNACH / UPI Autopay)                │
         │                                                  │
    ┌────┴──────┐                                           │
    ▼ SUCCESS   ▼ FAILED                                    │
  EMI posted  Bounce charge applied                         │
  DPD = 0     DPD clock starts                             │
    │              │                                        │
    │         Retry D+2, D+3                               │
    │              │                                        │
    │         [DPD 1–7]  Soft reminders                    │
    │         [DPD 8–30] Tele-calling + WhatsApp link       │
    │         [DPD 31–60] Field escalation                  │
    │         [DPD 61–90] Legal notice                      │
    │         [DPD 90+]   NPA classification                │
    │                                                       │
    └────────────────────────────────────────────┐          │
                                                 ▼          │
                                         All EMIs paid      │
                                         Outstanding = ₹0   │
                                                 │          │
                                                 ▼          │
                                         Loan CLOSED ◄──────┘
                                         NOC generated (72hr SLA)
                                         Bureau updated → CLOSED
                                         Cross-sell eligibility evaluated
```

---

## 6. Module Descriptions

### 6.1 Loan Account Module
Single source of truth for any loan. Maintains the running financial state: `outstanding_principal`, `accrued_interest`, `total_overdue`, `total_penalty`, `total_bounce_charges`, `total_paid`. All updates are transaction-safe and atomic. Exposes full ledger, outstanding breakup, and document access to customers and admins.

### 6.2 Schedule Engine
Generates the amortisation table at loan creation. Supports three product structures:
- **EMI (Reducing Balance):** Standard monthly instalment; interest computed on outstanding principal
- **EMI (Flat Rate):** Fixed interest on original principal; higher effective cost
- **Payday (Bullet):** Single repayment on maturity; daily flat rate applied

Also handles broken-period interest (when disbursal date is not the 1st of the month), schedule recalculation post part-prepayment, and full restructuring.

### 6.3 Payment & Reconciliation Module
Receives payment signals from:
- Digio eNACH webhooks (auto-debit)
- Razorpay UPI Autopay webhooks (auto-debit)
- Razorpay Payment Link webhooks (manual pay)
- NEFT/IMPS credit alerts (manual bank transfer)

Applies payments using RBI Fair Practice Code priority order: penalty charges → bounce charges → interest → principal. Runs nightly reconciliation against gateway settlement files; auto-flags mismatches.

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

### 6.6 NPA & Provisioning Engine
Classifies accounts as NPA at DPD 90. Maintains provisioning per RBI Prudential Norms:

| NPA Duration | Classification | Provisioning |
|---|---|---|
| < 12 months | Sub-Standard | 10% |
| 12–24 months | Doubtful-1 | 25% |
| 24–36 months | Doubtful-2 | 40% |
| > 36 months | Doubtful-3 | 100% |
| Identified as loss | Loss Asset | 100% |

### 6.7 Closure Module
Handles three closure paths:
1. **Normal closure** — all EMIs paid; auto-detected when `outstanding_principal ≤ ₹0.01`
2. **Foreclosure** — customer-initiated early closure; charge based on risk band (2–4% of OP); 3-business-day quote validity
3. **OTS Settlement** — negotiated for NPA accounts; waiver components require credit committee / MD approval above threshold

On any closure: mandate is cancelled, remaining schedule rows are waived, NOC is generated within 72 hours, bureau is updated to `CLOSED`.

### 6.8 NOC Generation
Generates a tamper-proof PDF using Puppeteer PDF Service. SHA-256 hash stored alongside the S3 key. Delivered to customer via:
- ZeptoMail (Zoho) email with PDF attachment
- WhatsApp (Razorpay / Interakt) with 7-day signed S3 link
- SMS (Tata DLT) confirmation

RBI requirement: NOC within 7 days of closure for digital lending.

### 6.9 Regulatory Reporting Module
| Report | Frequency | Destination | Deadline |
|---|---|---|---|
| Credit Bureau Data (CIBIL / Equifax / Experian) | Monthly | Bureau APIs | 5th of month |
| RBI Monthly Return (DNBS-02) | Monthly | RBI COSMOS portal | 7th of month |
| CRILC SMA Report | Monthly | RBI (for exposures > ₹5 crore) | 21st of month |
| NPA Provisioning Statement | Monthly | Internal / CFO | 5th of month |
| Interest Rate Disclosure | Quarterly | RBI website publication | Quarterly |
| Fraud Reporting (> ₹1 lakh) | Event-triggered | RBI fraud monitoring | Within 7 days |

### 6.10 Grievance Service Interface (External)

Grievance Management is **not owned by the LMS**. It is a shared platform-level service that handles complaints across all touchpoints — LOS (KYC rejection, application disputes), LMS (penalty disputes, NOC delay, bureau correction), DSA engine (agent misconduct), and auth (login issues). Owning it inside LMS would leave pre-disbursal complaints without a home.

**What LMS exposes to the Grievance Service:**

| LMS API | Purpose |
|---|---|
| `GET /loans/:id/outstanding` | Fetch penalty / interest breakup for dispute resolution |
| `GET /loans/:id/ledger` | Full transaction history for a charge dispute |
| `GET /loans/:id/noc` | Retrieve NOC for delivery complaints |
| `POST /loans/:id/waiver` | Apply a charge waiver approved by Grievance Officer |
| `GET /loans/:id/bureau-status` | Check bureau reporting status for correction requests |

**LMS also publishes events the Grievance Service subscribes to:**
- `loan.closed` → auto-close any open NOC-delay ticket
- `noc.generated` → mark NOC delivery tickets resolved
- `payment.received` → auto-close unauthorised-debit tickets if refund confirmed

---

### 6.11 Master Tables (Configuration Layer)

Four master tables drive every LMS engine. No rate, charge, or rule is hardcoded — all values come from these tables. The pattern is consistent across all four:

| Governance rule | Implementation |
|---|---|
| Versioning | `effective_from` / `effective_till` — point-in-time lookup, historical audit |
| Multi-tenant | `tenant_id` (NULL = system default; tenant row takes precedence) |
| Maker-checker | `created_by` + `approved_by` — four-eyes approval before activation |
| Soft-disable | `is_active = FALSE` disables without data loss |
| Tax | GST rate stored per charge on `charge_master`; no separate tax table required |

| Master Table | Owned By | Drives |
|---|---|---|
| `charge_master` | Finance ops | Penalty engine · Bounce engine · Foreclosure engine · Part-prepayment engine |
| `product_master` | Product team | Schedule generator · Foreclosure rules · NOC SLA |
| `collection_rule_master` | Collections | DPD engine · Collection escalation workflow |

> **`interest_rate_master` is owned by LOS.** The AI/Risk engine assigns ROI during underwriting; the final rate arrives in the `loan.disbursed` event and is stamped on `loans.roi_monthly`. LMS reads that column directly and never queries the rate master.

**`tenant_configs`** is a key-value table for tenant-wide operational settings not tied to a specific product. Engines read from Redis (5-min TTL), falling back to this table on cache miss. A `NULL` tenant row holds system defaults.

| Key | Default | Engine |
|---|---|---|
| `reconciliation_tolerance_inr` | ₹1.00 | Payment reconciliation |
| `statement_auto_generate_day` | 5th of month | Statement cron |
| `notification_timing_pre_due_days` | 3, 1 | Reminder cron |
| `notification_timing_post_due_days` | 1, 3, 7 | Overdue reminder cron |
| `npa_classification_dpd` | 90 | NPA engine (RBI floor — cannot go below 90) |
| `crilc_report_submission_day` | 15 | Regulatory reporting cron |

**Charge master key fields:** `charge_code`, `calc_type` (flat / pct_outstanding / pct_emi), `fixed_amount`, `pct_rate`, `min_amount`, `max_amount`, `gst_applicable`, `gst_rate` (default 18%), `penal_capitalise` (always FALSE — RBI Jan 2024 circular).

**Product master key fields (LMS-only — eligibility fields live in LOS):** `interest_type`, `grace_period_days`, `enach_presentation_lead_days`, `foreclosure_allowed`, `foreclosure_lock_months`, `part_prepayment_allowed`, `part_prepayment_min_pct`, `part_prepayment_lock_months`, `restructuring_allowed`, `ots_allowed`, `noc_auto_issue_days`, `bureau_report_on_closure`.

**Collection rule master key fields:** `dpd_from`, `dpd_to`, `sma_bucket`, `action_type` (SMS / WhatsApp / Call queue L1 / Call queue L2 / Legal notice / Field visit / SARFAESI), `enach_retry_count`, `enach_retry_gap_days`, `legal_action_flag`.

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
│  │                                                              │    │
│  │  Master / config tables:                                     │    │
│  │  charge_master · product_master · collection_rule_master      │    │
│  │  tenant_configs                                              │    │
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
│  │  • Session tokens         │  │  • RBI reports                │    │
│  └───────────────────────────┘  │  SSE-S3 + signed URLs         │    │
│                                  └───────────────────────────────┘    │
│  ┌───────────────────────────────────────────────────────────────┐    │
│  │  MongoDB  (DocumentDB / Atlas)                                │    │
│  │  • notification_logs  • audit_trail_overflow                  │    │
│  │  • webhook_raw_payloads (Digio / Razorpay raw JSON)           │    │
│  └───────────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────────┘
```

**Data residency:** All stores run in AWS `ap-south-1` (Mumbai) — mandatory per RBI data localisation circular.

---

## 9. Event-Driven Architecture

LMS is event-driven for all async operations. Events flow through Kafka (AWS MSK) / SQS.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     EVENT FLOW (LMS)                                │
│                                                                     │
│  LOS ──[loan.disbursed]──────────────────► LMS Schedule Engine     │
│                                                                     │
│  Digio ──[mandate.registered]────────────► LMS Mandate Module      │
│  Digio ──[nach.debit.success/failed]─────► LMS Payment Module      │
│  Razorpay ──[payment.captured]───────────► LMS Payment Module      │
│  Razorpay ──[payment.failed]─────────────► LMS Bounce Handler      │
│                                                                     │
│  LMS ──[payment.received]────────────────► Notification Svc        │
│  LMS ──[payment.failed]──────────────────► Notification Svc        │
│                                            Collection Engine        │
│  LMS ──[dpd.updated]─────────────────────► Notification Svc        │
│                                            Collection Engine        │
│                                            Reporting Svc            │
│  LMS ──[npa.classified]──────────────────► Collection Engine       │
│                                            Bureau Reporting         │
│  LMS ──[loan.closed]─────────────────────► NOC Service             │
│                                            Notification Svc         │
│                                            Bureau Reporting         │
│                                            Cross-sell Engine        │
│  LMS ──[noc.generated]───────────────────► Notification Svc        │
│                                            Grievance Service        │
│                                                                     │
│  LMS ──[loan.closed]─────────────────────► Grievance Service       │
│         (auto-closes open NOC-delay tickets)                        │
│                                                                     │
│  Grievance Svc ──[waiver.approved]───────► LMS Waiver API          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 10. Background Processing Architecture

All time-based operations run as Kubernetes CronJobs on the same EKS cluster. Each job writes its result to `job_execution_logs` and publishes completion events.

```
00:05 IST  ── daily_interest_accrual
00:30 IST  ── dpd_engine  ──────────────────── (core — highest priority)
01:00 IST  ── penalty_accrual_engine
01:30 IST  ── npa_classifier
02:00 IST  ── provisioning_update  (1st of month only)
08:00 IST  ── enach_orchestrator  ──────────── (eNACH due-date debit)
08:00 IST  ── enach_retry_d2  (bounce retry day 2)
08:00 IST  ── enach_retry_d3  (bounce retry day 3 — final)
09:00 IST  ── pre_debit_notification  ────────  (T-1 SMS+WA — NPCI rule)
10:00 IST  ── overdue_reminders  (DPD 1–7)
10:30 IST  ── collection_escalation  (DPD 8–30 tele-calling queue)
11:00 IST  ── legal_queue  (DPD 60+ flag)
23:30 IST  ── payment_reconciliation
02:00 IST  ── bureau_reporting  (5th of month)
09:00 IST  ── rbi_monthly_return  (7th of month)
10:00 IST  ── cross_sell_engine  (daily)
// grievance_sla_monitor runs inside the Grievance Service, not LMS
Every 30m  ── noc_generation_queue  (process pending NOC jobs)
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
DPD 8–30  [SEMI-AUTO]  Tele-calling queue opened
          [SEMI-AUTO]  WhatsApp payment link sent by agent
          [AUTO]  Penalty accruing daily
          │
DPD 31–60 [MANUAL]  Field agent assigned
          [AUTO]   Legal notice cost added at DPD 60
          │
DPD 61–90 [MANUAL]  Senior collection manager
          [AUTO]   Pre-NPA flag; credit committee review
          │
DPD 90+   [AUTO]   NPA classified
          [AUTO]   Mandate cancelled; bureau updated
          [MANUAL] Legal team takes over
          │
NPA       OTS offer (credit committee approval)
          OR
          Legal proceedings (SARFAESI if secured)
          OR
          Write-off (after full provisioning)
```

---

## 12. Security Architecture (LMS-Specific)

| Layer | Control |
|---|---|
| API authentication | JWT (15 min access token) + Refresh Token (7 days); role-based: `customer` / `agent` / `admin` / `credit_manager` / `system` |
| PII protection | PAN / Aadhaar token decrypted only in LMS service memory; never logged; never in API response as plaintext |
| Ledger integrity | `loan_ledger` is INSERT-only enforced via PostgreSQL row-level security; no UPDATE or DELETE allowed on any row |
| Payment idempotency | UTR-based dedup in Redis (TTL 7 days); duplicate webhooks silently acknowledged |
| Race condition prevention | `SELECT ... FOR UPDATE` on `loans` row during every payment posting transaction |
| Webhook verification | HMAC-SHA256 signature verification on all Digio and Razorpay inbound webhooks before processing |
| Document integrity | SHA-256 hash stored for every NOC and KFS; verified on download |
| Data residency | All data stores in `ap-south-1` Mumbai; no cross-region replication outside India |
| Encryption at rest | AES-256-GCM for PII fields; AWS KMS key per tenant; S3 SSE-S3 for documents |
| Audit trail | Every state transition emits to `audit_logs` with `actor_id`, `actor_role`, `ip_address`, `before_state`, `after_state`, `timestamp` |
| Secrets management | Digio / Razorpay / Bureau credentials in AWS Secrets Manager; rotated every 90 days |

---

## 13. Compliance Architecture Summary

```
┌────────────────────────────────────────────────────────────────────────┐
│                  RBI COMPLIANCE COVERAGE IN LMS                        │
│                                                                        │
│  RBI DLG 2022                                                          │
│    ✓ KFS accessible to borrower throughout lifecycle  (S3 + API)       │
│    ✓ 3-day cooling-off window on new loans            (LOS field)      │
│    ✓ Pre-debit notification T-1                       (cron + DLT SMS) │
│    ✓ Grievance resolution ≤ 15 days                   (Grievance Svc)  │
│    ✓ Full cost disclosure at any point                (outstanding API) │
│                                                                        │
│  Penal Charges Circular (Jan 2024)                                     │
│    ✓ Penalty NOT capitalised into principal           (separate tables) │
│    ✓ Penal charges disclosed in KFS                   (KFS template)   │
│    ✓ No compound penal interest                       (engine design)  │
│                                                                        │
│  NPA & Prudential Norms                                                │
│    ✓ 90-day NPA classification                        (npa_classifier) │
│    ✓ Tiered provisioning (10/25/40/100%)              (provisioning    │
│                                                        engine)         │
│    ✓ Credit bureau NPA reporting                      (bureau batch)   │
│                                                                        │
│  Fair Practice Code                                                    │
│    ✓ Payment allocation: penalty → interest → principal               │
│    ✓ Free annual statement                            (statement API)  │
│    ✓ NOC within 7 days of closure                     (NOC engine)     │
│                                                                        │
│  Monthly Bureau Reporting                                              │
│    ✓ CIBIL + Equifax + Experian on 5th of month       (bureau module)  │
│                                                                        │
│  CGST Act 2017                                                         │
│    ✓ 18% GST on fees, penalty, bounce (not on interest)               │
│    ✓ GST tracked per charge row                       (separate fields)│
│                                                                        │
│  DPDP Act 2023 / IT Act 2000                                           │
│    ✓ All data in India (ap-south-1)                                    │
│    ✓ PAN / Aadhaar AES-256 encrypted at field level                    │
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
| High-value lock contention | Row-level lock on `loans` during payment posting; Redis lock for concurrent mandate ops |
| RPO / RTO | PostgreSQL: automated snapshots every 1 hour (RPO = 1hr); Multi-AZ failover < 60s (RTO) |
| Availability target | 99.9% uptime for payment-critical paths (debit, reconciliation, NOC) |

---

## 15. Technology Stack (LMS)

| Layer | Technology |
|---|---|
| API service | Node.js (Express) — primary; Python (FastAPI) — calculation-heavy engines |
| Database | PostgreSQL 15 (RDS Multi-AZ) |
| Cache / Dedup | Redis 7 (ElastiCache) |
| Document store | MongoDB (DocumentDB) — webhook logs, notification logs |
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
| **Phase 3** | Weeks 9–12 | Foreclosure engine, part-prepayment, NOC generator, NPA classifier, monthly bureau reporting |
| **Phase 4** | Weeks 13–16 | Loan restructuring, OTS settlement, RBI monthly return, CRILC reporting, reconciliation engine, waiver API (consumed by Grievance Svc) |
| **Phase 5** | Ongoing | Cross-sell engine, BI dashboards, provisioning automation, model-driven collection prioritisation |
