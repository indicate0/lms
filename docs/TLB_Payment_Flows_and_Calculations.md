# Payment Flows & Calculations
## True Loan Bazaar (TLB) — Micro-Lending Platform

**All Payment Types · Modes · Waterfall Logic · Calculations · Accounting Entries**

> Covers: EMI · Bullet · Overdue · Part-Prepayment · Foreclosure · Refund (Cooling-off) · Disbursal · eNACH/UPI · OTS · DSA Commission · GST Remittance
> Compliant with RBI Digital Lending Guidelines 2022 · RBI Fair Practice Code · NPCI · CGST Act 2017

---

## 1. Payment Types Overview

| # | Payment Type | Direction | Trigger | Mode |
|---|---|---|---|---|
| 1 | EMI (Scheduled) | Customer → NBFC | Auto-debit on due date | eNACH / UPI Autopay |
| 2 | EMI (Manual) | Customer → NBFC | Customer-initiated | UPI / NEFT / IMPS / Payment Link |
| 3 | Bullet Repayment | Customer → NBFC | Maturity date (Payday) | eNACH / UPI / Manual |
| 4 | Overdue Payment | Customer → NBFC | Post DPD, with charges | UPI / NEFT / Agent collection |
| 5 | Part-Prepayment | Customer → NBFC | Customer request | UPI / NEFT |
| 6 | Foreclosure | Customer → NBFC | Customer request | NEFT / IMPS |
| 7 | Cooling-off Refund | NBFC → Customer | Customer exits within 3 days | IMPS / UPI |
| 8 | Loan Disbursal | NBFC → Customer | Post sanction & mandate | IMPS / UPI |
| 9 | OTS Settlement | Customer → NBFC | Negotiated post-NPA | NEFT / DD / Cash |
| 10 | DSA Commission Payout | NBFC → Agent | Post disbursal | NEFT / IMPS |
| 11 | GST Remittance | NBFC → Govt. | Monthly / Quarterly | Govt. portal |
| 12 | NACH Bounce Recovery | Customer → NBFC | Bounce charge recovery | Manual / next debit |

---

## 2. Payment Modes & Charges

| Mode | Transaction Limit | Charges (NBFC bears) | Settlement Time | Availability |
|---|---|---|---|---|
| IMPS | Up to ₹5,00,000 | ₹5–₹15 + GST per txn | Real-time (24×7) | Disbursal, refund, payout |
| UPI | Up to ₹1,00,000 (₹2L for verified) | Free | Real-time (24×7) | All customer payments |
| UPI Autopay | Up to ₹1,00,000 / debit | Free | Real-time on due date | Auto-EMI, auto-bullet |
| eNACH | Up to ₹10,00,000 / debit | ₹0.50–₹1.50 per txn | T+1 business day | Auto-EMI, auto-bullet |
| NEFT | No limit | ₹2–₹25 per txn | 30-min batches (Mon–Sat) | Foreclosure, OTS, large txns |
| RTGS | Min ₹2,00,000 | ₹25–₹50 per txn | Real-time (business hours) | Bulk disbursals, large OTS |
| Payment Link | Up to ₹1,00,000 | UPI/card processing fee | Real-time | Overdue recovery, manual EMI |

---

## 3. Payment Application Waterfall (Priority of Appropriation)

When any payment is received, the LMS applies it in the following priority order (RBI Fair Practice Code aligned):

```
Payment Received (any amount)
         │
         ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  WATERFALL ORDER (highest priority first)                       │
  │                                                                 │
  │  1st  →  Legal / Court / Recovery Charges  (+ GST)             │
  │  2nd  →  Bounce / Dishonour Charges        (+ GST)             │
  │  3rd  →  Penal Interest (DPD 30+)          (+ GST)             │
  │  4th  →  Late Payment Penalty (DPD 1–29)   (+ GST)             │
  │  5th  →  Overdue Regular Interest          (no GST)            │
  │  6th  →  Overdue Principal                 (no GST)            │
  │  7th  →  Current Period Interest           (no GST)            │
  │  8th  →  Current Period Principal          (no GST)            │
  │  9th  →  Future Principal (if excess)      → Prepayment rules  │
  └─────────────────────────────────────────────────────────────────┘
         │
         ▼
  Residual (if payment > total due) → Held as Advance / Refunded
```

### 3.1 Waterfall Calculation Formula

