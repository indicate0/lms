# Collection & Delinquency Management
## True Loan Bazaar (TLB) — Micro-Lending Platform

**Complete Workflow, Escalation Logic & Financial Calculations**

> Covers: DPD Classification · Penalty Calculations · Restructuring · OTS Settlement · NPA Provisioning · Collection Metrics
> Compliant with RBI Digital Lending Guidelines 2022, RBI NPA Circular, SARFAESI Act

---

## 1. Framework Overview

TLB's collection system is a fully automated, DPD-driven escalation engine integrated into the LMS. It transitions from soft digital nudges on Day 1 to legal proceedings at DPD 90+, with every action logged in the Audit Service and every charge calculated and applied in real-time.

```
Loan Disbursed → Active
      │
      └─► EMI due date arrives
               │
          ┌────┴────────────────────────────────────────────┐
          ▼ (Payment SUCCESS)                               ▼ (Payment FAILED)
   EMI marked PAID                                  DPD clock starts → Day 1
   Next cycle begins                                         │
                                              ┌──────────────┼──────────────────┐
                                              ▼              ▼                  ▼
                                          DPD 1–30      DPD 31–60          DPD 61–90
                                          SMA-0         SMA-1              SMA-2
                                          Soft collect  Hard collect       Pre-NPA
                                              │              │                  │
                                              └──────────────┴──────────────────┘
                                                                    │
                                                              DPD 90+ → NPA
                                                              Legal / Write-off
```

---

## 2. DPD Classification & RBI Asset Categories

### 2.1 DPD Bucket Definitions

| DPD Range | RBI Category | Internal Label | Collection Mode | Reporting |
|---|---|---|---|---|
| 0 | Standard Asset | CURRENT | Automated reminders | Normal |
| 1–30 | SMA-0 | EARLY DELINQUENT | Digital nudges + auto-debit retry | SMA report to RBI |
| 31–60 | SMA-1 | MID DELINQUENT | Tele-calling + field escalation | SMA report to RBI |
| 61–90 | SMA-2 | LATE DELINQUENT | Legal notice + senior escalation | SMA report to RBI |
| 91–365 | Sub-Standard (NPA) | NPA-SS | Legal proceedings | NPA report to Credit Bureau |
| 366–730 days as NPA | Doubtful-1 (NPA) | NPA-D1 | Recovery / OTS | NPA provisioning 25% |
| 731–1095 days as NPA | Doubtful-2 (NPA) | NPA-D2 | Recovery / OTS | NPA provisioning 40% |
| > 1095 days as NPA | Doubtful-3 (NPA) | NPA-D3 | Write-off | NPA provisioning 100% |
| Identified as Loss | Loss Asset | LOSS | Written off | 100% provisioned |

> **SMA** = Special Mention Account. RBI requires NBFCs to report SMA accounts to Central Repository of Information on Large Credits (CRILC) for exposures > ₹5 crore. For micro-lending tickets, internal tracking applies.

### 2.2 NPA Recognition Rule

```
An account is classified as NPA when:
  Principal or Interest overdue for > 90 days  (EMI loans)
  Bullet repayment overdue for > 90 days        (Payday loans)

NPA Date  =  Due Date  +  90 days
DPD       =  Today's Date  −  First Default Date
```

---

## 3. Collection Workflow by DPD Stage

### 3.1 Stage 1 — DPD 1 to 7 (Early Bucket)

```
Auto-debit FAILED on due date
         │
         ▼
Day 1:  Bounce charge applied to loan account
        SMS + WhatsApp: "Your EMI of ₹X could not be processed."
         │
         ▼
Day 2:  Auto-debit retry attempt #2
         ├── SUCCESS → EMI marked PAID (bounce charge remains on account)
         └── FAIL    → Bounce charge #2 applied
         │
         ▼
Day 3:  Auto-debit retry attempt #3
         ├── SUCCESS → EMI marked PAID
         └── FAIL    → Bounce charge #3 applied; DPD = 3
         │
         ▼
Day 4–7: Daily penalty accruing
         SMS reminder every 2 days
         Push notification daily
```

