# LMS Calculations & Charges Reference
## True Loan Bazaar (TLB) — Post-Disbursal Calculations

> **Scope:** All formulas, worked examples, and accounting entries the LMS engines use after
> a loan is disbursed. Pre-disbursal calculations (FOIR, risk scoring, processing fee deduction,
> net disbursed computation) belong to the LOS and are documented in R&D-docs/v0/.
>
> **Sources:** TLB_Calculations_and_Charges.md · TLB_Payment_Flows_and_Calculations.md
> **Regulatory basis:** RBI DLG 2022 · RBI Fair Practice Code · Penal Charges Circular (Jan 2024)
> · CGST Act 2017 · IT Act 2000 (Section 80E)

---

## 1. Interest Rate Reference

### 1.1 Risk Band → ROI Matrix (stamped on `loans.roi_monthly` at disbursal)

| Risk Band | P2P Score | CIBIL | ROI Monthly (Reducing) | ROI Annual |
|---|---|---|---|---|
| A — Prime | 750–1000 | 750+ | 1.50% – 2.00% | 18% – 24% |
| B — Near-Prime | 550–749 | 650–749 | 2.00% – 2.75% | 24% – 33% |
| C — Sub-Prime | 350–549 | 550–649 | 2.75% – 4.00% | 33% – 48% |

### 1.2 Payday Daily Rate Table

| Risk Band | Daily Rate | Max Ticket | Max Tenor |
|---|---|---|---|
| A | 0.10% / day | ₹50,000 | 30 days |
| B | 0.12% / day | ₹25,000 | 30 days |
| C | 0.15% / day | ₹15,000 | 30 days |

> **LMS usage:** `loans.roi_monthly` and `loans.roi_daily` are read-only from the LMS perspective.
> They are stamped by the LOS at disbursal and never changed except by a float rate reset event.

---

## 2. Repayment Schedule Generation

### 2.1 Reducing Balance EMI (Standard EMI Loans)

```
       P × r × (1 + r)^n
EMI  = ─────────────────
         (1 + r)^n − 1

Where:
  P  = Principal (sanctioned loan amount)
  r  = Monthly interest rate  =  roi_monthly / 100
  n  = Tenure in months
```

**Per-installment breakdown (for schedule generator):**

```
For installment number k (1-indexed):
  Opening Balance (k)   =  P×(1+r)^(k−1) − EMI×[(1+r)^(k−1)−1] / r
  Interest Component    =  Opening Balance(k) × r
  Principal Component   =  EMI − Interest Component
  Closing Balance (k)   =  Opening Balance(k) − Principal Component

  Last installment: principal_amt = outstanding (absorbs rounding delta)
```

> **WORKED EXAMPLE — ₹50,000 @ 2.5%/month, 6 months (Band B)**
> ```
> P = ₹50,000  |  r = 0.025  |  n = 6
> EMI = 50,000 × 0.025 × (1.025)^6 / ((1.025)^6 − 1) ≈ ₹9,079
>
> Month | Opening Bal | EMI    | Interest | Principal | Closing Bal
> ──────────────────────────────────────────────────────────────────
>   1   | 50,000      | 9,079  | 1,250    | 7,829     | 42,171
>   2   | 42,171      | 9,079  | 1,054    | 8,025     | 34,146
>   3   | 34,146      | 9,079  |   854    | 8,226     | 25,920
>   4   | 25,920      | 9,079  |   648    | 8,431     | 17,489
>   5   | 17,489      | 9,079  |   437    | 8,642     |  8,847
>   6   |  8,847      | 9,068* |   221    | 8,847     |      0
>
> *Last EMI adjusted for rounding.
> Total Interest = ₹4,464  |  Total Repaid = ₹54,464
> ```

### 2.2 Flat Rate EMI

```
Total Interest   =  P × Flat Rate × n
Total Repayable  =  P + Total Interest
EMI              =  Total Repayable / n

Effective monthly rate (approx.) ≈ Flat Rate × 1.83
(Flat rate is always more expensive than the stated rate implies)
```

> **WORKED EXAMPLE — ₹50,000 @ 2.0% flat/month, 6 months**
> ```
> Total Interest   = 50,000 × 2.0% × 6  = ₹6,000
> Total Repayable  = 50,000 + 6,000      = ₹56,000
> EMI              = 56,000 / 6          = ₹9,333 / month
> Effective reducing-equivalent rate ≈ 3.66% / month
> ```