```
  Remaining  =  Payment Amount

  Step 1:  Applied to Legal Charges     =  min(Remaining, Legal+GST)
           Remaining  −=  Applied Amount

  Step 2:  Applied to Bounce Charges    =  min(Remaining, Bounce+GST)
           Remaining  −=  Applied Amount

  Step 3:  Applied to Penal Interest    =  min(Remaining, Penal+GST)
           Remaining  −=  Applied Amount

  Step 4:  Applied to Late Penalty      =  min(Remaining, Penalty+GST)
           Remaining  −=  Applied Amount

  Step 5:  Applied to Overdue Interest  =  min(Remaining, Overdue Interest)
           Remaining  −=  Applied Amount

  Step 6:  Applied to Overdue Principal =  min(Remaining, Overdue Principal)
           Remaining  −=  Applied Amount

  Step 7:  Applied to Current Interest  =  min(Remaining, Current Interest)
           Remaining  −=  Applied Amount

  Step 8:  Applied to Current Principal =  min(Remaining, Current Principal)
           Remaining  −=  Applied Amount

  Step 9:  Residual > 0  →  Hold as Advance Bucket (auto-apply to next EMI)
                         OR  Trigger prepayment rules (if customer opted)
```

> **WORKED EXAMPLE — Partial payment of ₹5,000 on DPD 45 account (₹50,000 loan, Band B)**
> ```
> Total Outstanding     = ₹20,441  (from Collection doc DPD-45 example)
> Payment Received      = ₹5,000
>
> Step 1: Legal charges     = ₹590     → Applied ₹590   | Remaining ₹4,410
> Step 2: Bounce charges    = ₹944     → Applied ₹944   | Remaining ₹3,466
> Step 3: Penal interest    = ₹321     → Applied ₹321   | Remaining ₹3,145
> Step 4: Late penalty      = ₹428     → Applied ₹428   | Remaining ₹2,717
> Step 5: Overdue interest  = ₹1,875   → Applied ₹1,875 | Remaining ₹842
> Step 6: Overdue principal = ₹18,158  → Applied ₹842   | Remaining ₹0
>
> Outstanding after payment = ₹20,441 − ₹5,000 = ₹15,441
> Principal still owed      = ₹18,158 − ₹842   = ₹17,316
> All charges cleared except ₹15,441 − ₹17,316 ... charges remain in queue
> ```

---

## 4. Type 1 — Scheduled EMI Payment (Auto-Debit)

### 4.1 Auto-Debit Flow

```
  T-3 days before due date:
    Notification Service → SMS + WhatsApp: "EMI of ₹X due on [date]"

  Due Date (D):
    LMS triggers Payment Service → eNACH / UPI Autopay mandate
         │
         ├── SUCCESS (funds available)
         │       Payment Service receives webhook: status = SETTLED
         │       LMS: EMI record → PAID
         │       Interest component booked as income
         │       Principal reduces outstanding balance
         │       Notification: "EMI paid. Receipt #XXXX"
         │
         └── FAILURE (insufficient funds)
                 Bounce charge applied to loan account
                 DPD clock starts → Day 1
                 Retry on D+1 and D+2
```

### 4.2 EMI Breakup Calculation

```
  EMI  =  P × r × (1+r)^n / ((1+r)^n − 1)

  For EMI number k (1-indexed):
    Opening Balance (k)   =  P×(1+r)^(k−1) − EMI×[(1+r)^(k−1)−1]/r
    Interest Component    =  Opening Balance (k)  ×  r
    Principal Component   =  EMI  −  Interest Component
    Closing Balance (k)   =  Opening Balance (k)  −  Principal Component
```

> **EMI Breakup Table — ₹50,000 @ 2.5%/month, 6 months, Band B**
> ```
> Month | Opening Bal  | EMI    | Interest | Principal | Closing Bal
> ──────────────────────────────────────────────────────────────────
>   1   | ₹50,000      | ₹9,079 | ₹1,250   | ₹7,829    | ₹42,171
>   2   | ₹42,171      | ₹9,079 | ₹1,054   | ₹8,025    | ₹34,146
>   3   | ₹34,146      | ₹9,079 | ₹854     | ₹8,226    | ₹25,920
>   4   | ₹25,920      | ₹9,079 | ₹648     | ₹8,431    | ₹17,489
>   5   | ₹17,489      | ₹9,079 | ₹437     | ₹8,642    | ₹8,847
>   6   | ₹8,847       | ₹9,068*| ₹221     | ₹8,847    | ₹0
>
>   *Last EMI adjusted for rounding difference
>   Total Interest = ₹4,464   |   Total Repaid = ₹54,464
> ```

### 4.3 EMI Payment Accounting Entry

```
  On EMI receipt:
    Dr  Bank / NACH Settlement A/c     =  EMI Amount (₹9,079)
    Cr  Loan Account (Borrower)        =  Principal Component (₹7,829)
    Cr  Interest Income                =  Interest Component (₹1,250)

  On last EMI (loan closure):
    Dr  Bank / NACH Settlement A/c     =  Final EMI (₹9,068)
    Cr  Loan Account (Borrower)        =  Final Principal (₹8,847)
    Cr  Interest Income                =  Final Interest (₹221)
    → Trigger NOC generation
```