### 3.2 Stage 2 — DPD 8 to 30 (SMA-0)

```
DPD 8:   Tele-calling queue opened; agent assigned
         WhatsApp payment link sent
         Penalty continues accruing daily

DPD 15:  Supervisor review of account
         Payment plan offered if customer responds
         (Partial payment accepted to regularise)

DPD 25:  Final soft notice: "Account may be escalated"
         WhatsApp + SMS + Email

DPD 30:  Penal interest rate escalated (from 2% to 3% per month)
         Account flagged in SMA-0 report
```

### 3.3 Stage 3 — DPD 31 to 60 (SMA-1)

```
DPD 31:  Field agent assigned (if within serviceable geography)
         Physical visit scheduled within 5 business days

DPD 45:  Legal notice drafted (pre-dispatch)
         Customer given 7-day cure window

DPD 52:  Legal notice dispatched (Registered Post + WhatsApp)
         Restructuring option offered (see Section 6)

DPD 60:  SMA-1 internal report filed
         Senior credit officer review
         OTS (One-Time Settlement) option evaluated
```

### 3.4 Stage 4 — DPD 61 to 90 (SMA-2 / Pre-NPA)

```
DPD 61:  Account moves to SMA-2
         Legal team formally engaged
         All charges (principal + interest + penal + legal) compiled

DPD 75:  Final demand notice with 15-day cure period
         Credit bureau pre-warning tag applied

DPD 90:  NPA classification triggered at end of day
         Provisioning created (15% of outstanding for sub-standard)
         Credit bureau notified (CIBIL / Equifax)
         Customer credit score impacted
```

### 3.5 Stage 5 — DPD 90+ (NPA)

```
DPD 91–180:   Legal proceedings initiated (if loan > ₹50,000)
              SARFAESI notice (if applicable)
              OTS negotiation window open

DPD 181–365:  Debt recovery tribunal (DRT) / civil suit (for larger amounts)
              Continued recovery calls + field visits

DPD 366+:     Doubtful classification
              Write-off evaluation
              Sale to Asset Reconstruction Company (ARC) considered
```

---

## 4. Outstanding Balance Calculations at Each DPD Stage

### 4.1 Base Outstanding (Principal + Accrued Regular Interest)

```
For EMI loans — outstanding principal after k EMIs paid (0 if no EMI paid):

  OP  =  P × (1+r)^k  −  EMI × [(1+r)^k − 1] / r

  If NO EMI has been paid (k=0):
  OP  =  P  (full principal outstanding)

Accrued Interest (if EMI missed):
  Overdue Interest  =  OP × r  (one month's interest on outstanding principal)
```

### 4.2 Late Payment Penalty (DPD 1–29)

```
Penal Rate     =  2% per month on overdue EMI amount
Daily Rate     =  2% / 30  =  0.0667% per day

Penalty        =  Overdue Amount  ×  0.000667  ×  Days Overdue
GST on Penalty =  Penalty  ×  18%

Overdue Amount =  Unpaid EMI(s) including their interest component
```

### 4.3 Bounce Charge Calculation

```
Bounce Charge   =  ₹400 per failed eNACH debit  (₹300 for UPI Autopay)
GST             =  Charge × 18%
Total per event =  ₹472 (eNACH) / ₹354 (UPI)

Max retries per cycle  =  3
Max bounce charges     =  3 × ₹472  =  ₹1,416 (eNACH)
```

### 4.4 Penal Interest (DPD 30+)

```
Penal Interest Rate     =  3% per month (DPD 30–60)
                           5% per month (DPD 60+)

Penal Interest Base     =  Total Overdue Outstanding
                           (= Overdue Principal + Overdue Interest + Earlier Penalties)

Monthly Penal Interest  =  Overdue Outstanding  ×  Penal Rate
Daily Penal Interest    =  Monthly Penal Interest  /  30
GST on Penal Interest   =  Monthly Penal Interest  ×  18%

Cumulative Penal Interest compounds every 30 days.
```