### 2.3 Bullet / Payday Loan (Single Repayment)

```
Total Interest   =  Principal × Daily Rate × Tenor (days)
Total Repayable  =  Principal + Total Interest

Single repayment due on maturity date.
```

> **WORKED EXAMPLE — ₹10,000 @ 0.12%/day, 21 days (Band B)**
> ```
> Total Interest    = 10,000 × 0.0012 × 21 = ₹252
> Total Repayable   = ₹10,252 (due on day 21)
> ```

### 2.4 Broken-Period Interest (First EMI When Disbursal Is Not on 1st)

```
Broken Period Days  =  Days from disbursal date to first EMI date

Broken Period Int.  =  Principal × (roi_monthly / 100 / 30) × Broken Period Days

First EMI Total     =  Regular EMI + Broken Period Interest
Subsequent EMIs     =  Regular EMI (unchanged)
```

> **WORKED EXAMPLE — Disbursal on 10th, first EMI on 1st of next month**
> ```
> Broken Period Days  = 21
> Principal           = ₹50,000  |  roi_monthly = 2.5%
> Broken Period Int.  = 50,000 × (0.025/30) × 21 = ₹875
> First EMI           = ₹9,079 + ₹875 = ₹9,954
> ```

---

## 3. Daily Interest Accrual

```
Daily Interest  =  outstanding_principal × (roi_monthly / 100 / 30)

Runs at 00:05 IST. Adds to loans.accrued_interest.
Posted to loan_ledger as entry_type = 'interest_due'.
```

---

## 4. Outstanding Principal Formula (Point-in-Time)

Used by foreclosure engine, outstanding API, and statement generator.

```
Outstanding after k EMIs paid:
  OP  =  P × (1+r)^k  −  EMI × [(1+r)^k − 1] / r

Where:
  P   = Original principal
  r   = Monthly ROI / 100
  k   = Number of EMIs fully paid
  EMI = Regular monthly instalment
```

> **WORKED EXAMPLE — Outstanding after 3 EMIs (₹50,000 @ 2.5%, 6m)**
> ```
> OP = 50,000×(1.025)^3 − 9,079×((1.025)^3−1)/0.025
>    = 53,844 − 27,920 = ₹25,924
> ```

---

## 5. APR / Annualised Cost of Credit (KFS Disclosure)

Per RBI DLG 2022 — APR must be disclosed in the KFS and accessible throughout the loan lifecycle.

```
Simple APR  =  [(Total Amount Repaid − Net Disbursed) / Net Disbursed]
               × (365 / Tenor in days) × 100

XIRR-based APR (required for reducing-balance loans — use for KFS):
  Solve for r:  Net Disbursed = Σ  EMI_t / (1 + r)^(t/365)
  where t = days from disbursal to each payment date
```

> **WORKED EXAMPLE — ₹50,000, 6 months, Band B**
> ```
> Net Disbursed        = ₹47,363
> Total EMIs           = ₹54,463
> Total Cost of Credit = ₹7,100  (interest ₹4,463 + charges ₹2,637)
> Simple APR           = (7,100/47,363) × (365/180) × 100 ≈ 30.4% p.a.
>
> KFS Mandatory Fields:
>   Sanctioned Amount    ₹50,000
>   Net Disbursed        ₹47,363
>   Total Repayable      ₹54,463
>   Total Cost of Credit ₹7,100
>   APR                  ~30.4% p.a.
>   Cooling-off Period   3 days
> ```

---

## 6. Payment Application Waterfall

When any payment is received, LMS applies it in this exact priority order (RBI FPC mandated):

```
Payment Received
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│  PRIORITY ORDER (highest first)                          │
│                                                          │
│  1st  →  Legal / Court / Recovery Charges   (+ GST)     │
│  2nd  →  Bounce / Dishonour Charges         (+ GST)     │
│  3rd  →  Penal Interest (DPD 30+)           (+ GST)     │
│  4th  →  Late Payment Penalty (DPD 1–29)    (+ GST)     │
│  5th  →  Overdue Regular Interest           (no GST)    │
│  6th  →  Overdue Principal                  (no GST)    │
│  7th  →  Current Period Interest            (no GST)    │
│  8th  →  Current Period Principal           (no GST)    │
│  9th  →  Excess → held as advance / prepayment rules    │
└──────────────────────────────────────────────────────────┘
```