### 4.4 Broken-Period Interest (First EMI)

If the loan is disbursed mid-month, the first EMI includes a broken-period interest component.

```
  Broken Period Days  =  Days from Disbursal Date to First EMI Date

  Broken Period Int.  =  Principal  ×  (Monthly ROI / 30)  ×  Broken Period Days

  First EMI Total     =  Regular EMI  +  Broken Period Interest
```

> **WORKED EXAMPLE — Disbursal on 10th, first EMI on 1st of next month**
> ```
> Broken Period Days    = 21 days  (10th to 1st of next month)
> Principal             = ₹50,000
> Monthly ROI           = 2.5%
> Broken Period Int.    = 50,000 × (2.5%/30) × 21 = ₹875
> First EMI             = ₹9,079 + ₹875 = ₹9,954
> Subsequent EMIs       = ₹9,079 (regular schedule)
> ```

---

## 5. Type 2 — Bullet Repayment (Payday Loan)

### 5.1 Bullet Payment Flow

```
  Disbursed Amount → Customer Bank Account

  On Maturity Date:
    LMS triggers single auto-debit for FULL repayable amount
         │
         ├── SUCCESS → Loan CLOSED, NOC generated
         └── FAILURE → Overdue starts (daily penal rate applies)
                       (See Section 8 — Overdue Payment)
```

### 5.2 Bullet Amount Calculation

```
  Total Interest    =  Principal  ×  Daily Rate  ×  Tenor (days)
  Total Repayable   =  Principal  +  Total Interest

  Daily Rate (Band B)  =  0.12% per day
```

> **WORKED EXAMPLE — ₹10,000, 21 days, Band B**
> ```
> Principal           = ₹10,000
> Daily Rate          = 0.12% = 0.0012
> Tenor               = 21 days
> Total Interest      = 10,000 × 0.0012 × 21 = ₹252
> Total Repayable     = ₹10,252
>
> Accounting on receipt:
>   Dr  Bank A/c                ₹10,252
>   Cr  Loan Account (Borrower) ₹10,000
>   Cr  Interest Income             ₹252
> ```

---

## 6. Type 3 — Manual EMI / Payment Link

### 6.1 Manual Payment Flow

```
  Customer initiates payment:
    Via App → Pay Now button → Redirects to UPI / Card / Net Banking
    Via WhatsApp → Payment link sent by agent
    Via NEFT → Customer transfers to NBFC's virtual account number (VAN)

  Payment Gateway / VAN:
    Receives funds → Sends webhook to Payment Service
    Payment Service → Notifies LMS with: amount, UTR number, timestamp

  LMS Processing:
    Match payment to loan account by VAN or Loan ID
    Apply waterfall logic (Section 3)
    Mark EMI as PAID or PARTIALLY PAID
    Generate receipt (PDF) → Send via WhatsApp + SMS
```

### 6.2 Virtual Account Number (VAN) Mapping

```
  Each loan account is assigned a unique VAN at disbursal:
    VAN  =  NBFC_PREFIX + LOAN_ID + CHECK_DIGIT

  Any NEFT/IMPS to this VAN is auto-matched to the loan account.
  Amount mismatch:  → Held in suspense account → Manual reconciliation within 24h
```

---

## 7. Type 4 — Overdue Payment (DPD 1+)

### 7.1 Overdue Amount Calculation

```
  Total Amount to Clear  =

    Overdue EMI(s)                                          [A]
  + Bounce Charges × no. of bounces × 1.18 (GST)          [B]
  + Late Payment Penalty × 1.18 (if DPD ≤ 29)             [C]
  + Penal Interest (3%/mo, DPD 30–60) × 1.18              [D]
  + Penal Interest (5%/mo, DPD 61+) × 1.18                [E]
  + Legal Charges × 1.18 (if DPD ≥ 52)                    [F]

  Total Cure Amount  =  A + B + C + D + E + F
```

### 7.2 Overdue Interest Accrual (Daily)

```
  Daily Interest on Overdue EMI  =  Overdue Amount × (Monthly ROI / 30)

  Daily Penal (DPD 1–29)    =  Overdue Amount × (2% / 30)   = 0.000667 per day
  Daily Penal (DPD 30–60)   =  Total OS       × (3% / 30)   = 0.001000 per day
  Daily Penal (DPD 61+)     =  Total OS       × (5% / 30)   = 0.001667 per day

  All penal amounts × 1.18 for GST.
```