### 4.5 Legal / Recovery Charges (DPD 60+)

```
Legal Notice Dispatch     =  ₹500 (Registered Post + documentation)
Field Agent Visit         =  ₹300 – ₹800 per visit (actuals)
Legal Counsel Fees        =  Actuals (min ₹2,000 per case)
Court Filing Charges      =  Actuals (per jurisdiction)

All legal charges         →  GST @ 18%
All legal charges         →  Added to Loan Account; recoverable from borrower
```

### 4.6 Total Amount to Regularise (Cure Amount)

```
Cure Amount  =  Overdue EMI(s)
             +  Accrued Late Payment Penalty  +  GST
             +  Bounce Charges (all instances)  +  GST
             +  Penal Interest (if DPD 30+)  +  GST
             +  Legal Charges (if DPD 60+)  +  GST

After payment of Cure Amount → Loan status returns to CURRENT
Future EMIs continue on original schedule.
```

> **WORKED EXAMPLE — DPD 15, 1 EMI missed, 1 bounce (₹9,079 EMI, Band B)**
> ```
> Overdue EMI               = ₹9,079
> Bounce Charge (1×eNACH)   = ₹400
> GST on Bounce             = ₹72
> Penalty (DPD 1–15)        = 9,079 × 0.000667 × 15  = ₹91
> GST on Penalty            = 91 × 18%               = ₹16
> ────────────────────────────────────────────────────
> Total Cure Amount         = 9,079 + 400 + 72 + 91 + 16 = ₹9,658
> ```

> **WORKED EXAMPLE — DPD 45, 2 EMIs missed, 2 bounces (₹9,079/EMI, Band B)**
> ```
> Overdue EMIs (2)          = 9,079 × 2               = ₹18,158
> Bounce Charges (2×eNACH)  = 400 × 2                 = ₹800
> GST on Bounce             = 800 × 18%               = ₹144
> Penalty (DPD 1–30)        = 18,158 × 0.000667 × 30  = ₹363
> GST on Penalty (D1–30)    = 363 × 18%               = ₹65
> Penal Interest (DPD 31–45)= 18,158 × 3% / 30 × 15  = ₹272
> GST on Penal Int.         = 272 × 18%               = ₹49
> Legal Notice (dispatched) = ₹500
> GST on Legal              = ₹90
> ────────────────────────────────────────────────────────
> Total Cure Amount         = 18,158 + 800 + 144 + 363 + 65
>                           + 272 + 49 + 500 + 90
>                           = ₹20,441
> ```

> **WORKED EXAMPLE — DPD 90, Full NPA (₹50,000 loan, 0 EMIs paid, Band B)**
> ```
> Sanctioned Principal      = ₹50,000
> Overdue Interest (3 mo.)  = 50,000 × 2.5% × 3        = ₹3,750
> Bounce Charges (3×3)      = 9 × ₹400                  = ₹3,600
> GST on Bounce             = 3,600 × 18%               = ₹648
> Late Penalty (DPD 1–30)   = 50,000 × 0.000667 × 30   = ₹1,000
> GST on Penalty            = 1,000 × 18%               = ₹180
> Penal Int. (DPD 31–60)    = 53,750 × 3% / 30 × 30    = ₹1,613
> GST on Penal (31–60)      = 1,613 × 18%               = ₹290
> Penal Int. (DPD 61–90)    = 55,363 × 5% / 30 × 30    = ₹2,768
> GST on Penal (61–90)      = 2,768 × 18%               = ₹498
> Legal / Notice Charges    = ₹1,000
> GST on Legal              = ₹180
> ────────────────────────────────────────────────────────────
> Total NPA Outstanding     = ₹65,527
> (Principal ₹50,000 + All charges ₹15,527)
> ```

