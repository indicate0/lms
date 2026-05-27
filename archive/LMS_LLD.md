# Low-Level Design — Alpha LMS
## Alpha LMS — Post-Disbursal Lifecycle

> **Scope:** This document covers the LMS only. The LOS (Loan Origination System) ends at disbursal confirmation + UTR receipt. LMS ownership begins from that moment.
>
> **Regulatory basis:** RBI Digital Lending Guidelines 2022 · RBI Master Direction NBFC-ND-SI 2016 · RBI Fair Practice Code · Penal Charges Circular (Aug 2023, effective 01-Jan-2024) · RBI Floating Rate Reset Circular (Aug 2023) · NPA / Prudential Norms Circular · SARFAESI Act 2002 · CERSAI Act · CGST Act 2017 · IT Act 2000

---

## 1. LMS Boundary & Responsibilities

```
LOS hands off to LMS when:
  loan_applications.status = 'disbursed'
  AND disbursal UTR is stored
  AND repayment mandate is active

LMS owns:
  ├── Loan account ledger
  ├── Repayment schedule (amortisation table)
  ├── Daily interest accrual
  ├── EMI posting & reconciliation
  ├── Penalty / bounce charge engine
  ├── DPD classification & SMA tagging
  ├── Foreclosure & part-prepayment engine
  ├── Loan restructuring
  ├── NOC generation
  ├── Credit bureau reporting
  ├── Regulatory reporting (SMA, NPA, CRILC)
  └── Waiver API  ← consumed by Grievance Service (external)
  // Grievance management is NOT owned by LMS — see Section 3.9
```

---

## 2. Database Schema (PostgreSQL — LMS-Specific)

> All tables include `tenant_id UUID` for row-level multi-tenant isolation.
> All monetary fields use `NUMERIC(14,2)` — no floating point.
> All timestamps are `TIMESTAMPTZ` stored in UTC; display in IST (UTC+5:30).

---

### 2.1 `loans`

```sql
loans (
  id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id              UUID         NOT NULL REFERENCES tenants(id),
  application_id         UUID         NOT NULL REFERENCES loan_applications(id),
  customer_id            UUID         NOT NULL REFERENCES customers(id),
  agent_id               UUID         REFERENCES agents(id),

  -- Financials (immutable after creation)
  sanctioned_amount      NUMERIC(14,2) NOT NULL,
  disbursed_amount       NUMERIC(14,2) NOT NULL,   -- after all upfront deductions
  disbursal_utr          VARCHAR(50)  NOT NULL,
  disbursal_date         DATE         NOT NULL,
  disbursal_channel      VARCHAR(20)  NOT NULL,    -- 'IMPS' | 'UPI' | 'NEFT'
  principal              NUMERIC(14,2) NOT NULL,   -- = sanctioned_amount
  interest_type          VARCHAR(20)  NOT NULL,    -- 'reducing_balance' | 'flat' | 'daily_flat'
  roi_monthly            NUMERIC(6,4) NOT NULL,    -- e.g. 2.50 (%)
  roi_daily              NUMERIC(8,6),             -- populated for payday loans
  tenure_months          INTEGER,                  -- null for payday
  tenure_days            INTEGER,                  -- null for EMI loans
  maturity_date          DATE         NOT NULL,

  -- Mutable running state
  outstanding_principal  NUMERIC(14,2) NOT NULL,
  accrued_interest       NUMERIC(14,2) NOT NULL DEFAULT 0,
  total_overdue          NUMERIC(14,2) NOT NULL DEFAULT 0,
  total_penalty          NUMERIC(14,2) NOT NULL DEFAULT 0,
  total_bounce_charges   NUMERIC(14,2) NOT NULL DEFAULT 0,
  total_paid             NUMERIC(14,2) NOT NULL DEFAULT 0,

  -- Status & classification
  status                 VARCHAR(20)  NOT NULL DEFAULT 'active',
    -- 'active' | 'closed' | 'foreclosed' | 'restructured' | 'npa' |
    -- 'written_off' | 'settled_ots'
  dpd                    INTEGER      NOT NULL DEFAULT 0,
  sma_category           VARCHAR(10),  -- NULL | 'SMA-0' | 'SMA-1' | 'SMA-2'
  npa_classification     VARCHAR(20),  -- NULL | 'sub_standard' | 'doubtful_1' |
                                       --        'doubtful_2' | 'doubtful_3' | 'loss'
  npa_since              DATE,
  first_default_date     DATE,         -- date of first missed EMI

  -- Provisioning
  provision_pct          NUMERIC(5,2) DEFAULT 0,
  provision_amount       NUMERIC(14,2) DEFAULT 0,

  -- Closure
  closed_at              TIMESTAMPTZ,
  closure_type           VARCHAR(20),  -- 'normal' | 'foreclosure' | 'ots' | 'written_off'
  noc_generated_at       TIMESTAMPTZ,
  noc_s3_key             VARCHAR(500),

  -- Audit
  created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_loans_customer    ON loans(customer_id);
CREATE INDEX idx_loans_tenant      ON loans(tenant_id);
CREATE INDEX idx_loans_status      ON loans(status);
CREATE INDEX idx_loans_dpd         ON loans(dpd) WHERE status = 'active';
CREATE INDEX idx_loans_maturity    ON loans(maturity_date) WHERE status = 'active';
```

---

### 2.2 `repayment_schedules`

One row per installment. Immutable after generation except `status`, `penalty_amt`, `paid_at`.

```sql
repayment_schedules (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  tenant_id        UUID         NOT NULL,
  installment_no   INTEGER      NOT NULL,   -- 1-indexed; payday always has 1

  -- Due amounts (set at schedule generation)
  due_date         DATE         NOT NULL,
  principal_amt    NUMERIC(14,2) NOT NULL,
  interest_amt     NUMERIC(14,2) NOT NULL,
  emi_amount       NUMERIC(14,2) NOT NULL,  -- principal_amt + interest_amt

  -- Running charges (appended as events occur)
  bounce_charge    NUMERIC(14,2) NOT NULL DEFAULT 0,
  bounce_gst       NUMERIC(14,2) NOT NULL DEFAULT 0,
  penalty_amt      NUMERIC(14,2) NOT NULL DEFAULT 0,
  penalty_gst      NUMERIC(14,2) NOT NULL DEFAULT 0,
  waiver_amt       NUMERIC(14,2) NOT NULL DEFAULT 0,

  -- Settlement
  total_due        NUMERIC(14,2) GENERATED ALWAYS AS
                   (emi_amount + bounce_charge + bounce_gst
                    + penalty_amt + penalty_gst - waiver_amt) STORED,
  total_paid       NUMERIC(14,2) NOT NULL DEFAULT 0,
  balance_due      NUMERIC(14,2) GENERATED ALWAYS AS
                   (emi_amount + bounce_charge + bounce_gst
                    + penalty_amt + penalty_gst - waiver_amt - total_paid) STORED,

  status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- 'pending' | 'paid' | 'partial' | 'overdue' | 'waived' | 'restructured'
  dpd_on_payment   INTEGER,     -- DPD at the time payment was received
  paid_at          TIMESTAMPTZ,

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

  UNIQUE (loan_id, installment_no)
);

CREATE INDEX idx_sched_loan       ON repayment_schedules(loan_id);
CREATE INDEX idx_sched_due_date   ON repayment_schedules(due_date)
  WHERE status IN ('pending', 'overdue', 'partial');
```

---

### 2.3 `loan_ledger`

Double-entry accounting ledger. Every financial event creates one or more rows.

```sql
loan_ledger (
  id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id        UUID         NOT NULL REFERENCES loans(id),
  tenant_id      UUID         NOT NULL,
  schedule_id    UUID         REFERENCES repayment_schedules(id),
  payment_id     UUID         REFERENCES payments(id),

  entry_type     VARCHAR(40)  NOT NULL,
    -- 'principal_due' | 'interest_due' | 'penalty_charge' | 'bounce_charge'
    -- | 'payment_received' | 'payment_reversed' | 'waiver' | 'foreclosure_charge'
    -- | 'part_prepayment' | 'restructuring_charge' | 'insurance_claim'
    -- | 'write_off' | 'ots_settlement' | 'gst_charge'

  debit          NUMERIC(14,2) NOT NULL DEFAULT 0,
  credit         NUMERIC(14,2) NOT NULL DEFAULT 0,
  running_balance NUMERIC(14,2) NOT NULL,  -- outstanding after this entry

  narration      TEXT,
  effective_date DATE         NOT NULL,
  created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  created_by     UUID,         -- system UUID or admin user UUID
  reference_no   VARCHAR(100)  -- UTR / mandate ref / internal ref
);

CREATE INDEX idx_ledger_loan      ON loan_ledger(loan_id);
CREATE INDEX idx_ledger_date      ON loan_ledger(effective_date);
-- Partitioned by month for performance at scale
```

---

### 2.4 `payments`

Records every incoming payment event regardless of source channel.