> **WORKED EXAMPLE — Overdue payment on DPD 38 (₹9,079 EMI, Band B)**
> ```
> Overdue EMI               = ₹9,079
> Bounce Charges (2×eNACH)  = 2 × ₹472 = ₹944
> Late Penalty (DPD 1–30)   = 9,079 × 0.000667 × 30 = ₹182 × 1.18 = ₹215
> Penal Int. (DPD 31–38)    = 9,079 × 0.001 × 8     = ₹73  × 1.18 = ₹86
> ──────────────────────────────────────────────────────────
> Total Overdue Amount      = 9,079 + 944 + 215 + 86 = ₹10,324
>
> Accounting on receipt:
>   Dr  Bank A/c                         ₹10,324
>   Cr  Bounce Charge Income                 ₹800  (net of GST ₹144)
>   Cr  GST Payable — Bounce                 ₹144
>   Cr  Late Penalty Income                  ₹182  (net of GST ₹33)
>   Cr  GST Payable — Penalty                ₹33
>   Cr  Penal Interest Income                ₹73   (net of GST ₹13)
>   Cr  GST Payable — Penal                  ₹13
>   Cr  Interest Income                      ₹227  (interest part of overdue EMI)
>   Cr  Loan Account (Borrower)           ₹8,852  (principal part of overdue EMI)
> ```

---

## 8. Type 5 — Part-Prepayment

### 8.1 Eligibility & Rules

```
  • Minimum 3 EMIs must have been paid
  • Minimum prepayment amount = 1 full EMI
  • Maximum 2 part-prepayments per loan tenure
  • Not allowed on Payday / Bullet loans
  • Must be initiated by customer (not auto-triggered)
```

### 8.2 Part-Prepayment Charge Calculation

```
  Prepayment Charge   =  Prepayment Amount  ×  Rate
  GST on Charge       =  Prepayment Charge  ×  18%
  Total Charge        =  Prepayment Charge  +  GST

  Rates (TLB policy):
    Band A: 2% of prepayment amount
    Band B: 2.5% of prepayment amount
    Band C: 3% of prepayment amount

  Net Principal Reduction  =  Prepayment Amount  −  Prepayment Charge  −  GST
```

### 8.3 Revised Schedule After Prepayment

```
  After prepayment, LMS recalculates:

  New Outstanding Principal  =  OP (before prepayment)  −  Net Principal Reduction

  OPTION A — Reduce Tenure (same EMI):
    Solve for n_new:  New OS  =  EMI × [1 − (1+r)^−n_new] / r
    n_new  =  −ln(1 − New OS × r / EMI) / ln(1+r)

  OPTION B — Reduce EMI (same tenure):
    New EMI  =  New OS × r × (1+r)^n_remaining / ((1+r)^n_remaining − 1)
    Where n_remaining = original remaining tenure
```

> **WORKED EXAMPLE — Part-Prepayment of ₹15,000 after 3 EMIs (₹50,000 loan, Band B, 6m)**
> ```
> Outstanding after 3 EMIs   = ₹25,920  (from amortisation table)
> Prepayment Amount          = ₹15,000
> Prepayment Rate (Band B)   = 2.5%
> Prepayment Charge          = 15,000 × 2.5% = ₹375
> GST on Charge              = 375 × 18%     = ₹68
> Total Paid                 = ₹15,000 + ₹375 + ₹68 = ₹15,443
> Net Principal Reduction    = ₹15,000 − ₹375 − ₹68  = ₹14,557
> New Outstanding            = ₹25,920 − ₹14,557      = ₹11,363
>
> OPTION B — Revised EMI (3 months remaining, 2.5%/month):
>   New EMI = 11,363 × 0.025 × (1.025)^3 / ((1.025)^3 − 1)
>           = 11,363 × 0.025 × 1.0769 / 0.0769
>           ≈ ₹3,906 / month
>
> Original EMI was ₹9,079 → customer saves ₹5,173/month for 3 months.
>
> Accounting:
>   Dr  Bank A/c                    ₹15,443
>   Cr  Loan Account (Borrower)    ₹14,557   (principal reduction)
>   Cr  Prepayment Fee Income          ₹375
>   Cr  GST Payable                     ₹68
>   → Trigger schedule recalculation in LMS
> ```

---

## 9. Type 6 — Foreclosure (Full Early Closure)

### 9.1 Foreclosure Payment Flow

```
  Customer requests foreclosure (App / Branch)
         │
         ▼
  LMS computes Foreclosure Statement:
    Outstanding Principal (OP)    today
    + Accrued Interest (till today)
    + Foreclosure Charge + GST
    + Any overdue / penalty (if applicable)
         │
         ▼
  Statement sent to customer (valid for 3 days — rate can change after)
         │
         ▼
  Customer pays via NEFT/IMPS (full amount, single transaction preferred)
         │
         ▼
  LMS confirms receipt → Loan CLOSED
  NOC generated (PDF) → Delivered via WhatsApp + Email within 24h
  CIBIL / Equifax update → Loan closed, outstanding = ₹0
```