---

## 5. Cumulative Outstanding Balance Formula (Any DPD)

```
Total Outstanding at DPD d  =

  Principal Outstanding (OP)
+ Overdue Regular Interest
+ Σ Bounce Charges (× no. of bounces) × 1.18
+ Late Penalty (DPD 1–30): OP_overdue × 0.000667 × min(d,30) × 1.18
+ Penal Interest (DPD 31–60): OP_total × 3%/30 × max(0, min(d,60)−30) × 1.18
+ Penal Interest (DPD 61–90): OP_total × 5%/30 × max(0, min(d,90)−60) × 1.18
+ Penal Interest (DPD 90+): OP_total × 5%/30 × max(0, d−90) × 1.18
+ Legal Charges (if d ≥ 52) × 1.18

Where OP_total is updated each month to include accrued penal interest.
```

---

## 6. Loan Restructuring / Rescheduling

Offered as a last resort before NPA to customers who demonstrate willingness to pay but face genuine financial hardship. Requires credit officer approval.

### 6.1 Eligibility Criteria

```
  • DPD between 30 and 89 (SMA-1 or SMA-2)
  • Customer must have paid at least 1 EMI previously (not first default)
  • Customer requests restructuring in writing / app
  • No prior restructuring on this loan
  • No fraud flags on account
```

### 6.2 Restructuring Types

| Type | Description | When Used |
|---|---|---|
| Tenure Extension | Extend remaining tenor; EMI reduced | Income temporarily reduced |
| EMI Holiday | 1–2 month moratorium; no EMI charged (interest still accrues) | Short-term cash crunch |
| Step-up EMI | Lower EMI now, higher later | Borrower expects income to recover |
| Interest Waiver | Partial waiver of penal interest (not principal/regular interest) | Goodwill gesture; court order |

### 6.3 Restructuring Charge Calculation

```
Restructuring Fee  =  Outstanding Principal  ×  1.5%   (TLB policy)
GST                =  Fee  ×  18%
Total Charge       =  Fee + GST

Added to outstanding and spread across remaining EMIs.
```

### 6.4 Revised EMI After Tenure Extension

```
Inputs:
  OP   = Outstanding Principal at restructuring date
  OD   = All overdue amounts (interest + penalty — waived portion excluded)
  n_new = New tenure in months (remaining + extension)
  r    = Same monthly ROI as original loan

New Principal Base  =  OP + OD (non-waived)  +  Restructuring Charge
Revised EMI         =  New Principal Base × r × (1+r)^n_new / ((1+r)^n_new − 1)
```

> **WORKED EXAMPLE — Tenure Extension at DPD 45 (₹50,000 loan, Band B, 6m original)**
> ```
> Outstanding Principal (after 0 EMIs paid, DPD 45) = ₹50,000
> Overdue Charges (from DPD 45 example above)        = ₹2,283  (non-legal)
> Restructuring Fee (1.5%)                            = 50,000 × 1.5% = ₹750
> GST on Fee                                          = ₹135
> New Principal Base                                  = 50,000 + 2,283 + 750 + 135
>                                                     = ₹53,168
>
> Extension granted: 3 months (original 6m remaining → now 9m total)
> ROI remains 2.5% / month
>
> Revised EMI = 53,168 × 0.025 × (1.025)^9 / ((1.025)^9 − 1)
>             = 53,168 × 0.025 × 1.2489 / 0.2489
>             = 53,168 × 0.12546
>             ≈ ₹6,671 / month
>
> Original EMI was ₹9,079 → customer saves ₹2,408/month during extension.
> Total additional interest due to extension ≈ ₹6,671×9 − 53,168 = ₹7,071
> ```

---

## 7. One-Time Settlement (OTS) Calculations

OTS is offered when full recovery is unlikely and a negotiated lump-sum is more practical than prolonged legal action.

### 7.1 OTS Eligibility