**Waterfall calculation (pseudocode matching Engine 4.4):**

```
Remaining  =  Payment Amount

Step 1:  Applied = min(Remaining, Legal + GST);        Remaining -= Applied
Step 2:  Applied = min(Remaining, Bounce + GST);       Remaining -= Applied
Step 3:  Applied = min(Remaining, Penal Interest+GST); Remaining -= Applied
Step 4:  Applied = min(Remaining, Late Penalty + GST); Remaining -= Applied
Step 5:  Applied = min(Remaining, Overdue Interest);   Remaining -= Applied
Step 6:  Applied = min(Remaining, Overdue Principal);  Remaining -= Applied
Step 7:  Applied = min(Remaining, Current Interest);   Remaining -= Applied
Step 8:  Applied = min(Remaining, Current Principal);  Remaining -= Applied
Step 9:  Residual > 0 → excess_amount on payments row
```

> **WORKED EXAMPLE — ₹5,000 partial payment on DPD 45**
> ```
> Bounce charges (2× eNACH)  = ₹944   → Applied ₹944  | Remaining ₹4,056
> Late penalty (DPD 1–30)    = ₹428   → Applied ₹428  | Remaining ₹3,628
> Penal interest (DPD 31–45) = ₹321   → Applied ₹321  | Remaining ₹3,307
> Overdue interest            = ₹1,875 → Applied ₹1,875| Remaining ₹1,432
> Overdue principal           = ₹7,829 → Applied ₹1,432| Remaining ₹0
>
> Outstanding reduced by ₹5,000. Principal still owed = ₹7,829 − ₹1,432 = ₹6,397.
> ```

---

## 7. Bounce & Late Payment Charges

### 7.1 Bounce Charge

```
eNACH Bounce:     ₹400 + ₹72 GST  = ₹472 per bounce
UPI Autopay:      ₹300 + ₹54 GST  = ₹354 per bounce

Max 3 attempts (original + D+2 + D+3) → up to 3 bounce charges possible.
Rates read from charge_master (charge_code = 'BOUNCE_CHARGE').
```

### 7.2 Late Payment Penalty (DPD 1–29)

```
Daily Penal Rate  =  2% per month on overdue EMI  =  0.0667% per day

Penalty Amount    =  Overdue EMI × (0.02 / 30) × Days Overdue
GST on Penalty    =  Penalty × 18%
```

> **WORKED EXAMPLE — ₹9,079 EMI, DPD 15, 1 eNACH bounce**
> ```
> Penalty          = 9,079 × 0.000667 × 15 = ₹91
> GST on Penalty   = 91 × 18%               = ₹16
> Bounce Charge    = ₹400 + ₹72 GST        = ₹472
> ─────────────────────────────────────────────────
> Total Outstanding = 9,079 + 91 + 16 + 472 = ₹9,658
> ```

### 7.3 Penal Interest (DPD 30+ — RBI Penal Charges Circular Jan 2024)

```
Rate on total overdue outstanding (principal + accrued interest):
  DPD 30–60:  3% / month  (0.10% per day)
  DPD 61+:    Per charge_master (up to 5% / month for sub-prime)

GST on Penal Interest = Amount × 18%

CRITICAL RBI RULE: Penal charges are NEVER capitalised into principal.
  → Tracked in penalty_ledger separately
  → Never added to loans.outstanding_principal
  → Never compounded on top of the principal balance
```

### 7.4 DPD-wise Cumulative Outstanding

| DPD | Charge | Rate | GST |
|---|---|---|---|
| 1–7 | Bounce (if debit attempted) | ₹400 eNACH / ₹300 UPI per attempt | 18% |
| 8–29 | Late payment penalty | 2% / month on overdue EMI | 18% |
| 30–60 | Penal interest | 3% / month on total overdue OS | 18% |
| 60 | Legal notice charge (one-off) | ₹500 flat | 18% |
| 60+ | Continued penal interest | 3–5% / month | 18% |
| 90+ | NPA; full provisioning begins | — | — |

> **WORKED EXAMPLE — Total overdue on DPD 38 (₹9,079 EMI, Band B)**
> ```
> Overdue EMI               = ₹9,079
> Bounce (2× eNACH)         = 2 × ₹472 = ₹944
> Late penalty DPD 1–30     = 9,079 × 0.000667 × 30 × 1.18 = ₹215
> Penal interest DPD 31–38  = 9,079 × 0.001    × 8  × 1.18 = ₹86
> ──────────────────────────────────────────────────────────────
> Total overdue amount      = ₹10,324
> ```