### 9.2 Foreclosure Amount Calculation

```
  Outstanding Principal (after k EMIs paid):
    OP  =  P × (1+r)^k  −  EMI × [(1+r)^k − 1] / r

  Accrued Interest (mid-month, d days into current EMI cycle):
    Accrued  =  OP × (r / 30) × d

  Foreclosure Charge  =  OP × FC Rate
  GST on FC Charge    =  Foreclosure Charge × 18%

  FC Rates (TLB policy):
    Band A: 2%   |   Band B: 3%   |   Band C: 4%
    Surcharge +1% if closed within first 3 months of disbursal

  Total Foreclosure Amount  =  OP  +  Accrued Interest  +  FC Charge  +  GST
```

> **WORKED EXAMPLE — Foreclosure on Day 15 of Month 4 (₹50,000, Band B, 6m)**
> ```
> EMIs paid so far           = 3
> Outstanding Principal (OP) = ₹25,920
> Days into 4th EMI cycle    = 15 days
> Accrued Interest           = 25,920 × (2.5%/30) × 15 = ₹324
> Foreclosure Charge (3%)    = 25,920 × 3% = ₹778
> GST on FC Charge           = 778 × 18%   = ₹140
> ────────────────────────────────────────────────
> Total Foreclosure Amount   = 25,920 + 324 + 778 + 140 = ₹27,162
>
> Interest Saved (EMIs 4,5,6 not paid):
>   Remaining interest        = ₹648 + ₹437 + ₹221 = ₹1,306
>   FC charge paid            = ₹918
>   Net saving to customer    = ₹1,306 − ₹918 = ₹388
>
> Accounting:
>   Dr  Bank A/c                    ₹27,162
>   Cr  Loan Account (Borrower)    ₹25,920  (principal closure)
>   Cr  Interest Income                ₹324  (accrued interest)
>   Cr  Foreclosure Fee Income         ₹778
>   Cr  GST Payable                    ₹140
> ```

---

## 10. Type 7 — Cooling-off Period Refund (Exit / Cancellation)

### 10.1 Cooling-off Rules (RBI DLG 2022)

```
  Cooling-off Period  =  3 business days from disbursal date

  Customer can exit the loan during this window:
    → No foreclosure charge
    → No prepayment penalty
    → Only proportionate interest for days loan was held
    → All deducted fees (PF, insurance, NACH) are NON-refundable
       (they represent services already rendered / contracted)
```

### 10.2 Refund Calculation

```
  Refund Amount  =  Principal Disbursed  (sanctioned amount — charges)
                  − Proportionate Interest

  Proportionate Interest  =  Principal  ×  (Monthly ROI / 30)  ×  Days Held

  Days Held  =  Date of Refund Request  −  Disbursal Date

  Net Refund  =  Net Disbursed Amount  −  Proportionate Interest
```

> **WORKED EXAMPLE — Exit on Day 2 (₹50,000 loan, Band B, 2.5%/month)**
> ```
> Net Disbursed Amount     = ₹47,363   (principal received by customer)
> Days Held                = 2 days
> Proportionate Interest   = 50,000 × (2.5%/30) × 2 = ₹83
>
> Refund to Customer       = ₹47,363 − ₹83 = ₹47,280
>
> Non-refundable charges:
>   Processing Fee + GST   = ₹1,770   (cost of underwriting incurred)
>   Stamp Duty             = ₹100     (govt. levy, non-recoverable)
>   NACH Charge + GST      = ₹177     (mandate already registered)
>   Insurance + GST        = ₹590     (policy already issued)
>
> NBFC sends ₹47,280 via IMPS to customer's account within 24 hours.
>
> Accounting:
>   Dr  Loan Account (Borrower)     ₹50,000
>   Cr  Bank A/c (refund out)       ₹47,280
>   Cr  Interest Income                  ₹83  (2 days interest earned)
>   Cr  Income — Processing Fee      ₹1,500  (retained)
>   Cr  GST Payable — PF               ₹270
>   [Stamp, NACH, Insurance similarly retained]
> ```

---

## 11. Type 8 — Loan Disbursal (NBFC → Customer)

### 11.1 Disbursal Flow

```
  Loan Sanctioned + Mandate Registered
         │
         ▼
  LMS generates Disbursal Instruction:
    Beneficiary: Customer Bank A/c (verified via penny-drop)
    Amount:      Net Disbursed Amount
    Mode:        IMPS (real-time) or UPI
    Reference:   Loan ID + UTR
         │
         ▼
  Payment Service → Bank API (IMPS/UPI)
         │
         ├── SUCCESS (webhook: status = CREDITED)
         │       LMS: Loan status = ACTIVE
         │       Disbursal timestamp recorded
         │       SMS + WhatsApp: "₹X credited to your A/c XXXX"
         │
         └── FAILURE (invalid A/c / bank down)
                 Retry logic: 3 attempts (15-min intervals)
                 If all fail: Ops alert → Manual intervention
                 Loan status remains = MANDATE_REGISTERED (not ACTIVE)
```