```
  • NPA for ≥ 90 days (DPD 90+)
  • No active fraud proceedings
  • Borrower approaches for settlement OR field agent recommends
  • Credit officer + management approval required for waiver > 20% of outstanding
```

### 7.2 OTS Calculation Framework

```
OTS Offer Amount  =  Principal Outstanding (OP)
                  +  Regular Interest (partial — negotiated %)
                  −  Waiver on Penal Interest
                  −  Waiver on Legal Charges
                  ±  Negotiated adjustment

Standard OTS Slabs (TLB policy):

  DPD 90–180:
    Settle at  OP + 50% of accrued regular interest
    Waive:     100% penal interest + 100% legal charges

  DPD 181–365:
    Settle at  OP + 25% of accrued regular interest
    Waive:     100% penal interest + 100% legal charges

  DPD 365+:
    Settle at  OP only (principal recovery)
    Waive:     100% of all interest + charges

  Loss Asset (written off):
    Settle at  50%–75% of OP
    (Any recovery boosts P&L as write-back)
```

### 7.3 OTS Settlement Charges

```
OTS Processing Fee  =  OTS Amount  ×  1%
GST                 =  OTS Fee     ×  18%

Final OTS Payment   =  OTS Amount  +  OTS Fee  +  GST
```

### 7.4 Write-Back Accounting on OTS

```
On OTS payment received:

  Dr  Bank / Cash                   =  OTS Amount Received
  Dr  Provision for NPA             =  Provisioned Amount
  Cr  Loan Account (Borrower)       =  Total Outstanding (Full)
  Cr  Income — Bad Debt Recovery    =  OTS Amount − OP  (if OP > OTS, debit loss)
  Cr  Income — Provision Write-back =  Provisioned Amount
```

> **WORKED EXAMPLE — OTS at DPD 120 (₹50,000 loan, 0 EMIs paid, Band B)**
> ```
> Principal Outstanding     = ₹50,000
> Accrued Regular Interest  = 50,000 × 2.5% × 4 months = ₹5,000
> Penal Interest (total)    = ₹4,381   (from DPD 90 example + 30 more days)
> Legal Charges             = ₹1,000
> Total Ledger Outstanding  = ₹60,381
>
> OTS Offer (DPD 90–180 slab):
>   Principal               = ₹50,000
>   50% of Regular Interest = ₹2,500
>   Penal Waiver            = (₹4,381) — fully waived
>   Legal Waiver            = (₹1,000) — fully waived
>   ─────────────────────────────────────
>   OTS Base Amount         = ₹52,500
>   OTS Processing Fee (1%) = ₹525
>   GST on Fee              = ₹95
>   Final OTS Payment       = ₹53,120
>
> Recovery Rate             = 53,120 / 60,381 = 88%
> Waiver Amount             = ₹7,261
> ```

---

## 8. NPA Provisioning Norms (RBI — NBFC)

Provisioning is a mandatory accounting entry where the NBFC sets aside funds against expected credit losses.

### 8.1 Provisioning Rates

| Asset Category | DPD / NPA Age | Secured Loans | Unsecured Loans | TLB (all unsecured) |
|---|---|---|---|---|
| Standard Asset | 0 DPD | 0.25% – 0.40% | 0.25% – 0.40% | 0.40% of portfolio |
| Sub-Standard | NPA < 12 months | 15% | 25% | **25%** |
| Doubtful-1 | NPA 12–24 months | 25% + 100% unsecured | 100% | **100%** |
| Doubtful-2 | NPA 24–36 months | 40% + 100% unsecured | 100% | **100%** |
| Doubtful-3 | NPA > 36 months | 100% | 100% | **100%** |
| Loss Asset | Written off | 100% | 100% | **100%** |

> All TLB loans are **unsecured personal loans**. Provisioning follows the unsecured column.

### 8.2 Provisioning Calculation