```sql
payments (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  tenant_id        UUID         NOT NULL,
  schedule_id      UUID         REFERENCES repayment_schedules(id),
  mandate_id       UUID         REFERENCES mandates(id),

  amount           NUMERIC(14,2) NOT NULL,
  channel          VARCHAR(20)  NOT NULL,
    -- 'enach' | 'upi_autopay' | 'upi_manual' | 'neft' | 'imps'
    -- | 'rtgs' | 'cash' | 'cheque' | 'pos'
  payment_type     VARCHAR(20)  NOT NULL,
    -- 'emi' | 'penalty' | 'bounce_charge' | 'foreclosure' | 'part_prepayment'
    -- | 'ots' | 'excess' | 'refund'
  utr_ref          VARCHAR(100),            -- bank UTR / UPI ref / NACH ref
  gateway_ref      VARCHAR(100),            -- Razorpay/Digio internal ref
  payer_account    VARCHAR(30),             -- masked last 4 digits

  status           VARCHAR(20)  NOT NULL DEFAULT 'initiated',
    -- 'initiated' | 'success' | 'failed' | 'reversed' | 'refunded'
  failure_reason   VARCHAR(200),

  -- Allocation snapshot at time of posting
  allocated_principal  NUMERIC(14,2) DEFAULT 0,
  allocated_interest   NUMERIC(14,2) DEFAULT 0,
  allocated_penalty    NUMERIC(14,2) DEFAULT 0,
  allocated_bounce     NUMERIC(14,2) DEFAULT 0,
  excess_amount        NUMERIC(14,2) DEFAULT 0,

  initiated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  settled_at       TIMESTAMPTZ,

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payments_loan    ON payments(loan_id);
CREATE INDEX idx_payments_utr     ON payments(utr_ref) WHERE utr_ref IS NOT NULL;
CREATE INDEX idx_payments_status  ON payments(status);
```

---

### 2.5 `mandates`