---

## 8. Foreclosure Calculation

```
Outstanding Principal at foreclosure (k EMIs paid):
  OP  =  P×(1+r)^k  −  EMI×[(1+r)^k − 1]/r

Accrued Interest (d days into current EMI cycle):
  Accrued  =  OP × (r / 30) × d

Foreclosure Charge (fixed-rate loans only):
  FC Rates: Band A = 2% | Band B = 3% | Band C = 4%
  Surcharge +1% if closed within first 3 months
  FC Charge   = OP × FC Rate
  GST on FC   = FC Charge × 18%

FLOATING RATE LOANS → FC Charge = 0, GST = 0
  (RBI Master Direction for NBFCs — no foreclosure charge on floating-rate
   term loans to individual borrowers)

Total Foreclosure Payment  =  OP + Accrued Interest + FC Charge + GST on FC
                            + Any overdue / penalty balance
```

> **WORKED EXAMPLE — Foreclosure on Day 15 of Month 4 (₹50,000, Band B, 6m)**
> ```
> EMIs paid              = 3
> OP                     = ₹25,924
> Accrued interest       = 25,924 × (0.025/30) × 15 = ₹324
> FC Charge (3%)         = 25,924 × 3%               = ₹778
> GST on FC (18%)        = 778 × 18%                 = ₹140
> ──────────────────────────────────────────────────────────
> Total Foreclosure      = 25,924 + 324 + 778 + 140  = ₹27,166
>
> Interest saved vs. completing loan:
>   Remaining interest (EMIs 4,5,6) = ₹1,306
>   FC charge paid                  = ₹918
>   Net saving to customer          = ₹388
>
> Accounting entry:
>   Dr  Bank A/c                  ₹27,166
>   Cr  Loan Account (Borrower)  ₹25,924  (principal closure)
>   Cr  Interest Income             ₹324  (accrued)
>   Cr  Foreclosure Fee Income      ₹778
>   Cr  GST Payable                 ₹140
> ```

---

## 9. Part-Prepayment Calculation

```
Prepayment Charge   =  Prepayment Amount × Charge Rate (from charge_master)
GST on Charge       =  Prepayment Charge × 18%
Total Paid          =  Prepayment Amount + Prepayment Charge + GST
Net Principal Reduction  =  Prepayment Amount − Prepayment Charge − GST

New Outstanding     =  OP (before prepayment) − Net Principal Reduction

OPTION A — Reduce Tenure (same EMI):
  Solve for n_new:  n_new = −ln(1 − New OS × r / EMI) / ln(1+r)

OPTION B — Reduce EMI (same tenure):
  New EMI = New OS × r × (1+r)^n_rem / ((1+r)^n_rem − 1)
  where n_rem = remaining installments
```

> **WORKED EXAMPLE — ₹15,000 prepayment after 3 EMIs (₹50,000, Band B, 6m)**
> ```
> OS after 3 EMIs         = ₹25,920
> Prepayment Amount       = ₹15,000
> Charge (Band B = 2.5%)  = 15,000 × 2.5% = ₹375
> GST (18%)               = ₹68
> Net Principal Reduction = 15,000 − 375 − 68 = ₹14,557
> New Outstanding         = 25,920 − 14,557   = ₹11,363
>
> OPTION B — Revised EMI (3 months remaining, 2.5%/month):
>   New EMI = 11,363 × 0.025 × (1.025)^3 / ((1.025)^3 − 1) ≈ ₹3,906
>   Original EMI was ₹9,079 → customer saves ₹5,173/month for 3 months.
>
> Accounting:
>   Dr  Bank A/c                  ₹15,443
>   Cr  Loan Account (Borrower)  ₹14,557
>   Cr  Prepayment Fee Income       ₹375
>   Cr  GST Payable                  ₹68
> ```

---

## 10. Cooling-off Period Refund (RBI DLG 2022)

```
Cooling-off window  =  3 calendar days from disbursal_date
                      (cooling_off_until = disbursal_date + 3)

Customer exits: Zero foreclosure charge. Only proportionate interest charged.

Proportionate Interest  =  Principal × (roi_monthly / 100 / 30) × Days Held
Days Held               =  Refund date − Disbursal date

Refund Amount  =  Net Disbursed Amount − Proportionate Interest

Non-refundable (services already rendered):
  Processing Fee + GST, Stamp Duty, NACH Charge + GST, Insurance + GST
```