### 11.2 Net Disbursed Amount Calculation

```
  Net Disbursed  =  Sanctioned Amount
                 −  Processing Fee  (PF Rate × Principal)
                 −  GST on PF       (PF × 18%)
                 −  Stamp Duty      (State rate; min ₹100)
                 −  NACH Charge     (₹150)
                 −  GST on NACH     (₹27)
                 −  Insurance       (opt-in; % of principal)
                 −  GST on Insur.   (Insurance × 18%)
```

### 11.3 Disbursal Accounting Entry

```
  Dr  Loan Account (Borrower)    =  Sanctioned Amount          (₹50,000)
  Cr  Bank A/c (NBFC Disbursal)  =  Net Disbursed              (₹47,363)
  Cr  Income — Processing Fee    =  PF (net of GST)            (₹1,500)
  Cr  GST Payable — PF           =  GST on PF                  (₹270)
  Cr  Stamp Duty Payable         =  Stamp Duty                 (₹100)
  Cr  Income — NACH Fee          =  NACH (net of GST)          (₹150)
  Cr  GST Payable — NACH         =  GST on NACH                (₹27)
  Cr  Insurance Premium Payable  =  Insurance (net of GST)     (₹500)
  Cr  GST Payable — Insurance    =  GST on Insurance           (₹90)
```

### 11.4 Penny-Drop Verification (Pre-Disbursal)

```
  Before first disbursal, NBFC verifies customer bank account:
    Send ₹1 to beneficiary A/c via IMPS
    Verify: Account exists + Name matches KYC name (fuzzy match ≥ 80%)
    If FAIL → Ask customer to re-enter account details

  Penny-drop cost: ₹0.50 – ₹2 per verification (borne by NBFC)
```

---

## 12. Type 9 — OTS Settlement Payment

### 12.1 OTS Payment Flow

```
  OTS Agreement finalised (credit officer + management approval)
         │
         ▼
  OTS Settlement Letter issued to customer:
    OTS Amount  =  Principal + partial interest + OTS fee + GST
    Valid for:  15 days (after which OTS may be revised)
         │
         ▼
  Customer pays via NEFT / DD / Banker's Cheque (cash discouraged for AML)
         │
         ▼
  Payment confirmed → Loan CLOSED (OTS basis)
  Waiver letter issued (documents charges waived)
  NOC issued (marked "Settled via OTS")
  CIBIL update: status = "Settled"  (NOT "Closed" — impacts score differently)
```

### 12.2 OTS Amount Calculation

```
  OTS Amount  =  Outstanding Principal (OP)
              +  Negotiated Interest  (% of total accrued regular interest)
              −  Penal Interest Waiver  (100% waived)
              −  Legal Charges Waiver  (100% waived)
              +  OTS Processing Fee  (OTS Base × 1%)
              +  GST on OTS Fee  (1% × 18%)

  DPD Slab          Interest Retained   Waiver on Penal & Legal
  DPD  90–180       50%                 100%
  DPD 181–365       25%                 100%
  DPD   365+        0%                  100%
  Written-off       0%                  100% (recover principal only)
```

> **WORKED EXAMPLE — OTS at DPD 120 (₹50,000 loan, Band B)**
> ```
> Outstanding Principal      = ₹50,000
> Accrued Regular Interest   = ₹5,000   (4 months × 2.5% × 50,000)
> Penal Interest Total       = ₹4,381   (DPD 30–120)
> Legal Charges              = ₹1,000
> Total Gross Outstanding    = ₹60,381
>
> OTS Terms (DPD 90–180):
>   Principal retained         = ₹50,000  (100%)
>   Interest retained (50%)    = ₹2,500
>   Penal waived               = (₹4,381)
>   Legal waived               = (₹1,000)
>   OTS Base                   = ₹52,500
>   OTS Processing Fee (1%)    = ₹525
>   GST on OTS Fee (18%)       = ₹95
>   ───────────────────────────────
>   Final OTS Payment          = ₹53,120
>
> Accounting:
>   Dr  Bank A/c                        ₹53,120
>   Dr  Provision for NPA (write-back) ₹16,382   (25% provision)
>   Dr  Penal Interest Receivable        ₹4,381   (waiver off-ledger)
>   Dr  Legal Charges Receivable         ₹1,000   (waiver off-ledger)
>   Cr  Loan Account (Borrower)        ₹60,381   (close full ledger)
>   Cr  Income — OTS Fee                   ₹525
>   Cr  GST Payable — OTS                   ₹95
>   Cr  Income — Provision Write-back  ₹16,382
>   Cr  Income — Interest Recovery      ₹2,500
> ```