```
Provision Amount  =  Net Outstanding Principal  ×  Provisioning Rate

Net Outstanding   =  Gross Outstanding  −  Any Security / Guarantee (if any)
                  (for TLB unsecured loans: Net Outstanding = Gross Outstanding)

Provision Journal Entry:
  Dr  Provision for Loan Losses (P&L)   =  Provision Amount
  Cr  Provision for NPA (Balance Sheet) =  Provision Amount
```

### 8.3 Provision Coverage Ratio (PCR)

```
PCR  =  (Total Provisions Held / Total Gross NPA)  ×  100

Healthy PCR for micro-lending NBFCs:  ≥ 70%
RBI expectation for unsecured NBFCs:  ≥ 60%
```

> **WORKED EXAMPLE — Provisioning (₹50,000 loan, DPD 95 = NPA Sub-Standard)**
> ```
> Gross Outstanding       = ₹65,527  (from DPD 90 example)
> Provisioning Rate       = 25%  (unsecured sub-standard)
> Provision Amount        = 65,527 × 25% = ₹16,382
>
> P&L Impact:
>   Dr Provision for Loan Losses  ₹16,382
>   Cr Provision for NPA          ₹16,382
> ```

---

## 9. Write-Off Calculations

A write-off removes the loan from the active balance sheet. Recovery is still pursued; any recovery is booked as income.

### 9.1 Write-Off Criteria (TLB policy)

```
  • NPA for > 365 days (Doubtful-1 and above)
  • OR legal proceedings closed without recovery
  • OR OTS failed and no further recovery expected
  • Requires management approval + Board ratification quarterly
```

### 9.2 Write-Off Accounting Entry

```
On Write-Off:
  Dr  Provision for NPA             =  Provision Amount (already held)
  Dr  Write-Off Loss (P&L)          =  Net Outstanding − Provision (if under-provisioned)
  Cr  Loan Account (Borrower)       =  Gross Outstanding

Post Write-Off Recovery (if any amount collected later):
  Dr  Bank / Cash                   =  Amount Recovered
  Cr  Bad Debt Recovery (P&L)       =  Amount Recovered
```

### 9.3 Net Write-Off Impact

```
Net Write-Off Loss  =  Gross Outstanding  −  Provision Already Held  −  OTS / Recovery Received

Example:
  Gross Outstanding   = ₹65,527
  Provision Held      = ₹16,382  (25%)
  OTS Recovery        = ₹53,120
  Net P&L Loss        = 65,527 − 16,382 − 53,120 = −₹3,975  (net gain)
```

---

## 10. Collection Performance Metrics

### 10.1 Collection Efficiency Ratio (CER)

```
CER  =  (Amount Collected in Period / Amount Due in Period)  ×  100

Amount Due   =  All EMIs scheduled for the period (including overdue from prior periods)
Amount Collected = All payments received (EMIs + penalty + legal charges)

Target CER for TLB:  ≥ 95% (current portfolio)
                      ≥ 75% (delinquent portfolio)
```

> **Example:**
> ```
> EMIs due in June       = ₹15,00,000
> Collected in June      = ₹14,25,000
> CER                    = 14,25,000 / 15,00,000 × 100 = 95%
> ```

### 10.2 Roll Rate Analysis

Roll rate measures the percentage of accounts that move (roll) from one DPD bucket to the next worse bucket in a given month.

```
Roll Rate (bucket X → bucket Y)  =
  (Accounts in bucket Y this month that were in bucket X last month)
  ─────────────────────────────────────────────────────────────────  × 100
  (Total accounts in bucket X last month)
```

| Transition | Healthy Target | Warning Threshold |
|---|---|---|
| Current → SMA-0 | < 3% | > 5% |
| SMA-0 → SMA-1 | < 20% | > 35% |
| SMA-1 → SMA-2 | < 25% | > 40% |
| SMA-2 → NPA | < 30% | > 50% |
| NPA → Write-off | < 40% | > 60% |