> **WORKED EXAMPLE — Exit on Day 2 (₹50,000, Band B)**
> ```
> Net Disbursed           = ₹47,363
> Days Held               = 2
> Proportionate Interest  = 50,000 × (0.025/30) × 2 = ₹83
> Refund to Customer      = ₹47,363 − ₹83 = ₹47,280
>
> NBFC sends ₹47,280 via IMPS within 24 hours.
>
> Accounting:
>   Dr  Loan Account (Borrower)  ₹50,000
>   Cr  Bank A/c (refund)        ₹47,280
>   Cr  Interest Income               ₹83
>   Cr  Income — Processing Fee   ₹1,500  (retained)
>   Cr  GST Payable — PF            ₹270
>   [Stamp, NACH, Insurance similarly retained]
> ```

---

## 11. OTS Settlement Calculation

```
OTS Amount  =  Outstanding Principal (OP)  [always 100% retained]
            +  Negotiated Interest (% of total accrued regular interest)
            −  Penal Interest Waiver        (100% waived per RBI FPC)
            −  Legal Charges Waiver         (100% waived)
            +  OTS Processing Fee  (OTS Base × 1%)
            +  GST on OTS Fee (1% × 18%)

DPD Slab        | Regular Interest Retained | Waiver
────────────────────────────────────────────────────────
DPD  90–180     | 50%                       | 100% penal + legal
DPD 181–365     | 25%                       | 100% penal + legal
DPD  365+       | 0%                        | 100% penal + legal
Written-off     | 0%                        | Recover principal only

Note: CIBIL status after OTS = "Settled" (NOT "Closed" — impacts credit score differently)
```

> **WORKED EXAMPLE — OTS at DPD 120 (₹50,000, Band B)**
> ```
> Outstanding Principal    = ₹50,000
> Accrued Regular Interest = ₹5,000  (4 months × 2.5%)
> Penal Interest Total     = ₹4,381
> Legal Charges            = ₹1,000
> Total Gross Outstanding  = ₹60,381
>
> OTS Terms (DPD 90–180):
>   Principal retained          = ₹50,000
>   Interest retained (50%)     = ₹2,500
>   OTS Base                    = ₹52,500
>   OTS Processing Fee (1%)     = ₹525
>   GST on Fee (18%)            = ₹95
>   ────────────────────────────────────
>   Final OTS Payment           = ₹53,120
>
> Accounting:
>   Dr  Bank A/c                        ₹53,120
>   Dr  Provision for NPA (write-back) ₹16,382  (25% provision release)
>   Cr  Loan Account (Borrower)        ₹60,381
>   Cr  Income — OTS Fee                  ₹525
>   Cr  GST Payable                         ₹95
>   Cr  Income — Provision Write-back  ₹16,382
>   Cr  Income — Interest Recovery      ₹2,500
> ```

---

## 12. NPA Provisioning

Per RBI Prudential Norms — provisioning is a percentage of net outstanding.

```
Net Outstanding  =  outstanding_principal − collateral_value

NPA Duration     | Classification  | Provisioning %
─────────────────────────────────────────────────────
< 12 months      | Sub-Standard    | 10%
12–24 months     | Doubtful-1      | 25%
24–36 months     | Doubtful-2      | 40%
> 36 months      | Doubtful-3      | 100%
Identified loss  | Loss Asset      | 100%

Provision Amount = Net Outstanding × Provision % / 100
```

---

## 13. NPA Upgrade Conditions

```
Upgrade NPA → Active (Standard) when ALL of:
  1. total_overdue ≤ ₹0.01
  2. total_penalty ≤ ₹0.01
  3. accrued_interest ≤ ₹0.01
  4. 3 consecutive scheduled installments paid on time (dpd_on_payment = 0)
     after the arrear clearance date

On upgrade:
  provision_pct = 0, provision_amount = 0
  Bureau reclassification to 'STD'
```

---

## 14. Annual Interest Certificate (Section 80E / IT Act)

Used for borrower tax filing. Generated by `interest_certificate_generator` cron on 1 April.