---

## 13. Type 10 — DSA Commission Payout

### 13.1 Commission Payout Flow

```
  Loan disbursed with DSA attribution tag
         │
         ▼
  Commission Engine calculates payout (same day as disbursal)
         │
         ▼
  Payout held for 7-day cooling-off window
  (In case loan is cancelled / cooling-off exit by borrower)
         │
         ▼
  Day 8: Payout approved → Payment Service initiates NEFT to DSA bank A/c
         │
         ├── If DSA is GST-registered: GST invoice required from DSA
         └── If DSA is non-GST: Reverse charge mechanism (NBFC pays GST)
         │
         ▼
  Form 16A (TDS certificate) issued quarterly
```

### 13.2 Commission Calculation

```
  Gross Commission  =  Net Disbursed Amount  ×  Commission Rate

  Commission Slabs:
    ₹0 – ₹25,000          →  1.00%
    ₹25,001 – ₹1,00,000   →  1.50%
    ₹1,00,001 – ₹2,00,000 →  2.00%

  TDS (Section 194H — Commission):
    Rate:  10% of Gross Commission  (if PAN provided)
           20% if no PAN

  Net Payout  =  Gross Commission  −  TDS

  If DSA is GST-registered:
    GST Invoice Amount  =  Gross Commission × 18%  (NBFC pays this as input credit)
    Total NBFC Cost     =  Gross Commission + GST on Commission
```

> **WORKED EXAMPLE — DSA payout for ₹50,000 loan disbursed (Band B)**
> ```
> Net Disbursed          = ₹47,363
> Commission Rate        = 1.50%  (slab: ₹25,001–₹1,00,000)
> Gross Commission       = 47,363 × 1.5% = ₹711
> TDS (10%)              = ₹71
> Net Payout to DSA      = ₹711 − ₹71 = ₹640
>
> If GST-registered DSA:
>   GST on Commission    = ₹711 × 18% = ₹128
>   DSA raises invoice   = ₹711 + ₹128 = ₹839
>   NBFC pays ₹839, claims ₹128 as GST input credit
>   NBFC remits TDS ₹71 to govt.
>
> Accounting:
>   Dr  Commission Expense              ₹711
>   Dr  GST Input Credit (if GST reg.)  ₹128
>   Cr  Bank A/c (payout)               ₹640
>   Cr  TDS Payable (194H)               ₹71
>   Cr  GST Payable (if reverse charge)  ₹128  (if non-GST DSA)
> ```

---

## 14. Type 11 — GST Remittance on Charges

### 14.1 GST Applicability Summary

| Charge Type | GST Applicable | Rate | SAC Code |
|---|---|---|---|
| Processing Fee | Yes | 18% | 999714 |
| NACH / Mandate Registration | Yes | 18% | 997158 |
| Bounce / Dishonour Charge | Yes | 18% | 999714 |
| Late Payment Penalty | Yes | 18% | 999714 |
| Penal Interest | Yes | 18% | 999714 |
| Foreclosure / Prepayment Charge | Yes | 18% | 999714 |
| Legal / Recovery Charges | Yes | 18% | 998216 |
| OTS Processing Fee | Yes | 18% | 999714 |
| Loan Insurance Premium | Yes | 18% | 997131 |
| Interest (ROI) | **No** | Exempt | — |
| Stamp Duty | **No** | Govt. levy | — |

### 14.2 Monthly GST Calculation & Remittance

```
  GST Collected (Output Tax) in month M:
    =  Σ (All fee / charge components received × 18%)

  GST Input Credit (if any GSTIN-registered vendor invoices):
    =  Σ Input GST on eligible business expenses

  Net GST Payable  =  Output GST  −  Input GST Credit

  Due Date:  20th of following month (GSTR-3B filing + payment)
```

> **WORKED EXAMPLE — Monthly GST for 100 disbursals of ₹50,000 each**
> ```
> Processing Fees collected    = 100 × ₹1,500  = ₹1,50,000
> GST on PF (18%)              = ₹27,000
>
> NACH Charges collected       = 100 × ₹150    = ₹15,000
> GST on NACH (18%)            = ₹2,700
>
> Bounce Charges (assume 5%)   = 5 × ₹400      = ₹2,000
> GST on Bounce (18%)          = ₹360
>
> Total Output GST             = ₹27,000 + ₹2,700 + ₹360 = ₹30,060
> GST Input Credit (expenses)  = ₹5,000   (estimated)
> Net GST Payable              = ₹30,060 − ₹5,000 = ₹25,060
> ```

---