### 10.3 Recovery Rate

```
Recovery Rate  =  (Amount Recovered from NPA Accounts / Gross NPA Outstanding)  ×  100

Includes: OTS settlements + legal recoveries + voluntary payments post-NPA

Target for TLB micro-lending:  ≥ 40% of Gross NPA
```

### 10.4 Gross NPA Ratio

```
Gross NPA Ratio  =  (Gross NPA Outstanding / Gross Loan Portfolio)  ×  100

Gross NPA Outstanding  =  All accounts with DPD > 90, at book value
Gross Loan Portfolio   =  Total outstanding principal across all active loans

RBI benchmark for NBFC-MFI:  < 5%
TLB target:                   < 3%
```

### 10.5 Net NPA Ratio

```
Net NPA Ratio  =  (Gross NPA − Provisions Held) / (Gross Loan Portfolio − Provisions)  ×  100

TLB target:  < 1.5%
```

### 10.6 Cost of Collection

```
Cost of Collection (per loan)  =
  (Agent Salary + Tele-calling Costs + Field Visit Costs + Legal Costs)
  ─────────────────────────────────────────────────────────────────────
  Number of Delinquent Loans Managed

Cost of Collection Ratio  =
  Total Collection Cost / Total Amount Recovered  ×  100

TLB target:  < 15% of amount recovered
```

### 10.7 Portfolio at Risk (PAR)

```
PAR (X days)  =  Outstanding balance of all loans with DPD > X
                 ────────────────────────────────────────────  × 100
                 Total Outstanding Loan Portfolio

Common thresholds:
  PAR-30   (DPD > 30):  TLB target < 8%
  PAR-60   (DPD > 60):  TLB target < 5%
  PAR-90   (DPD > 90):  TLB target < 3%  (= Gross NPA Ratio)
```

---

## 11. Notification & Escalation Schedule

| Day | Trigger | Channel | Message Type | Charge Applied |
|---|---|---|---|---|
| Due Date | Auto-debit triggered | System | — | — |
| DPD 1 | Auto-debit failed | SMS + WA | Soft reminder + payment link | Bounce ₹472 |
| DPD 2 | Retry #2 | SMS + Push | Urgent reminder | Bounce ₹472 (if failed) |
| DPD 3 | Retry #3 | SMS + WA + Push | Final retry alert | Bounce ₹472 (if failed) |
| DPD 5 | No payment | WhatsApp | Payment link + support contact | Penalty accruing |
| DPD 8 | Tele-call queue | Call | Agent outreach | Penalty accruing |
| DPD 10 | SMS | SMS | "Avoid credit score impact" | Penalty accruing |
| DPD 15 | Supervisor review | Internal | Supervisor flag | Penalty accruing |
| DPD 20 | WA message | WhatsApp | Structured repayment plan offered | Penalty accruing |
| DPD 25 | Pre-escalation notice | SMS + WA | "Account may be escalated" | Penalty accruing |
| DPD 30 | Penal rate escalation | System | — | Penal 3%/mo starts |
| DPD 31 | Field agent assigned | Internal | — | Field visit charge |
| DPD 45 | Legal notice drafted | Internal | — | Legal prep charges |
| DPD 52 | Legal notice dispatched | Regd. Post + WA | Legal demand notice | ₹500 legal charge |
| DPD 60 | SMA-1 report | RBI system | — | — |
| DPD 61 | Penal rate escalation | System | — | Penal 5%/mo starts |
| DPD 75 | Final demand + cure window | Legal + WA | 15-day cure notice | — |
| DPD 89 | Pre-NPA alert | Internal | Credit officer alert | — |
| DPD 90 | NPA classification | System + CIBIL | — | Provisioning created |

---

## 12. Complete DPD Charge Accumulation Table

*(Based on ₹50,000 loan, Band B, 2.5%/month, 0 EMIs paid — worst case)*