```
For financial year FY (1 Apr – 31 Mar):
  Total Interest Paid  =  SUM(allocated_interest)
                          FROM payments
                          WHERE loan_id = X
                          AND   settled_at BETWEEN FY_start AND FY_end
                          AND   status = 'success'

Alternatively from loan_ledger:
  Total Interest  =  SUM(credit)
                     WHERE entry_type = 'payment_received'
                     AND   effective_date BETWEEN FY_start AND FY_end
                     (interest portion only — use payments.allocated_interest)
```

---

## 15. GST Applicability on LMS Charges

| Charge | GST | Rate | SAC Code |
|---|---|---|---|
| Late Payment Penalty | Yes | 18% | 999714 |
| Bounce / Dishonour Charge | Yes | 18% | 999714 |
| Penal Interest | Yes | 18% | 999714 |
| Foreclosure Charge | Yes | 18% | 999714 |
| Part-Prepayment Charge | Yes | 18% | 999714 |
| Legal / Recovery Charge | Yes | 18% | 998216 |
| OTS Processing Fee | Yes | 18% | 999714 |
| Regular Interest (ROI) | **No** | Exempt | — |
| Principal repayment | **No** | Not applicable | — |

> **Rule:** GST applies to all fees and penalty charges. GST does NOT apply to interest (ROI).
> GST is tracked as a separate column on every charge row — never bundled with the charge amount.

---

## 16. Payment Reconciliation Checks

```
Daily reconciliation (23:30 IST) — 5 checks:

Check 1 — Amount:
  Σ payments received (Gateway) = Σ payments applied (LMS)

Check 2 — Count:
  No. successful transactions (Gateway) = No. EMIs marked PAID (LMS)

Check 3 — Suspense:
  Unmatched payments in VAN/suspense → Manual resolution < 24h

Check 4 — Bounce:
  No. NACH returns (Bank) = No. bounce charges created (LMS)

Check 5 — Disbursal:
  No. IMPS/UPI sent (Bank) = No. loans moved to ACTIVE (LMS)

Tolerance: ₹1.00 (configurable via tenant_configs.reconciliation_tolerance_inr)
```

| Mismatch Type | Action | TAT |
|---|---|---|
| Payment received, not in LMS | Hold suspense; Ops alert | 4 hours |
| LMS PAID, bank not credited | Reverse LMS entry; raise failure | 2 hours |
| Amount mismatch | Apply waterfall to received amount; flag | 24 hours |
| Duplicate payment | Second payment to suspense; refund | 48 hours |

---

## 17. Quick Reference — All LMS Formulas

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REDUCING BALANCE EMI:
  EMI = P×r×(1+r)^n / ((1+r)^n − 1)

OUTSTANDING AFTER k EMIs:
  OP  = P×(1+r)^k − EMI×((1+r)^k − 1)/r

DAILY INTEREST ACCRUAL:
  Daily Int = outstanding_principal × (roi_monthly/100/30)

BROKEN PERIOD (first EMI):
  Extra = P × (roi_monthly/100/30) × days_from_disbursal_to_first_due

BULLET (Payday):
  Repayable = P + P × roi_daily × tenor_days

LATE PAYMENT PENALTY (DPD 1–29):
  Daily Penalty = overdue_emi × (0.02/30)
  GST           = Penalty × 0.18

PENAL INTEREST (DPD 30+):
  Daily Penal   = total_overdue_outstanding × (0.03/30)
  GST           = Penal × 0.18
  NEVER capitalised into principal (RBI Jan 2024)

FORECLOSURE:
  FC Charge  = OP × FC_Rate  (0 for floating-rate loans)
  Total      = OP + Accrued_Int + FC_Charge×1.18 + Overdue

COOLING-OFF REFUND:
  Refund     = Net_Disbursed − P×(roi_monthly/100/30)×days_held
  PF, NACH, Insurance, Stamp Duty — non-refundable

PART-PREPAYMENT:
  Net_Reduction = Prepay − Prepay×Rate×1.18
  New EMI or Tenor via standard formula on (OP − Net_Reduction)

OTS:
  OTS_Amount = OP + (Interest × Retention%) + OTS_Fee×1.18
  Penal interest and legal charges → 100% waived

GST ON CHARGES:
  All fees except ROI and stamp duty → 18%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

*True Loan Bazaar (TLB) | LMS Calculations Reference v1.0 | Confidential*
*Sources: TLB_Calculations_and_Charges.md · TLB_Payment_Flows_and_Calculations.md*
*Compliant with RBI DLG 2022 · RBI FPC · Penal Charges Circular Jan 2024 · CGST Act 2017*