```sql
mandates (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  customer_id      UUID         NOT NULL REFERENCES customers(id),
  tenant_id        UUID         NOT NULL,

  type             VARCHAR(20)  NOT NULL,   -- 'enach' | 'upi_autopay'
  umrn             VARCHAR(100),            -- NPCI Unique Mandate Reference Number
  vendor_mandate_id VARCHAR(100),           -- Digio / Razorpay internal ID
  bank_name        VARCHAR(100),
  account_masked   VARCHAR(20),             -- last 4 digits only
  ifsc             VARCHAR(15),
  account_type     VARCHAR(20),             -- 'savings' | 'current'
  max_amount       NUMERIC(14,2) NOT NULL,
  frequency        VARCHAR(20)  NOT NULL DEFAULT 'monthly',
    -- 'monthly' | 'bimonthly' | 'weekly' | 'as_presented'
  start_date       DATE,
  end_date         DATE,

  status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- 'pending' | 'registered' | 'active' | 'paused' | 'cancelled' | 'expired'
  cancellation_reason VARCHAR(200),

  registered_at    TIMESTAMPTZ,
  cancelled_at     TIMESTAMPTZ,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.6 `bounce_events`

Each failed auto-debit attempt creates one row.

```sql
bounce_events (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  schedule_id      UUID         NOT NULL REFERENCES repayment_schedules(id),
  mandate_id       UUID         REFERENCES mandates(id),
  tenant_id        UUID         NOT NULL,

  attempt_no       INTEGER      NOT NULL,   -- 1 | 2 | 3
  attempted_at     TIMESTAMPTZ  NOT NULL,
  amount_attempted NUMERIC(14,2) NOT NULL,

  bounce_reason    VARCHAR(200),
    -- 'insufficient_funds' | 'account_closed' | 'stop_payment'
    -- | 'account_frozen' | 'invalid_account' | 'bank_error' | 'technical_error'
  npci_ref         VARCHAR(100),
  gateway_ref      VARCHAR(100),

  bounce_charge    NUMERIC(14,2) NOT NULL DEFAULT 0,
  bounce_gst       NUMERIC(14,2) NOT NULL DEFAULT 0,
  charge_waived    BOOLEAN      NOT NULL DEFAULT FALSE,
  waiver_reason    VARCHAR(200),

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.7 `penalty_ledger`

Granular daily penalty accrual log. Supports waiver and audit trail.

```sql
penalty_ledger (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  schedule_id      UUID         NOT NULL REFERENCES repayment_schedules(id),
  tenant_id        UUID         NOT NULL,

  accrual_date     DATE         NOT NULL,
  dpd_on_date      INTEGER      NOT NULL,
  overdue_amount   NUMERIC(14,2) NOT NULL,  -- base on which penalty is calculated
  penalty_rate_pct NUMERIC(6,4) NOT NULL,   -- e.g. 0.0667 (= 2%/30 per day)
  penalty_amount   NUMERIC(14,2) NOT NULL,
  gst_amount       NUMERIC(14,2) NOT NULL,
  penalty_type     VARCHAR(20)  NOT NULL,
    -- 'late_payment' | 'penal_interest_dpd30' | 'legal_charge'

  waived           BOOLEAN      NOT NULL DEFAULT FALSE,
  waiver_amount    NUMERIC(14,2) DEFAULT 0,
  waiver_by        UUID,
  waiver_reason    VARCHAR(500),
  waiver_at        TIMESTAMPTZ,

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_penalty_date ON penalty_ledger(loan_id, schedule_id, accrual_date);
```

---

### 2.8 `foreclosure_requests`

```sql
foreclosure_requests (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  customer_id      UUID         NOT NULL REFERENCES customers(id),
  tenant_id        UUID         NOT NULL,

  request_date     DATE         NOT NULL,
  valid_until      DATE         NOT NULL,  -- quote valid for 3 business days

  outstanding_principal NUMERIC(14,2) NOT NULL,
  accrued_interest NUMERIC(14,2) NOT NULL,
  overdue_amount   NUMERIC(14,2) NOT NULL DEFAULT 0,
  foreclosure_charge NUMERIC(14,2) NOT NULL,
  gst_on_charge    NUMERIC(14,2) NOT NULL,
  total_payable    NUMERIC(14,2) NOT NULL,

  status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- 'pending' | 'paid' | 'expired' | 'cancelled'
  payment_id       UUID         REFERENCES payments(id),
  completed_at     TIMESTAMPTZ,

  created_by       UUID,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.9 `part_prepayment_requests`

```sql
part_prepayment_requests (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  tenant_id        UUID         NOT NULL,

  request_date     DATE         NOT NULL,
  prepay_amount    NUMERIC(14,2) NOT NULL,
  prepay_charge    NUMERIC(14,2) NOT NULL,
  gst_on_charge    NUMERIC(14,2) NOT NULL,
  total_payable    NUMERIC(14,2) NOT NULL,

  -- Post-prepayment recalculation
  new_outstanding  NUMERIC(14,2),
  recalc_option    VARCHAR(20),  -- 'reduce_tenure' | 'reduce_emi'
  new_emi          NUMERIC(14,2),
  new_tenure_months INTEGER,

  status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- 'pending' | 'paid' | 'schedule_revised' | 'cancelled'
  payment_id       UUID         REFERENCES payments(id),
  completed_at     TIMESTAMPTZ,

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.10 `loan_restructuring`

```sql
loan_restructuring (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  tenant_id        UUID         NOT NULL,

  restructure_date DATE         NOT NULL,
  reason           VARCHAR(500),  -- 'customer_hardship' | 'rbi_moratorium' | 'covid' etc.

  -- Original terms (snapshot)
  orig_outstanding NUMERIC(14,2) NOT NULL,
  orig_tenure      INTEGER,
  orig_roi         NUMERIC(6,4),
  orig_emi         NUMERIC(14,2),

  -- Revised terms
  new_principal    NUMERIC(14,2) NOT NULL,
  new_tenure       INTEGER      NOT NULL,
  new_roi          NUMERIC(6,4) NOT NULL,
  new_emi          NUMERIC(14,2) NOT NULL,
  new_maturity_date DATE        NOT NULL,
  moratorium_months INTEGER     DEFAULT 0,

  restructuring_charge NUMERIC(14,2) DEFAULT 0,
  gst_on_charge    NUMERIC(14,2) DEFAULT 0,

  status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- 'pending' | 'approved' | 'active' | 'rejected'
  approved_by      UUID,
  approved_at      TIMESTAMPTZ,

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.11 `ots_settlements` (One-Time Settlement)

```sql
ots_settlements (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  tenant_id        UUID         NOT NULL,

  offer_date       DATE         NOT NULL,
  offer_valid_until DATE        NOT NULL,

  total_outstanding NUMERIC(14,2) NOT NULL,   -- full amount owed
  settlement_amount NUMERIC(14,2) NOT NULL,   -- agreed OTS amount
  waiver_amount    NUMERIC(14,2) NOT NULL,    -- = total_outstanding - settlement_amount
  waiver_components JSONB,
    -- {"principal": 0, "interest": 5000, "penalty": 12000, "legal": 2000}

  -- RBI requirement: OTS requires MD/CEO approval for waivers > threshold
  approval_level   VARCHAR(20),   -- 'rm' | 'branch_head' | 'credit_committee' | 'md'
  approved_by      UUID,
  approved_at      TIMESTAMPTZ,

  payment_id       UUID         REFERENCES payments(id),
  status           VARCHAR(20)  NOT NULL DEFAULT 'offered',
    -- 'offered' | 'accepted' | 'paid' | 'expired' | 'rejected'
  completed_at     TIMESTAMPTZ,

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.12 `npa_provisioning`

Monthly snapshot for regulatory provisioning computation.

```sql
npa_provisioning (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  tenant_id        UUID         NOT NULL,
  report_month     DATE         NOT NULL,   -- first day of month

  classification   VARCHAR(20)  NOT NULL,
  dpd_at_eom       INTEGER      NOT NULL,
  outstanding_eom  NUMERIC(14,2) NOT NULL,
  collateral_value NUMERIC(14,2) DEFAULT 0,
  net_outstanding  NUMERIC(14,2) GENERATED ALWAYS AS
                   (outstanding_eom - collateral_value) STORED,
  provision_pct    NUMERIC(5,2) NOT NULL,
  provision_amount NUMERIC(14,2) GENERATED ALWAYS AS
                   ((outstanding_eom - collateral_value) * provision_pct / 100) STORED,

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  UNIQUE (loan_id, report_month)
);
```

---

### 2.13 `credit_bureau_reports`

```sql
credit_bureau_reports (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  customer_id      UUID         NOT NULL REFERENCES customers(id),
  tenant_id        UUID         NOT NULL,

  bureau           VARCHAR(20)  NOT NULL,   -- 'CIBIL' | 'EQUIFAX' | 'EXPERIAN'
  report_type      VARCHAR(20)  NOT NULL,
    -- 'monthly_regular' | 'npa_update' | 'closure' | 'correction_request'
  reporting_month  DATE         NOT NULL,   -- first day of reporting month
  dpd_reported     INTEGER,
  account_status   VARCHAR(30),
    -- 'STD' | 'SMA-0' | 'SMA-1' | 'SMA-2' | 'NPA' | 'CLOSED' | 'WRITTEN_OFF'
  outstanding_reported NUMERIC(14,2),

  submission_ref   VARCHAR(100),           -- bureau ACK reference
  submitted_at     TIMESTAMPTZ,
  status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- 'pending' | 'submitted' | 'acknowledged' | 'rejected' | 'corrected'
  rejection_reason TEXT,

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.14 `loan_waivers`

The `grievances` table lives in the **Grievance Service** database, not in LMS. LMS only stores the outcome of a waiver decision once approved by the Grievance Officer — this is the single write-back that LMS accepts from the Grievance Service.

```sql
loan_waivers (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id          UUID         NOT NULL REFERENCES loans(id),
  schedule_id      UUID         REFERENCES repayment_schedules(id),
  tenant_id        UUID         NOT NULL,

  -- Populated by Grievance Service after GRO approval
  grievance_ticket VARCHAR(30)  NOT NULL,  -- reference to Grievance Svc ticket
  waiver_type      VARCHAR(30)  NOT NULL,
    -- 'penalty' | 'bounce_charge' | 'penal_interest' | 'legal_charge' | 'interest'
  waiver_amount    NUMERIC(14,2) NOT NULL,
  gst_reversal     NUMERIC(14,2) NOT NULL DEFAULT 0,
  reason           TEXT         NOT NULL,

  approved_by      UUID         NOT NULL,  -- Grievance Officer user ID
  approved_at      TIMESTAMPTZ  NOT NULL,
  applied_at       TIMESTAMPTZ,            -- when LMS applied the waiver to the ledger

  status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- 'pending' | 'applied' | 'rejected'

  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.15 `regulatory_reports`

```sql
regulatory_reports (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID         NOT NULL,
  report_type      VARCHAR(50)  NOT NULL,
    -- 'rbi_monthly_return' | 'crilc_sma' | 'npa_provisioning'
    -- | 'fraud_reporting' | 'interest_rate_disclosure' | 'ombudsman_quarterly'
  reporting_period DATE         NOT NULL,
  report_data      JSONB        NOT NULL,
  file_s3_key      VARCHAR(500),
  submitted_at     TIMESTAMPTZ,
  submission_ref   VARCHAR(100),
  status           VARCHAR(20)  NOT NULL DEFAULT 'draft',
    -- 'draft' | 'ready' | 'submitted' | 'acknowledged' | 'revised'
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

---

### 2.16 Master Tables

> All master tables share the same governance pattern:
> - `effective_from` / `effective_till` for versioning — engines always query `WHERE effective_from <= NOW() AND (effective_till IS NULL OR effective_till > NOW())`
> - `is_active` boolean for soft-disable without losing history
> - `created_by` + `approved_by` — four-eyes principle (maker-checker)
> - `tenant_id` for multi-tenant isolation; a row with `tenant_id = NULL` is a system default
> - Engine always selects: tenant-specific row first, fallback to system default

---

#### 2.16.1 `charge_master`

Stores all fee/charge definitions. The penalty engine, bounce engine, and foreclosure engine read from this table — nothing is hardcoded.

```sql
charge_master (
  id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID          REFERENCES tenants(id),  -- NULL = system default
  charge_code      VARCHAR(50)   NOT NULL,
    -- 'LATE_PAYMENT_PENALTY' | 'BOUNCE_CHARGE' | 'LEGAL_NOTICE_CHARGE'
    -- | 'FORECLOSURE_CHARGE' | 'PART_PREPAYMENT_CHARGE' | 'PROCESSING_FEE'
    -- | 'DOCUMENTATION_CHARGE' | 'CHEQUE_SWAP_CHARGE'
  charge_name      VARCHAR(100)  NOT NULL,
  calc_type        VARCHAR(20)   NOT NULL,
    -- 'flat'            → fixed_amount applies
    -- 'pct_outstanding' → pct_rate * outstanding_principal
    -- 'pct_emi'         → pct_rate * emi_amount
  fixed_amount     NUMERIC(10,2),
  pct_rate         NUMERIC(6,4),   -- e.g. 2.00 = 2 % per month
  min_amount       NUMERIC(10,2),  -- floor (₹ 0 if no floor)
  max_amount       NUMERIC(10,2),  -- cap (NULL = uncapped)
  gst_applicable   BOOLEAN       NOT NULL DEFAULT TRUE,
  gst_rate         NUMERIC(5,2)  NOT NULL DEFAULT 18.00,  -- GST % (18% standard)
  penal_capitalise BOOLEAN       NOT NULL DEFAULT FALSE,  -- MUST be FALSE — RBI Jan 2024
  effective_from   DATE          NOT NULL,
  effective_till   DATE,           -- NULL = open-ended (current)
  is_active        BOOLEAN       NOT NULL DEFAULT TRUE,
  created_by       UUID          NOT NULL REFERENCES users(id),
  approved_by      UUID          REFERENCES users(id),
  created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

  CONSTRAINT chk_penal_no_cap CHECK (penal_capitalise = FALSE),  -- RBI hard constraint
  CONSTRAINT chk_calc_type CHECK (
    (calc_type = 'flat' AND fixed_amount IS NOT NULL) OR
    (calc_type IN ('pct_outstanding','pct_emi') AND pct_rate IS NOT NULL)
  )
);

CREATE UNIQUE INDEX ux_charge_master_active
  ON charge_master (tenant_id, charge_code, effective_from)
  WHERE is_active = TRUE;
```

---

#### 2.16.2 `product_master`

Contains only fields the LMS engines read at runtime. Eligibility fields (`min/max_loan_amount`, `min/max_tenure`) belong in LOS and are not repeated here.

```sql
product_master (
  id                        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                 UUID         REFERENCES tenants(id),
  product_code              VARCHAR(50)  NOT NULL,   -- 'PAYDAY_30D' | 'EMI_6M' | 'EMI_12M' | 'EMI_24M'
  product_name              VARCHAR(100) NOT NULL,   -- used in NOC, statements, RBI reports

  -- Accrual engine
  interest_type             VARCHAR(20)  NOT NULL,
    -- 'reducing_balance' | 'flat' | 'daily_flat'

  -- Foreclosure engine
  foreclosure_allowed       BOOLEAN     NOT NULL DEFAULT TRUE,
  foreclosure_lock_months   INTEGER     NOT NULL DEFAULT 0,  -- must complete N EMIs first

  -- Penalty engine
  grace_period_days         INTEGER     NOT NULL DEFAULT 0,  -- days after due before penalty starts

  -- EMI auto-debit orchestrator
  enach_presentation_lead_days INTEGER  NOT NULL DEFAULT 3,  -- present mandate N days before due date

  -- Part-prepayment engine
  part_prepayment_allowed   BOOLEAN     NOT NULL DEFAULT TRUE,
  part_prepayment_min_pct   NUMERIC(5,2),  -- minimum as % of outstanding principal
  part_prepayment_lock_months INTEGER   NOT NULL DEFAULT 0,  -- block prepayment in first N months

  -- Restructuring / OTS modules
  restructuring_allowed     BOOLEAN     NOT NULL DEFAULT FALSE,
  ots_allowed               BOOLEAN     NOT NULL DEFAULT FALSE,

  -- NOC engine (RBI mandates closure NOC within 7 days; default target = 3)
  noc_auto_issue_days       INTEGER     NOT NULL DEFAULT 3,

  -- Bureau reporting engine
  bureau_report_on_closure  BOOLEAN     NOT NULL DEFAULT TRUE,

  -- Governance
  effective_from            DATE        NOT NULL,
  effective_till            DATE,
  is_active                 BOOLEAN     NOT NULL DEFAULT TRUE,
  created_by                UUID        NOT NULL REFERENCES users(id),
  approved_by               UUID        REFERENCES users(id),
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
  -- min/max_loan_amount, min/max_tenure: LOS concern — not stored here
);

CREATE UNIQUE INDEX ux_product_master_active
  ON product_master (tenant_id, product_code, effective_from)
  WHERE is_active = TRUE;
```

---

> **`interest_rate_master` is owned by LOS, not LMS.**
> The AI/Risk engine reads it during underwriting to compute the final ROI. That rate is stamped on `loans.roi_monthly` in the `loan.disbursed` event payload. LMS reads `loans.roi_monthly` directly — it never queries `interest_rate_master`. Document and schema belong in the LOS LLD.

---

#### 2.16.3 `collection_rule_master`

Drives the collection escalation engine. Maps DPD ranges to actions. The DPD engine reads this table daily to decide which collection action to trigger.

```sql
collection_rule_master (
  id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID         REFERENCES tenants(id),
  product_id        UUID         REFERENCES product_master(id), -- NULL = all products
  dpd_from          INTEGER      NOT NULL,  -- inclusive
  dpd_to            INTEGER      NOT NULL,  -- inclusive; 999 = open-ended NPA+
  sma_bucket        VARCHAR(10)  NOT NULL,
    -- 'CURRENT' | 'SMA-0' | 'SMA-1' | 'SMA-2' | 'NPA'
  action_type       VARCHAR(50)  NOT NULL,
    -- 'SMS_REMINDER' | 'WHATSAPP_REMINDER' | 'CALL_QUEUE_L1'
    -- | 'CALL_QUEUE_L2' | 'LEGAL_NOTICE' | 'FIELD_VISIT' | 'SARFAESI_NOTICE'
  escalate_to_field BOOLEAN      NOT NULL DEFAULT FALSE,
  legal_action_flag BOOLEAN      NOT NULL DEFAULT FALSE,
  enach_retry_count   INTEGER    NOT NULL DEFAULT 1,
  enach_retry_gap_days INTEGER   NOT NULL DEFAULT 3,  -- days to wait before re-presenting after bounce
  notify_agent      BOOLEAN      NOT NULL DEFAULT FALSE,
  notify_guarantor  BOOLEAN      NOT NULL DEFAULT FALSE,
  effective_from    DATE         NOT NULL,
  effective_till    DATE,
  is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
  created_by        UUID         NOT NULL REFERENCES users(id),
  approved_by       UUID         REFERENCES users(id),
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

  CONSTRAINT chk_dpd_range CHECK (dpd_from <= dpd_to),
  CONSTRAINT chk_dpd_from_non_neg CHECK (dpd_from >= 0)
);

CREATE INDEX idx_collection_rule_dpd
  ON collection_rule_master (tenant_id, dpd_from, dpd_to)
  WHERE is_active = TRUE;
```

> **GST note:** GST rate (currently 18%) is stored on `charge_master.gst_rate` per charge type. A separate `tax_master` table is not required — GST on loan charges has been a single uniform rate since July 2017, and any future rate change is handled by inserting a new `charge_master` row with an updated `effective_from` date.

---

### 2.17 `tenant_configs`

Tenant-wide operational settings that are not product-specific. Engines read from Redis cache (5-minute TTL); on cache miss they fall back to this table. A row with `tenant_id = NULL` holds system defaults that apply to all tenants unless overridden.

```sql
tenant_configs (
  id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID         REFERENCES tenants(id),  -- NULL = system default
  config_key  VARCHAR(100) NOT NULL,
  config_value TEXT        NOT NULL,   -- always stored as string; engine casts to correct type
  description TEXT,                    -- human-readable explanation for ops team
  updated_by  UUID         NOT NULL REFERENCES users(id),
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

  CONSTRAINT uq_tenant_config UNIQUE (tenant_id, config_key)
);
```

**Seed rows (system defaults):**

| `config_key` | Default value | Used by |
|---|---|---|
| `reconciliation_tolerance_inr` | `1.00` | Payment reconciliation — accept match if difference ≤ ₹1 (rounding) |
| `statement_auto_generate_day` | `5` | Monthly statement cron — generate on this day of month (5th) |
| `notification_timing_pre_due_days` | `3,1` | Reminder cron — send reminders 3 days and 1 day before due date |
| `notification_timing_post_due_days` | `1,3,7` | Overdue reminder cron — send on D+1, D+3, D+7 after missed due date |
| `npa_classification_dpd` | `90` | NPA engine — DPD threshold (RBI floor; cannot be lowered below 90) |
| `crilc_report_submission_day` | `15` | Regulatory reporting cron — submit CRILC by 15th of following month |

> **Redis cache pattern:**
> ```
> Key:   lms:config:{tenant_id}:{config_key}
> TTL:   300 seconds (5 minutes)
> Miss:  SELECT config_value FROM tenant_configs
>          WHERE (tenant_id = $1 OR tenant_id IS NULL)
>          ORDER BY tenant_id NULLS LAST   -- tenant row wins over system default
>          LIMIT 1
> ```

---

## 3. LMS API Endpoints

### 3.1 Loan Account (`/api/v1/lms/loans`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| GET | `/:id` | customer, agent, admin | Full loan details + current status |
| GET | `/:id/schedule` | customer, agent, admin | Full amortisation schedule |
| GET | `/:id/ledger` | customer, admin | Complete transaction ledger |
| GET | `/:id/statement` | customer, agent, admin | PDF loan account statement |
| GET | `/:id/outstanding` | customer, agent, admin | Current outstanding breakup |
| GET | `/:id/dpd` | agent, admin | Current DPD + SMA classification |

### 3.2 Repayment (`/api/v1/lms/repayments`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| POST | `/pay` | customer, admin | Manual payment initiation (UPI/NEFT) |
| GET | `/:loan_id/next-due` | customer, agent | Next due date + amount |
| GET | `/:loan_id/overdue` | customer, admin | All overdue installments + charges |
| POST | `/webhook/enach` | system | Digio eNACH debit success/failure |
| POST | `/webhook/upi` | system | Razorpay UPI Autopay success/failure |
| POST | `/webhook/payment-link` | system | Razorpay payment link completion |

### 3.3 Mandate Management (`/api/v1/lms/mandates`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| GET | `/:loan_id` | customer, admin | Active mandate details |
| POST | `/:loan_id/cancel` | admin | Cancel mandate (e.g., on foreclosure) |
| POST | `/:loan_id/pause` | admin | Pause mandate (restructuring) |
| POST | `/:loan_id/resume` | admin | Resume paused mandate |

### 3.4 Foreclosure (`/api/v1/lms/foreclosure`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| GET | `/:loan_id/quote` | customer, agent, admin | Generate foreclosure quote (valid 3 days) |
| POST | `/:loan_id/initiate` | customer, admin | Initiate foreclosure payment |
| GET | `/:loan_id/status` | customer, admin | Foreclosure request status |

### 3.5 Part-Prepayment (`/api/v1/lms/prepayment`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| GET | `/:loan_id/eligibility` | customer, admin | Check if prepayment is allowed |
| POST | `/:loan_id/quote` | customer, admin | Calculate prepayment charges + new schedule |
| POST | `/:loan_id/initiate` | customer, admin | Initiate part-prepayment |

### 3.6 Restructuring (`/api/v1/lms/restructure`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| POST | `/:loan_id/apply` | admin | Raise restructuring request |
| GET | `/:loan_id/status` | admin | Restructuring status |
| POST | `/:loan_id/approve` | credit_manager | Approve and activate restructured schedule |

### 3.7 OTS Settlement (`/api/v1/lms/ots`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| POST | `/:loan_id/offer` | credit_manager | Create OTS offer |
| GET | `/:loan_id/offer` | customer, admin | Fetch current OTS offer |
| POST | `/:loan_id/accept` | customer | Customer accepts OTS |
| POST | `/:loan_id/pay` | customer, admin | Process OTS payment |

### 3.8 NOC & Documents (`/api/v1/lms/documents`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| GET | `/:loan_id/noc` | customer, admin | Download NOC (only after closure) |
| POST | `/:loan_id/noc/generate` | system | Trigger NOC generation post-closure |
| GET | `/:loan_id/kfs` | customer | Download original KFS |
| GET | `/:loan_id/agreement` | customer, admin | Download signed loan agreement |
| POST | `/:loan_id/statement/email` | customer | Email account statement |

### 3.9 Grievance Service Interface (`/api/v1/lms/grievance-interface`)

Grievances are owned and tracked by a separate **Grievance Service**. LMS exposes a narrow read + command interface that the Grievance Service calls — LMS does not store ticket state.

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| GET | `/:loan_id/dispute-summary` | grievance_service | Outstanding breakup + ledger snapshot for dispute resolution |
| GET | `/:loan_id/ledger` | grievance_service | Full transaction ledger for a charge dispute |
| GET | `/:loan_id/bureau-status` | grievance_service | Current bureau reporting status (for correction requests) |
| POST | `/:loan_id/waiver` | grievance_service | Apply a GRO-approved waiver; creates `loan_waivers` record and posts to ledger |

### 3.10 Admin / Reporting (`/api/v1/lms/admin`)

| Method | Endpoint | Auth Role | Description |
|---|---|---|---|
| GET | `/dashboard` | admin | Live DPD buckets, NPA count, collection rate |
| GET | `/dpd-report` | admin | Full DPD bucket report for any date |
| GET | `/npa-list` | admin | All NPA accounts with outstanding |
| GET | `/bureau-queue` | admin | Bureau reporting queue status |
| POST | `/bureau-submit` | admin | Trigger monthly bureau submission |
| GET | `/regulatory/rbi-return` | admin | Generate RBI monthly return |
| POST | `/waiver/apply` | credit_manager | Raise penalty/charge waiver |

---

## 4. Core Engine Designs

### 4.1 Repayment Schedule Generator

Called by LMS on receipt of `loan_disbursed` event from LOS.

```
function generateRepaymentSchedule(loan):

  IF loan.interest_type == 'daily_flat':          // Payday loan
    schedule = [{
      installment_no: 1,
      due_date:       loan.disbursal_date + loan.tenure_days,
      principal_amt:  loan.principal,
      interest_amt:   loan.principal × loan.roi_daily × loan.tenure_days,
      emi_amount:     principal_amt + interest_amt
    }]

  ELSE IF loan.interest_type == 'reducing_balance':  // Standard EMI
    r   = loan.roi_monthly / 100
    n   = loan.tenure_months
    EMI = ROUND(loan.principal × r × (1+r)^n / ((1+r)^n - 1), 2)

    // Broken period interest if disbursal not on 1st of month
    broken_days    = days_until_first_emi_date(loan.disbursal_date)
    broken_int     = loan.principal × (r/30) × broken_days
    first_emi_date = next_emi_date(loan.disbursal_date)

    outstanding = loan.principal
    FOR installment_no IN 1..n:
      interest    = ROUND(outstanding × r, 2)
      principal   = ROUND(EMI - interest, 2)
      if installment_no == n:
        principal = outstanding            // last EMI absorbs rounding delta
      emi_total   = principal + interest
      IF installment_no == 1:
        emi_total += broken_int            // broken period added to first EMI
      INSERT repayment_schedules(...)
      outstanding -= principal

  ELSE IF loan.interest_type == 'flat':
    total_interest = loan.principal × loan.roi_monthly × loan.tenure_months / 100
    EMI = ROUND((loan.principal + total_interest) / loan.tenure_months, 2)
    // generate schedule rows similar to above

  publish EVENT: 'schedule_generated', loan_id
  schedule_reminders(schedule)
```

---

### 4.2 Daily Interest Accrual Engine (Cron)

```
// Runs daily at 00:05 IST
function dailyInterestAccrual():
  active_loans = SELECT * FROM loans WHERE status = 'active'

  FOR EACH loan IN active_loans:
    daily_rate    = loan.roi_monthly / 100 / 30
    daily_int     = ROUND(loan.outstanding_principal × daily_rate, 2)
    loan.accrued_interest += daily_int

    INSERT loan_ledger(
      entry_type:     'interest_due',
      debit:          daily_int,
      effective_date: TODAY,
      narration:      'Daily interest accrual'
    )

    UPDATE loans SET accrued_interest = loan.accrued_interest
```

---

### 4.3 EMI Auto-Debit Orchestrator (Cron)

```
// Runs daily at 08:00 IST; pre-debit notification at 09:00 IST T-1 day
function eNachOrchestrator():
  due_today = SELECT rs.* FROM repayment_schedules rs
              JOIN loans l ON rs.loan_id = l.id
              WHERE rs.due_date = TODAY
              AND   rs.status IN ('pending', 'partial')
              AND   l.status = 'active'

  FOR EACH installment IN due_today:
    mandate = getActiveMandate(installment.loan_id)
    IF NOT mandate OR mandate.status != 'active':
      flag_for_manual_collection(installment)
      CONTINUE

    IF mandate.type == 'enach':
      digio_api.register_presentation(
        mandate_id:  mandate.vendor_mandate_id,
        amount:      installment.balance_due,
        debit_date:  TODAY
      )
    ELSE IF mandate.type == 'upi_autopay':
      razorpay_api.execute_recurring(
        subscription_id: mandate.vendor_mandate_id,
        amount:          installment.balance_due
      )

    UPDATE payments(status='initiated', amount=installment.balance_due)
    AuditLog('emi_debit_initiated', installment.id)

// Pre-debit notification (T-1)
function priorDayNotification():
  tomorrow_dues = SELECT rs.*, l.* FROM repayment_schedules rs ...
                  WHERE rs.due_date = TODAY + 1
  FOR EACH installment:
    notify(customer, 'emi_due_tomorrow',
      { amount: installment.total_due, due_date: installment.due_date })
    // RBI DLG 2022: pre-debit notification mandatory 24 hrs before auto-debit
```

---

### 4.4 Payment Posting & Allocation Engine

Priority order for payment allocation (RBI Fair Practice Code mandates):
1. Penal charges + GST (oldest first)
2. Bounce charges + GST
3. Interest (oldest overdue first)
4. Principal (oldest overdue first)
5. Current EMI interest
6. Current EMI principal
7. Future installments (if excess)

```
function postPayment(loan_id, amount, channel, utr_ref):

  // Idempotency check — reject duplicate UTR
  IF EXISTS payments WHERE utr_ref = utr_ref AND status = 'success':
    RAISE DuplicatePaymentError

  // Lock loan row for update (prevent race conditions)
  LOCK loans WHERE id = loan_id FOR UPDATE

  outstanding_installments = SELECT * FROM repayment_schedules
    WHERE loan_id = loan_id
    AND   status IN ('overdue', 'partial', 'pending')
    ORDER BY due_date ASC

  remaining = amount
  allocation = { principal: 0, interest: 0, penalty: 0, bounce: 0, excess: 0 }

  FOR EACH installment IN outstanding_installments:
    IF remaining <= 0: BREAK

    // Step 1: Settle penalty
    penalty_due = installment.penalty_amt + installment.penalty_gst - waived
    IF penalty_due > 0:
      settled = MIN(remaining, penalty_due)
      allocation.penalty += settled
      remaining -= settled

    // Step 2: Settle bounce charges
    bounce_due = installment.bounce_charge + installment.bounce_gst
    IF bounce_due > 0:
      settled = MIN(remaining, bounce_due)
      allocation.bounce += settled
      remaining -= settled

    // Step 3: Settle interest
    IF remaining > 0:
      settled = MIN(remaining, installment.interest_amt)
      allocation.interest += settled
      remaining -= settled

    // Step 4: Settle principal
    IF remaining > 0:
      settled = MIN(remaining, installment.principal_amt)
      allocation.principal += settled
      remaining -= settled

    // Mark installment status
    IF installment.balance_due <= 0:
      UPDATE repayment_schedules SET status = 'paid', paid_at = NOW()
    ELSE:
      UPDATE repayment_schedules SET status = 'partial'

  // Remaining is excess — hold as credit on loan account
  allocation.excess = remaining

  // Update loan outstanding
  UPDATE loans SET
    outstanding_principal -= allocation.principal,
    accrued_interest      -= allocation.interest,
    total_penalty         -= allocation.penalty,
    total_bounce_charges  -= allocation.bounce,
    total_paid            += amount

  // Ledger entries
  INSERT loan_ledger(entry_type='payment_received', credit=amount, ...)

  // Check if loan is fully paid
  IF loan.outstanding_principal <= 0.01:
    closeLoan(loan_id, 'normal')

  // Update DPD
  recalculateDPD(loan_id)

  PUBLISH EVENT: 'payment_received', { loan_id, amount, allocation }
```

---

### 4.5 DPD Engine & SMA Classifier (Cron)

```
// Runs daily at 00:30 IST
function updateDPD():
  active_loans = SELECT * FROM loans WHERE status = 'active'

  FOR EACH loan IN active_loans:
    oldest_overdue = SELECT MIN(due_date) FROM repayment_schedules
                     WHERE loan_id = loan.id
                     AND   status IN ('overdue', 'partial')

    IF oldest_overdue IS NULL:
      dpd = 0
      loan.first_default_date = NULL
    ELSE:
      IF loan.first_default_date IS NULL:
        loan.first_default_date = oldest_overdue  // first miss ever
      dpd = TODAY - oldest_overdue

    // Update overdue installments status
    UPDATE repayment_schedules SET status = 'overdue'
    WHERE loan_id = loan.id
    AND   due_date < TODAY
    AND   status = 'pending'

    // SMA classification (RBI NPA norms)
    IF   dpd == 0:    sma = NULL
    ELIF dpd <= 30:   sma = 'SMA-0'
    ELIF dpd <= 60:   sma = 'SMA-1'
    ELIF dpd <= 90:   sma = 'SMA-2'
    ELIF dpd > 90:
      IF loan.status != 'npa':
        markNPA(loan.id, dpd)
      sma = NULL  // NPA overrides SMA

    UPDATE loans SET dpd = dpd, sma_category = sma
    AuditLog('dpd_updated', loan.id, { dpd, sma })
```

---

### 4.6 Penalty Accrual Engine (Cron)

```
// Runs daily at 01:00 IST
// RBI Penal Charges Circular (Aug 2023, effective 01-Jan-2024):
//   - Penal charges must be reasonable and disclosed in KFS
//   - Cannot be capitalised (compounded on principal)
//   - Separate line item from interest; not part of outstanding principal

function accrueDaily Penalty():
  overdue_installments = SELECT rs.*, l.roi_monthly
    FROM repayment_schedules rs
    JOIN loans l ON rs.loan_id = l.id
    WHERE rs.status IN ('overdue', 'partial')
    AND   l.status = 'active'
    AND   rs.due_date < TODAY

  FOR EACH inst IN overdue_installments:
    dpd        = TODAY - inst.due_date
    overdue_amt = inst.balance_due  // current balance (principal + interest)

    // Stage 1: DPD 1–29 — Late payment penalty (2%/month = 0.0667%/day)
    IF dpd <= 29:
      daily_rate = 0.02 / 30
      penalty    = ROUND(overdue_amt × daily_rate, 2)
      gst        = ROUND(penalty × 0.18, 2)
      penalty_type = 'late_payment'

    // Stage 2: DPD 30+ — Penal interest (3%/month)
    ELIF dpd >= 30:
      daily_rate = 0.03 / 30
      penalty    = ROUND(overdue_amt × daily_rate, 2)
      gst        = ROUND(penalty × 0.18, 2)
      penalty_type = 'penal_interest_dpd30'

    // DPD 60+ — Legal charges (once-off when crossing threshold)
    IF dpd == 60:
      addLegalNoticeCharge(inst.loan_id, amount=500, gst=90)

    // Check for existing entry today (idempotency)
    IF NOT EXISTS penalty_ledger WHERE loan_id=inst.loan_id
                                 AND   schedule_id=inst.id
                                 AND   accrual_date=TODAY:
      INSERT penalty_ledger(...)
      UPDATE repayment_schedules SET
        penalty_amt  += penalty,
        penalty_gst  += gst
      UPDATE loans SET total_penalty += (penalty + gst)
```

---

### 4.7 NPA Classification Engine

```
// Triggered by DPD engine when dpd > 90
function markNPA(loan_id, dpd):
  loan = getLoan(loan_id)
  IF loan.status IN ('npa', 'written_off', 'closed'): RETURN

  npa_since = loan.first_default_date + 90 days

  UPDATE loans SET
    status       = 'npa',
    npa_since    = npa_since,
    npa_classification = 'sub_standard',
    provision_pct = 10.0,
    provision_amount = outstanding_principal × 0.10

  INSERT loan_ledger(entry_type='npa_classification', narration='Account classified NPA')

  // Cancel mandate
  cancelMandate(loan.mandate_id, reason='NPA classification')

  // Freeze further penalty accrual (penalty continues on NPA per RBI)
  // Report to credit bureau
  queueBureauReport(loan_id, account_status='NPA')

  // Notify collection team
  notifyCollectionTeam(loan_id, 'NPA')

  AuditLog('npa_classified', loan_id, { dpd, npa_since, outstanding: loan.outstanding_principal })

// Monthly provisioning update
function updateProvisioning(loan_id):
  loan     = getLoan(loan_id)
  days_npa = TODAY - loan.npa_since
  years_npa = days_npa / 365

  IF   days_npa <= 365:   pct = 10.0;  cls = 'sub_standard'
  ELIF days_npa <= 730:   pct = 25.0;  cls = 'doubtful_1'
  ELIF days_npa <= 1095:  pct = 40.0;  cls = 'doubtful_2'
  ELSE:                   pct = 100.0; cls = 'doubtful_3'

  UPDATE loans SET npa_classification = cls, provision_pct = pct,
         provision_amount = outstanding_principal × pct / 100

  INSERT npa_provisioning(
    report_month: FIRST_DAY_OF_CURRENT_MONTH,
    classification: cls, provision_pct: pct, ...
  )
```

---

### 4.8 Foreclosure Engine

```
function generateForeclosureQuote(loan_id):
  loan     = getLoan(loan_id)
  IF loan.status != 'active': RAISE LoanNotActiveError

  outstanding_p = loan.outstanding_principal
  accrued_int   = loan.accrued_interest
  overdue       = loan.total_overdue

  // Foreclosure rates by risk band (Alpha LMS policy)
  fc_rates = { 'A': 0.02, 'B': 0.03, 'C': 0.04 }
  customer_band = loan.application.risk_band
  fc_rate = fc_rates[customer_band]

  // Extra 1% surcharge within first 3 months
  months_active = MONTHS_BETWEEN(TODAY, loan.disbursal_date)
  IF months_active < 3: fc_rate += 0.01

  fc_charge    = ROUND(outstanding_p × fc_rate, 2)
  gst_on_fc    = ROUND(fc_charge × 0.18, 2)
  total_payable = outstanding_p + accrued_int + overdue + fc_charge + gst_on_fc

  INSERT foreclosure_requests(
    valid_until: TODAY + 3 business_days,  // quote valid 3 business days
    total_payable: total_payable, ...
  )
  RETURN quote

function processForeclosure(foreclosure_request_id, payment_id):
  request = getForeclosureRequest(foreclosure_request_id)
  IF request.valid_until < TODAY: RAISE QuoteExpiredError

  payment = verifyPayment(payment_id, expected_amount=request.total_payable)

  // Close loan
  UPDATE loans SET status='foreclosed', closed_at=NOW(), closure_type='foreclosure'
  cancelMandate(loan.mandate_id)
  UPDATE remaining repayment_schedules SET status='waived'

  // Ledger entries
  INSERT loan_ledger(entry_type='foreclosure_charge', debit=request.fc_charge)
  INSERT loan_ledger(entry_type='payment_received',   credit=request.total_payable)

  // Schedule NOC generation (72-hour SLA)
  queue NOC_GENERATION_JOB(loan_id, sla=72h)
  notifyCustomer(loan_id, 'foreclosure_complete')
  queueBureauReport(loan_id, account_status='CLOSED')
```

---

### 4.9 NOC Generation Engine

```
// Triggered on loan closure (normal / foreclosure / OTS)
function generateNOC(loan_id):
  loan = getLoan(loan_id)
  IF loan.outstanding_principal > 0.01: RAISE LoanNotFullyPaidError

  // Pull all data for NOC
  noc_data = {
    customer_name:     loan.customer.full_name,
    pan:               decrypt(loan.customer.pan_number),
    loan_account_no:   loan.id,
    sanctioned_amount: loan.sanctioned_amount,
    disbursal_date:    loan.disbursal_date,
    closure_date:      loan.closed_at.date(),
    closure_type:      loan.closure_type,
    total_paid:        loan.total_paid,
    noc_date:          TODAY,
    nbfc_name:         loan.tenant.name,
    // Authorized signatory from tenant config
    signatory_name:    loan.tenant.config.noc_signatory,
    signatory_designation: loan.tenant.config.noc_designation
  }

  // Generate PDF via Puppeteer service
  pdf_bytes = pdfService.render('noc_template', noc_data)

  // SHA-256 hash for tamper-proofing (RBI requirement)
  hash = SHA256(pdf_bytes)

  // Store in S3 with server-side encryption
  s3_key = "loans/{loan_id}/noc/{TODAY_ISO}.pdf"
  s3.put(s3_key, pdf_bytes, ServerSideEncryption='AES256')

  UPDATE loans SET noc_generated_at=NOW(), noc_s3_key=s3_key
  INSERT loan_ledger(entry_type='noc_issued', narration='NOC generated and stored')

  // Deliver to customer
  email(customer, 'noc_issued', attachment=pdf_bytes)
  whatsapp(customer, 'noc_issued', pdf_link=signed_s3_url(s3_key, expires=7days))
  sms(customer, 'noc_sms')  // Tata DLT template

  AuditLog('noc_generated', loan_id, { s3_key, hash })
```

---

### 4.10 Credit Bureau Reporting Engine

Monthly batch process. Complies with CIBIL, Equifax, Experian member reporting format.

```
// Runs on 5th of every month at 02:00 IST
function monthlyBureauReporting():
  report_month = FIRST_DAY_OF_PREVIOUS_MONTH
  active_loans  = SELECT * FROM loans WHERE status NOT IN ('written_off')
                  AND tenant.bureau_member = TRUE

  FOR EACH bureau IN ['CIBIL', 'EQUIFAX', 'EXPERIAN']:
    records = []

    FOR EACH loan IN active_loans:
      dpd = loan.dpd
      IF   dpd == 0:             account_status = 'STD'
      ELIF dpd <= 30:            account_status = 'SMA-0'
      ELIF dpd <= 60:            account_status = 'SMA-1'
      ELIF dpd <= 90:            account_status = 'SMA-2'
      ELIF loan.status == 'npa': account_status = 'NPA'
      ELIF loan.status == 'closed':    account_status = 'CLOSED'
      ELIF loan.status == 'written_off': account_status = 'WRITTEN_OFF'

      records.append({
        member_id:        TENANT_BUREAU_MEMBER_ID,
        account_number:   loan.id,
        pan:              customer.pan_decrypted,
        dob:              customer.dob,
        current_balance:  loan.outstanding_principal + loan.accrued_interest,
        amount_overdue:   loan.total_overdue,
        dpd:              dpd,
        account_status:   account_status,
        date_of_last_payment: latest_payment.settled_at.date()
      })

    // Submit to bureau via their API
    IF bureau == 'CIBIL': cibil_api.submitMonthlyFile(records)
    ELIF bureau == 'EQUIFAX': equifax_api.submitFile(records)
    ELIF bureau == 'EXPERIAN': experian_api.submitFile(records)

    // Store submission record
    INSERT credit_bureau_reports(bureau, reporting_month, status='submitted')
```

---

### 4.11 RBI Regulatory Reporting Engine

```
// Monthly Return (NBFC-ND-SI Form DNBS-02)
function generateRBIMonthlyReturn(report_month):
  summary = {
    total_loans_outstanding:   COUNT(loans WHERE status='active'),
    total_principal_outstanding: SUM(outstanding_principal WHERE status='active'),
    npa_accounts:              COUNT(loans WHERE status='npa'),
    npa_amount:                SUM(outstanding_principal WHERE status='npa'),
    sma0_accounts:             COUNT(loans WHERE sma_category='SMA-0'),
    sma1_accounts:             COUNT(loans WHERE sma_category='SMA-1'),
    sma2_accounts:             COUNT(loans WHERE sma_category='SMA-2'),
    provisions_held:           SUM(provision_amount),
    write_offs_this_month:     SUM(principal WHERE closure_type='written_off'
                                   AND closed_at BETWEEN month_start AND month_end),
    recoveries_from_written_off: ...,
    average_interest_rate:     AVG(roi_monthly),
    interest_income_accrued:   SUM(interest from loan_ledger this month),
    fee_income:                SUM(processing_fees this month),
    penalty_income:            SUM(penalty_amt collected this month)
  }

  pdf = pdfService.render('rbi_monthly_return_template', summary)
  INSERT regulatory_reports(report_type='rbi_monthly_return', ...)
  RETURN summary

// CRILC SMA Reporting (for exposures > ₹5 crore — optional for micro-lending)
function generateCRILCReport():
  large_exposures = SELECT * FROM loans
    WHERE outstanding_principal > 50000000  // ₹5 crore
    AND   sma_category IS NOT NULL
  // Submit to CRILC portal (RBI web service)
```

---

## 5. Background Jobs (Cron Schedule)

| Job | Schedule (IST) | Description | SLA |
|---|---|---|---|
| `daily_interest_accrual` | Daily 00:05 | Accrue daily interest on all active loans | < 5 min |
| `dpd_engine` | Daily 00:30 | Update DPD + SMA + flag overdue installments | < 10 min |
| `penalty_accrual` | Daily 01:00 | Apply daily late penalty / penal interest | < 10 min |
| `npa_classifier` | Daily 01:30 | Check DPD 90+ and mark NPA | < 5 min |
| `provisioning_update` | 1st of month 02:00 | Recalculate NPA provisioning | < 15 min |
| `pre_debit_notification` | Daily 09:00 | T-1 pre-debit SMS + WhatsApp (NPCI rule) | < 5 min |
| `enach_orchestrator` | Daily 08:00 | Submit due-date debits to Digio/Razorpay | < 10 min |
| `enach_retry_d2` | Daily 08:00 | Retry D+2 bounce cases | < 5 min |
| `enach_retry_d3` | Daily 08:00 | Retry D+3 bounce cases (final attempt) | < 5 min |
| `overdue_reminders` | Daily 10:00 | SMS + WhatsApp for DPD 1–7 | < 10 min |
| `collection_escalation` | Daily 10:30 | Assign tele-calling queue DPD 8–30 | < 5 min |
| `legal_queue` | Daily 11:00 | Flag DPD 60+ for legal notice | < 5 min |
| `bureau_reporting` | 5th of month 02:00 | Monthly bureau submission (CIBIL + Equifax + Experian) | < 30 min |
| `rbi_monthly_return` | 7th of month 09:00 | Generate and email RBI monthly return | < 15 min |
| `noc_generation_queue` | Every 30 min | Process NOC generation queue | < 5 min |
| `waiver_application` | On-demand | Apply approved waivers from Grievance Service to loan ledger | < 1 min |
| `cross_sell_engine` | Daily 10:00 | Flag closed loans for cross-sell eligibility | < 10 min |

---

## 6. Event System (Kafka / SQS Topics)

| Topic | Producer | Consumers | Description |
|---|---|---|---|
| `loan.disbursed` | LOS Service | LMS (schedule gen), Notification, Audit | Disbursal complete, LMS takes ownership |
| `payment.received` | LMS, Webhook Handler | LMS, Notification, DSA Engine | Successful EMI / manual payment |
| `payment.failed` | Webhook Handler | LMS, Notification, Collection | Bounce or failed debit |
| `mandate.registered` | Webhook Handler | LMS, Notification | Mandate activated |
| `mandate.cancelled` | LMS | Notification, Collection | Mandate cancelled |
| `dpd.updated` | DPD Engine | Notification, Collection, Reporting | DPD changed for a loan |
| `npa.classified` | NPA Engine | Collection, Bureau Reporting, Reporting | Loan moved to NPA |
| `loan.closed` | LMS | NOC Service, Notification, Bureau Reporting | Loan fully paid / foreclosed |
| `loan.foreclosed` | LMS | NOC Service, Notification, Bureau Reporting | Foreclosure complete |
| `noc.generated` | NOC Service | Notification | NOC ready for delivery |
| `reconciliation.mismatch` | LMS | Grievance Service, Ops Slack | Unreconciled payment after T+2 days |
| `bureau.report.due` | Scheduler | Bureau Reporting Engine | Monthly bureau report trigger |

---

## 7. Service Architecture

```
                      ┌─────────────────────────────────────────┐
                      │            LMS SERVICE                  │
                      │         (Node.js / FastAPI)             │
                      └───────────────┬─────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────────┐
          ▼                           ▼                               ▼
┌──────────────────┐      ┌──────────────────────┐       ┌────────────────────┐
│ Schedule Engine  │      │  Payment Engine       │       │  Reporting Engine  │
│ • EMI generation │      │  • EMI posting        │       │  • RBI return      │
│ • Broken period  │      │  • Allocation logic   │       │  • Bureau submit   │
│ • Restructure    │      │  • Reconciliation     │       │  • NPA provisioning│
└──────────────────┘      └──────────────────────┘       └────────────────────┘
          ▼                           ▼                               ▼
┌──────────────────┐      ┌──────────────────────┐       ┌────────────────────┐
│ DPD / Penalty    │      │  Foreclosure /         │       │  NOC / Document    │
│ Engine (Cron)    │      │  Prepayment Engine    │       │  Engine            │
│ • DPD calc       │      │  • Quote generation   │       │  • PDF generation  │
│ • Penalty accrual│      │  • Schedule recalc    │       │  • S3 storage      │
│ • NPA classifier │      │  • OTS settlement     │       │  • Email + WA      │
└──────────────────┘      └──────────────────────┘       └────────────────────┘
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
              ┌──────────────────┐      ┌────────────────────┐
              │   Digio          │      │   Razorpay         │
              │ (eNACH / eSign)  │      │ (UPI Autopay /     │
              └──────────────────┘      │  Payment Links)    │
                                        └────────────────────┘
```

---

## 8. Payment Reconciliation

```
Daily reconciliation (runs at 23:30 IST):

1. Fetch all payments from gateway (Digio/Razorpay settlement report)
2. Match against payments table by utr_ref
3. Flag:
   a. MATCHED    → status already 'success'; no action
   b. GATEWAY_SUCCESS_NOT_IN_DB → create payment record; post to loan
   c. DB_SUCCESS_GATEWAY_MISSING → flag for ops review (possible double-credit)
   d. AMOUNT_MISMATCH → flag for ops review

4. For each unreconciled payment after T+2 days:
   → Publish event 'reconciliation.mismatch' to Grievance Service
   → Escalate to ops team via Slack webhook
   // Grievance Service creates the ticket; LMS only raises the event

Reconciliation report → regulatory_reports table (monthly)
```

---

## 9. RBI Compliance Checklist — LMS

| # | Regulation | Requirement | Implementation |
|---|---|---|---|
| 1 | RBI DLG 2022 | KFS must be stored and accessible to customer throughout loan lifecycle | `documents` endpoint; S3 with signed URL |
| 2 | RBI DLG 2022 | 3-day cooling-off period post-disbursal (cancel without penalty) | `cooling_off_until` field; foreclosure zero-charge window |
| 3 | RBI DLG 2022 | Pre-debit notification 24 hrs before auto-debit | `pre_debit_notification` cron; DLT SMS + WhatsApp |
| 4 | RBI Penal Charges Circular (Jan 2024) | Penal charges must be reasonable, not compounded on principal, disclosed in KFS | Separate `penalty_ledger`; not added to `outstanding_principal` |
| 5 | RBI Penal Charges Circular (Jan 2024) | No capitalisation of penal interest | Penalty tracked separately; never added to principal |
| 6 | RBI Floating Rate Reset Circular (Aug 2023) | Customer must be notified of EMI / tenure change on rate reset | `roi_change_notification` event in notification service |
| 7 | RBI NPA Norms | 90-day overdue = NPA; 180-day = sub-standard; provisioning required | `npa_classifier` cron; `npa_provisioning` table |
| 8 | RBI Fair Practice Code | Payment allocation: charges → interest → principal order | `postPayment()` allocation logic |
| 9 | RBI Fair Practice Code | Annual / periodic account statement free of charge | `GET /:id/statement` endpoint; first copy free |
| 10 | RBI Fair Practice Code | NOC within 30 days of loan closure (7 days for digital lending) | `noc_generation_queue` with 72-hr SLA |
| 11 | RBI NBFC Directions 2016 | Monthly bureau reporting (CIBIL / Equifax / Experian) | `monthlyBureauReporting()` on 5th of month |
| 12 | RBI NBFC Directions 2016 | Grievance redressal within 15 days; Ombudsman if unresolved in 30 days | Grievance Service (external); LMS exposes read APIs and waiver endpoint |
| 13 | IT Act 2000 / DPDP Act 2023 | Customer data must be stored in India | All data in AWS `ap-south-1` (Mumbai) |
| 14 | CGST Act 2017 | GST @ 18% on all fees, penalties, bounce charges (not on interest) | Separate GST fields on all charge rows |
| 15 | RBI DLG 2022 | Borrower must be able to see full cost of loan at any point | `GET /:id/outstanding` with full breakup |
| 16 | RBI Master Direction | No prepayment penalty on floating rate loans (consumer) | Prepayment engine checks loan type |
| 17 | SARFAESI Act 2002 | Notice mandatory before enforcement for secured loans > ₹1 lakh | Legal notice tracked in collection module; Grievance Service records the dispute |
| 18 | RBI Ombudsman Scheme | Escalation path must exist for unresolved grievances | Grievance Service escalation ladder; LMS publishes events Grievance Service listens to |

---

## 10. Security Implementation (LMS-Specific)

| Concern | Implementation |
|---|---|
| Duplicate payment prevention | Idempotency check on `utr_ref` before any payment post |
| Race condition on payment posting | Row-level `SELECT ... FOR UPDATE` on `loans` row |
| PAN / Aadhaar decryption | Decrypt only in authorized LMS service; never logged or returned in API response as plaintext |
| NOC tamper detection | SHA-256 hash stored alongside S3 key; verified on download |
| Ledger immutability | `loan_ledger` rows are INSERT-only; no UPDATE or DELETE permitted; enforced via PG row-level security |
| Audit trail | Every LMS state change emits to `audit_logs`; includes `actor_id`, `ip_address`, `payload_before`, `payload_after` |
| Bureau data | CIBIL / Equifax member credentials in AWS Secrets Manager; rotated quarterly |
| Webhook verification | All inbound webhooks (Digio, Razorpay) verified via HMAC-SHA256 signature before processing |
| API rate limits | Admin endpoints: 60 req/min; Customer endpoints: 30 req/min; Webhook: 500 req/min |

---

## 11. Key Fact Statement (KFS) — Ongoing Accessibility

Per RBI DLG 2022, the KFS generated at loan origination must remain accessible to the borrower at all times.

```
KFS fields stored in loan_applications (immutable):
  kfs_s3_key           S3 path to signed KFS PDF
  kfs_generated_at     Timestamp of KFS generation
  kfs_sha256_hash      Tamper-proof hash

LMS endpoint GET /loans/:id/kfs:
  1. Fetch kfs_s3_key from loan_applications
  2. Generate pre-signed S3 URL (expires 60 minutes)
  3. Verify SHA-256 hash of stored file
  4. Return URL to customer
  5. Log access in audit_logs
```

---

## 12. Error Handling & Idempotency

| Scenario | Handling |
|---|---|
| Duplicate UTR in payment posting | Return HTTP 200 with existing payment record (idempotent) |
| Digio webhook received twice | Idempotency key check on `gateway_ref`; second receipt ignored |
| DPD cron fails mid-run | All updates wrapped in DB transaction; partial run is rolled back; job re-runs from checkpoint |
| NACH debit file submission fails | Retry with exponential backoff (3 attempts); alert ops if all fail |
| Bureau submission rejected | Flag `credit_bureau_reports.status = 'rejected'`; alert compliance team; resubmit corrected file |
| NOC generation PDF fails | Queue retry (max 3); escalate to ops ticket if all fail; SLA timer continues |
| Kafka/SQS message not consumed | Dead letter queue (DLQ) with 3-retry policy; DLQ alert to engineering |

---

## 13. Notification Templates (LMS Events)

| Event | Channel | Tata DLT Template ID | Trigger |
|---|---|---|---|
| EMI due tomorrow | SMS + WhatsApp | `emi_reminder_t1` | T-1 pre-debit cron |
| EMI debit success | SMS + WhatsApp | `emi_success` | Payment webhook |
| EMI debit failed | SMS + WhatsApp | `emi_bounce` | Bounce webhook |
| EMI overdue DPD 3 | SMS + WhatsApp | `emi_overdue_d3` | DPD engine |
| Penalty applied | SMS | `penalty_applied` | Penalty engine |
| Foreclosure quote | Email + WhatsApp | — | Foreclosure API |
| Foreclosure complete | SMS + WhatsApp + Email | `loan_closed` | LMS close event |
| NOC issued | SMS + WhatsApp + Email | `noc_issued` | NOC generator |
| OTS offer | SMS + WhatsApp + Email | `ots_offer` | Collection team |
| NPA classified | SMS | `npa_notice` | NPA engine |
| Legal notice | Registered post + SMS | `legal_notice_d60` | Legal cron |
| Grievance received | SMS + Email | `grievance_ack` | Grievance Service (not LMS) |
| Grievance resolved | SMS + Email | `grievance_resolved` | Grievance Service (not LMS) |
| Rate reset notification | SMS + Email | `rate_reset` | Rate change event |
| Cross-sell eligible | Push + WhatsApp | `cross_sell` | Cross-sell engine |

---

## 14. Interfaces with Other Services

| Interface | Direction | Data Exchanged |
|---|---|---|
| LOS → LMS | Inbound event (`loan.disbursed`) | Full loan + application + customer snapshot |
| LMS → Payment Service | Outbound calls | Mandate cancel/pause; excess refund trigger |
| LMS → Notification Service | Event publish | All notification events with template + data |
| LMS → Audit Service | Event publish | Every state change |
| LMS → Reporting Service | Direct query | DPD buckets, NPA list, bureau data |
| LMS → PDF Service | Sync HTTP | NOC and statement generation |
| LMS → Digio | Outbound + inbound webhooks | eNACH presentation; mandate status |
| LMS → Razorpay | Outbound + inbound webhooks | UPI Autopay; payment links |
| LMS → CIBIL / Equifax / Experian | Outbound batch | Monthly bureau file submission |
| LMS → S3 | Direct SDK | Document storage (NOC, statements, KFS) |
| LMS → Redis | Direct | DPD cache; rate-limit keys; idempotency store |
| Grievance Service → LMS | Inbound REST | `GET /dispute-summary`, `GET /ledger`, `GET /bureau-status`, `POST /waiver` |
| LMS → Grievance Service | Event publish | `reconciliation.mismatch`, `loan.closed`, `noc.generated`, `payment.received` |