| DPD | Principal OS | Accrued Interest | Bounce Charges+GST | Late Penalty+GST | Penal Interest+GST | Legal+GST | Total Outstanding |
|---|---|---|---|---|---|---|---|
| 0 | ₹50,000 | ₹0 | ₹0 | ₹0 | ₹0 | ₹0 | ₹50,000 |
| 1 | ₹50,000 | ₹42 | ₹472 | ₹0 | ₹0 | ₹0 | ₹50,514 |
| 7 | ₹50,000 | ₹292 | ₹1,416 | ₹0 | ₹0 | ₹0 | ₹51,708 |
| 15 | ₹50,000 | ₹625 | ₹1,416 | ₹107 | ₹0 | ₹0 | ₹52,148 |
| 30 | ₹50,000 | ₹1,250 | ₹1,416 | ₹1,180 | ₹0 | ₹0 | ₹53,846 |
| 45 | ₹50,000 | ₹1,875 | ₹1,416 | ₹1,180 | ₹321 | ₹590 | ₹55,382 |
| 60 | ₹50,000 | ₹2,500 | ₹1,416 | ₹1,180 | ₹1,903 | ₹590 | ₹57,589 |
| 75 | ₹50,000 | ₹3,125 | ₹1,416 | ₹1,180 | ₹3,758 | ₹1,180 | ₹60,659 |
| 90 | ₹50,000 | ₹3,750 | ₹1,416 | ₹1,180 | ₹5,526 | ₹1,180 | ₹63,052 |
| 120 | ₹50,000 | ₹5,000 | ₹1,416 | ₹1,180 | ₹8,850 | ₹1,180 | ₹67,626 |
| 180 | ₹50,000 | ₹7,500 | ₹1,416 | ₹1,180 | ₹17,700 | ₹1,770 | ₹79,566 |
| 365 | ₹50,000 | ₹15,208 | ₹1,416 | ₹1,180 | ₹42,480 | ₹2,360 | ₹1,12,644 |

> Values are illustrative. Actual figures depend on partial payments received, retry success, and exact dates.

---

## 13. Summary — Key Formulae Reference

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 LATE PENALTY (DPD 1–29):
   Penalty  =  Overdue Amount × 0.000667 × Days Overdue
   Total    =  Penalty × 1.18  (incl. GST)

 PENAL INTEREST (DPD 30–60):
   Monthly  =  Total Overdue Outstanding × 3%
   Total    =  Monthly Penal × 1.18

 PENAL INTEREST (DPD 61+):
   Monthly  =  Total Overdue Outstanding × 5%
   Total    =  Monthly Penal × 1.18

 BOUNCE CHARGE:
   Per event (eNACH) =  ₹400 + ₹72 GST = ₹472
   Per event (UPI)   =  ₹300 + ₹54 GST = ₹354

 CURE AMOUNT:
   = Overdue EMIs + Penalty+GST + Bounce+GST + Penal+GST + Legal+GST

 RESTRUCTURING EMI:
   New Base  =  OP + Overdue + Restructuring Fee (1.5% + GST)
   New EMI   =  New Base × r × (1+r)^n_new / ((1+r)^n_new − 1)

 OTS (DPD 90–180):
   =  Principal + 50% Regular Interest + 1% OTS Fee + GST

 PROVISIONING:
   Sub-Standard (NPA < 12m):  OS × 25%
   Doubtful (NPA ≥ 12m):      OS × 100%

 GROSS NPA RATIO:
   =  Gross NPA / Gross Portfolio × 100  [target < 3%]

 COLLECTION EFFICIENCY:
   =  Collected / Due × 100  [target ≥ 95%]

 PAR-90:
   =  OS balance (DPD>90) / Total Portfolio × 100  [target < 3%]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

*True Loan Bazaar (TLB) | Collection & Delinquency Management v1.0 | Confidential*
*Compliant with RBI NPA Circular, RBI Digital Lending Guidelines 2022, SARFAESI Act, CGST Act 2017*