## 15. Type 12 — NACH Bounce Charge Recovery

### 15.1 Bounce Recovery Flow

```
  Bounce occurs on auto-debit attempt
         │
         ▼
  System adds bounce charge to loan account:
    eNACH bounce: ₹400 + ₹72 GST = ₹472
    UPI Autopay:  ₹300 + ₹54 GST = ₹354
         │
         ▼
  On next successful payment:
    Waterfall applies — bounce charge recovered BEFORE principal/interest
         │
         ▼
  If bounce charges remain unpaid at foreclosure:
    Added to foreclosure statement as outstanding charges
         │
         ▼
  If loan goes to NPA:
    Bounce charges remain on loan ledger
    Included in OTS negotiation / legal recovery
```

### 15.2 Bounce Charge Accounting

```
  On bounce event (charge creation):
    Dr  Bounce Charge Receivable (Borrower A/c)  =  ₹400
    Dr  GST Receivable (Borrower A/c)            =  ₹72
    Cr  Income — Bounce Charges                  =  ₹400   (deferred till collected)
    Cr  GST Payable (deferred)                   =  ₹72

  On collection of bounce charge:
    Dr  Bank A/c                                 =  ₹472
    Cr  Bounce Charge Receivable                 =  ₹400
    Cr  GST Receivable                           =  ₹72
    → Income and GST now realised
```

---

## 16. Payment Reconciliation Framework

### 16.1 Daily Reconciliation Checks

```
  End of Day — Payment Service vs. LMS vs. Bank Statement

  Check 1 — Amount Match:
    Σ payments received (Payment Gateway) = Σ payments applied (LMS)

  Check 2 — Count Match:
    No. of successful transactions (Gateway) = No. of EMIs marked PAID (LMS)

  Check 3 — Suspense Account:
    Any unmatched payments in VAN/suspense → Flag for manual resolution < 24h

  Check 4 — Bounce Reconciliation:
    No. of NACH returns (Bank) = No. of bounce charges created (LMS)

  Check 5 — Disbursal Reconciliation:
    No. of IMPS/UPI sent (Bank) = No. of loans moved to ACTIVE status (LMS)
```

### 16.2 Reconciliation Mismatch Handling

| Mismatch Type | System Action | TAT |
|---|---|---|
| Payment received, not applied in LMS | Hold in suspense; trigger alert to Ops | 4 hours |
| LMS shows PAID, bank not credited | Reverse LMS entry; raise payment failure | 2 hours |
| Amount mismatch (partial vs. full) | Apply waterfall to received amount; flag | 24 hours |
| Duplicate payment received | Second payment to suspense; refund within 2 days | 48 hours |
| Disbursal sent but not received by customer | Bank investigation initiated | 3 business days |

---

## 17. All Payment Types — Quick Reference Summary

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PAYMENT WATERFALL PRIORITY:
    1. Legal charges  2. Bounce charges  3. Penal interest
    4. Late penalty   5. Overdue interest  6. Overdue principal
    7. Current interest  8. Current principal  9. Advance/prepay

  SCHEDULED EMI:
    EMI = P×r×(1+r)^n / ((1+r)^n−1)
    Interest(k) = Opening Balance(k) × r
    Principal(k) = EMI − Interest(k)

  BROKEN PERIOD (first EMI):
    Extra = Principal × (r/30) × days_from_disbursal_to_first_due

  BULLET (Payday):
    Repayable = Principal + (Principal × daily_rate × days)

  OVERDUE CURE AMOUNT:
    = Overdue EMIs + Bounce×1.18 + Penalty×1.18 + Penal×1.18 + Legal×1.18

  PART-PREPAYMENT:
    Charge = Prepayment × Rate × 1.18
    New OS = OP − (Prepayment − Charge − GST)
    New EMI or Tenor recalculated via standard formula

  FORECLOSURE:
    Total = OP + Accrued Interest + (OP × FC_Rate × 1.18)
    Accrued Interest = OP × (r/30) × days_since_last_EMI

  COOLING-OFF REFUND:
    Refund = Net Disbursed − (Principal × r/30 × days_held)
    PF, NACH, Insurance, Stamp Duty are non-refundable

  DISBURSAL (Net Disbursed):
    = Principal − PF×1.18 − Stamp − NACH×1.18 − Insurance×1.18

  DSA COMMISSION:
    Gross = Net Disbursed × Rate
    Net   = Gross − TDS (10%)

  GST ON CHARGES:
    All fees except ROI and stamp duty attract 18% GST

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

*True Loan Bazaar (TLB) | Payment Flows & Calculations v1.0 | Confidential*
*Compliant with RBI Digital Lending Guidelines 2022 · RBI Fair Practice Code · NPCI · CGST Act 2017 · Income Tax Act (TDS)*
