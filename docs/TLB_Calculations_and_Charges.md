# Calculation & Charges Handbook
## Alpha LMS — Micro-Lending Platform

**All Fee, Interest & Penalty Calculations Across the Lending Lifecycle**

> Loan Products: Payday (7–30 days) | Short-Term (15–90 days) | EMI (3–12 months)
> Ticket Size: ₹5,000 – ₹2,00,000 | Compliant with RBI Digital Lending Guidelines 2022

---

## 1. Charge Master — All Applicable Fees

All fees are subject to 18% GST as per Indian tax law. The exact rate within each range is determined by the AI Risk Engine based on the customer's risk band.

| # | Charge Type | Applicable Rate / Amount | GST | When Levied | Regulatory Basis |
|---|---|---|---|---|---|
| 1 | Processing Fee | 2% – 5% of loan amount | 18% | At disbursal (deducted upfront) | RBI DLG 2022 — disclosed in KFS |
| 2 | Interest (ROI) — EMI Loans | 1.5% – 4% per month (reducing) | Nil | Monthly on outstanding principal | FEMA / RBI NBFC guidelines |
| 3 | Interest (ROI) — Payday Loans | 0.1% – 0.15% per day (flat) | Nil | Accrued daily on principal | RBI NBFC guidelines |
| 4 | Stamp Duty | 0.1% – 0.2% of loan amount | Nil | At loan agreement execution | Indian Stamp Act (state-wise) |
| 5 | NACH / Mandate Registration | ₹100 – ₹250 per mandate | 18% | One-time at mandate setup | NPCI circular |
| 6 | Bounce / Dishonour Charge | ₹300 – ₹500 per bounce | 18% | Per failed auto-debit attempt | RBI Fair Practice Code |
| 7 | Late Payment Penalty | 2% – 3% per month on overdue amt | 18% | From day 1 of default | Loan agreement / RBI FPC |
| 8 | Penal Interest (DPD 30+) | 3% – 5% per month on overdue | 18% | On sustained overdue after 30 DPD | RBI Circular — Penal Charges |
| 9 | Foreclosure / Prepayment | 2% – 5% of outstanding principal | 18% | On early full closure | RBI — NBFC policy |
| 10 | Part-Prepayment | 2% – 3% of prepaid amount | 18% | After 3rd EMI (min. 1 EMI amount) | NBFC policy |
| 11 | Loan Insurance Premium | 0.5% – 2% of loan amount | 18% | Optional; deducted at disbursal | IRDAI guidelines |
| 12 | Legal / Recovery Charges | Actuals (min ₹500) | 18% | On NPA; post DPD 90 | Loan agreement |
| 13 | Re-scheduling / Restructuring | 1% – 2% of outstanding principal | 18% | On approved loan restructuring | RBI / NBFC policy |
| 14 | Duplicate NOC / Statement | ₹100 – ₹200 per document | 18% | On customer request post-closure | NBFC policy |
| 15 | GST on All Fee Components | 18% flat | — | Applied on all charges except ROI | CGST Act 2017 |

> **NOTE:** ROI (interest) is exempt from GST. GST applies only to fees and penalty charges.

---

## 2. Risk Band & Interest Rate (ROI) Matrix

The AI/ML Risk Engine assigns a Risk Band (A through D) based on the Propensity-to-Pay Score (0–1000). The band determines the applicable interest rate and eligible loan ceiling.

| Risk Band | P2P Score | CIBIL Range | ROI (Monthly) | ROI (Annual) | Max Loan Amt | Tenor Range | Auto Decision |
|---|---|---|---|---|---|---|---|
| **A — Prime** | 750–1000 | 750+ | 1.50% – 2.00% | 18% – 24% | ₹2,00,000 | 3–12 months | Auto-Approve |
| **B — Near-Prime** | 550–749 | 650–749 | 2.00% – 2.75% | 24% – 33% | ₹1,00,000 | 3–6 months | Auto-Approve |
| **C — Sub-Prime** | 350–549 | 550–649 | 2.75% – 4.00% | 33% – 48% | ₹50,000 | 1–3 months | Manual Review |
| **D — Declined** | 0–349 | < 550 / NH | N/A | N/A | — | — | Auto-Reject |

> **NH** = No History (thin file). Payday loans use a separate daily-rate table regardless of band.

### 2.1 Payday / Daily-Rate ROI Table

| Risk Band | Daily Rate | Effective Monthly | Effective Annual | Max Ticket | Max Tenor |
|---|---|---|---|---|---|
| A | 0.10% / day | ~3.0% | ~36.5% | ₹50,000 | 30 days |
| B | 0.12% / day | ~3.6% | ~43.8% | ₹25,000 | 30 days |
| C | 0.15% / day | ~4.5% | ~54.75% | ₹15,000 | 30 days |

---

## 3. Step-by-Step Calculation Flow

### 3.1 Step 4 — AI Risk Assessment Calculations

#### A. FOIR (Fixed Obligation to Income Ratio)

FOIR measures what percentage of a customer's net monthly income is already committed to existing loan EMIs. Alpha LMS enforces a maximum FOIR of 50% before the new EMI.

```
FOIR  =  (Total Existing Monthly EMIs) / (Net Monthly Income)  × 100

Eligibility condition:   FOIR + New EMI  ≤  50% of Net Monthly Income

Maximum New EMI Allowed  =  (Net Monthly Income × 50%)  −  Existing EMIs
```

> **WORKED EXAMPLE — FOIR Check**
> ```
> Net Monthly Income     = ₹40,000
> Existing EMIs          = ₹8,000
> Current FOIR           = 8,000 / 40,000 = 20%
> Available for new EMI  = (40,000 × 50%) − 8,000 = ₹12,000
> Customer can support a max new EMI of ₹12,000 per month.
> ```

#### B. Loan Eligibility Amount (based on FOIR ceiling)

```
Max Eligible EMI  =  (Net Income × 0.50)  −  Existing Obligations

Max Loan Amount   =  Max Eligible EMI  ×  [1 − (1 + r)^−n] / r
                     where r = monthly interest rate, n = tenure in months
                     (Reducing balance formula — see Section 3.3F)
```

#### C. Risk Score → Band Assignment

```
P2P Score  =  w1×(CIBIL Normalised)  +  w2×(Bank Statement Score)
            +  w3×(Geo Zone Score)   +  w4×(Income Stability Score)
            +  w5×(Fraud Flag Penalty)

Weights (illustrative):  CIBIL=40%  BankStmt=25%  Geo=15%  Income=15%  Fraud=−5%

CIBIL Normalised  =  (CIBIL Score − 300) / (900 − 300)  × 1000

Score ≥ 750  → Band A    |   550–749 → Band B
350–549      → Band C    |   < 350   → Band D (Reject)
```

---

### 3.2 Step 5 — Offer Engine Calculations

#### A. Processing Fee Calculation

```
Processing Fee (PF)    =  Loan Amount  ×  PF Rate
GST on PF              =  PF  ×  18%
Total PF Deduction     =  PF  +  GST on PF

PF Rate by Risk Band:
  Band A → 2.0%   |   Band B → 3.0%
  Band C → 4.0%   |   Payday → 5.0%
```

> **WORKED EXAMPLE — Processing Fee (Band B, ₹50,000 loan)**
> ```
> Loan Amount         = ₹50,000
> PF Rate             = 3.0%
> Processing Fee      = 50,000 × 3%  = ₹1,500
> GST on PF (18%)     = 1,500 × 18%  = ₹270
> Total PF Deduction  = ₹1,500 + ₹270 = ₹1,770
> ```

#### B. Stamp Duty Calculation

```
Stamp Duty  =  Loan Amount  ×  State Rate

Common state rates (indicative):
  Maharashtra → 0.1% of loan amt  (min ₹100, max ₹500 for personal loans)
  Delhi       → 0.2% of loan amt
  Karnataka   → 0.1% of loan amt  (flat ₹200 for < ₹1,00,000)
  Tamil Nadu  → 0.2% of loan amt

Note: Stamp duty is NOT subject to GST.
```

> **WORKED EXAMPLE — Stamp Duty (Maharashtra, ₹50,000)**
> ```
> Loan Amount   = ₹50,000
> Rate          = 0.1%
> Stamp Duty    = 50,000 × 0.1% = ₹50  (subject to minimum ₹100)
> Applied Stamp Duty = ₹100
> ```

#### C. NACH Mandate Registration Charge

```
NACH Charge    =  ₹150  (one-time, per mandate)
GST on NACH    =  150  ×  18%  =  ₹27
Total          =  ₹177

Deducted from disbursed amount OR collected separately depending on NBFC policy.
```

#### D. Loan Insurance Premium (Optional)

```
Insurance Premium  =  Loan Amount  ×  Premium Rate
GST on Insurance   =  Premium  ×  18%

Typical Premium Rates:
  Payday / < 90 days → 0.5% of loan amount
  3–6 months EMI     → 1.0% of loan amount
  7–12 months EMI    → 1.5% – 2.0% of loan amount
```

#### E. Net Disbursed Amount

```
Net Disbursed  =  Sanctioned Loan Amount
               −  Processing Fee
               −  GST on Processing Fee
               −  Stamp Duty
               −  NACH Registration Charge  (if deducted upfront)
               −  Insurance Premium + GST   (if opted in)

Customer receives Net Disbursed to bank account.
Repayment EMIs are on the FULL Sanctioned Loan Amount (not net).
```

> **WORKED EXAMPLE — Net Disbursed (Band B, ₹50,000, 6-month EMI, Maharashtra)**
> ```
> Sanctioned Amount       = ₹50,000
> Processing Fee (3%)     = ₹1,500
> GST on PF (18%)         = ₹270
> Stamp Duty              = ₹100
> NACH Charge             = ₹150
> GST on NACH             = ₹27
> Insurance (1%)          = ₹500
> GST on Insurance (18%)  = ₹90
> ─────────────────────────────
> Total Deductions        = ₹2,637
> Net Disbursed           = ₹50,000 − ₹2,637 = ₹47,363
> ```

#### F. EMI Calculation — Reducing Balance (EMI Loans)

The standard Reducing Balance method is used for EMI loans. Interest is charged only on the outstanding principal, so each EMI has an increasing principal component and decreasing interest component.

```
       P × r × (1 + r)^n
EMI  = ─────────────────
         (1 + r)^n − 1

Where:
  P  = Principal (sanctioned loan amount)
  r  = Monthly interest rate  =  Annual ROI / 12
  n  = Loan tenure in months

Monthly Interest Component  =  Outstanding Principal × r
Monthly Principal Component =  EMI − Interest Component
Closing Outstanding         =  Opening Outstanding − Principal Component
```

> **WORKED EXAMPLE — EMI (Band B, ₹50,000 @ 2.5%/month, 6 months)**
> ```
> P = ₹50,000  |  r = 2.5% = 0.025  |  n = 6
>
> EMI = 50,000 × 0.025 × (1.025)^6 / ((1.025)^6 − 1)
>     = 50,000 × 0.025 × 1.15969 / 0.15969
>     ≈ ₹9,079
>
> Month | Opening Bal | EMI    | Interest | Principal | Closing Bal
> ─────────────────────────────────────────────────────────────────
>   1   | 50,000      | 9,079  | 1,250    | 7,829     | 42,171
>   2   | 42,171      | 9,079  | 1,054    | 8,025     | 34,146
>   3   | 34,146      | 9,079  |   854    | 8,226     | 25,920
>   4   | 25,920      | 9,079  |   648    | 8,431     | 17,489
>   5   | 17,489      | 9,079  |   437    | 8,642     |  8,847
>   6   |  8,847      | 9,068* |   221    | 8,847     |      0
>
> *Last EMI adjusted for rounding.
> Total Interest Paid = ₹4,464  |  Total Repaid = ₹54,464
> ```

#### G. Flat Rate EMI Calculation

```
Total Interest  =  P × Flat Rate × n
Total Repayable =  P + Total Interest
EMI             =  Total Repayable / n

Note: Flat rate loans have a HIGHER effective ROI than reducing balance.
Effective Monthly Rate (approx.) ≈ Flat Rate × 1.83
```

> **WORKED EXAMPLE — Flat Rate (₹50,000 @ 2.0% flat/month, 6 months)**
> ```
> Total Interest  = 50,000 × 2.0% × 6 = ₹6,000
> Total Repayable = ₹50,000 + ₹6,000  = ₹56,000
> Flat EMI        = 56,000 / 6        = ₹9,333 / month
>
> Effective reducing-equivalent rate ≈ 2.0% × 1.83 ≈ 3.66% / month
> ```

#### H. Bullet / One-Shot Repayment (Payday Loans)

```
Total Interest  =  Principal  ×  Daily Rate  ×  Tenor (days)
Total Repayable =  Principal  +  Total Interest

Paid in ONE instalment on maturity date.
```

> **WORKED EXAMPLE — Bullet (₹10,000 @ 0.12%/day, 21 days, Band B)**
> ```
> Principal         = ₹10,000
> Daily Rate        = 0.12%
> Tenor             = 21 days
> Total Interest    = 10,000 × 0.0012 × 21 = ₹252
> Total Repayable   = ₹10,252  (due on day 21)
> ```

#### I. APR / Annualised Cost of Credit (ACC) — KFS Mandatory

RBI's Digital Lending Guidelines (2022) mandate disclosure of the Annual Percentage Rate (APR) and total cost of credit in the Key Fact Statement (KFS) before loan acceptance.

```
APR  =  [(Total Amount Repaid − Net Disbursed) / Net Disbursed]
        × (365 / Tenor in days) × 100

Total Cost of Credit  =  Total Interest + All Fees + GST on Fees + Stamp Duty

Effective APR (XIRR method) — required for reducing-balance EMI loans:
  Solve for r in:  Net Disbursed  =  Σ  EMI / (1+r)^(t/365)
                    where t = days from disbursal to each payment
```

> **WORKED EXAMPLE — APR / KFS (₹50,000, 6 months, Band B)**
> ```
> Net Disbursed           = ₹47,363
> Total EMIs              = 9,079 × 5 + 9,068 = ₹54,463
> Total Cost of Credit    = ₹54,463 + ₹2,637 (deductions) − ₹50,000 = ₹7,100
> Simple APR              = (7,100 / 47,363) × (365/180) × 100 ≈ 30.4% p.a.
>
> KFS Disclosure:
>   Sanctioned Amount      ₹50,000
>   Net Disbursed          ₹47,363
>   Total Repayable        ₹54,463
>   Total Charges          ₹2,637
>   Total Cost of Credit   ₹7,100
>   APR                    ~30.4% p.a.
>   Cooling-off Period     3 days (exit without penalty)
> ```

---

### 3.3 Step 6 — e-Mandate Charges

| Mandate Type | Registration Charge | GST | Total | Failure Charge per Bounce |
|---|---|---|---|---|
| eNACH (bank debit) | ₹150 | ₹27 | ₹177 | ₹400 + ₹72 GST = ₹472 |
| UPI Autopay | ₹100 | ₹18 | ₹118 | ₹300 + ₹54 GST = ₹354 |

---

### 3.4 Step 7 — Disbursal Reconciliation

```
Disbursal Amount (IMPS/UPI)  =  Net Disbursed Amount  (computed in Step 5E)

IMPS / UPI Transfer Charges: Borne by the NBFC (not the customer)
  IMPS < ₹1,000        →  ₹2.50 + GST
  IMPS ₹1,000–₹1 lakh →  ₹5.00 + GST
  IMPS ₹1–2 lakh       →  ₹15.00 + GST
  UPI                  →  Free (₹0)

Disbursal Ledger Entry:
  Dr  Loan Account (Borrower)    =  Sanctioned Amount
  Cr  Bank Account (NBFC)        =  Net Disbursed
  Cr  Income — Processing Fee    =  Processing Fee
  Cr  GST Payable                =  GST on PF
  Cr  Stamp Duty Payable         =  Stamp Duty
```

---

## 4. LMS — Repayment Schedule & Interest Accrual

### 4.1 Daily Interest Accrual (for penalty / broken period)

```
Daily Interest  =  Outstanding Principal  ×  (Monthly ROI / 30)

Broken Period Interest (first EMI if disbursal mid-month):
  Broken Period Days =  Days from disbursal to first EMI date
  Broken Period Int  =  Principal × (Monthly ROI / 30) × Broken Period Days
  First EMI          =  Regular EMI + Broken Period Interest
```

### 4.2 Interest Accrual Journal (Monthly)

```
Dr  Interest Receivable (Borrower A/c)   =  Monthly Interest Component
Cr  Interest Income                       =  Monthly Interest Component

On EMI receipt:
Dr  Bank / Cash                           =  EMI Amount
Cr  Interest Receivable                   =  Interest Component
Cr  Loan Account (Borrower)              =  Principal Component
```

### 4.3 Outstanding Principal at Any Point in Time

```
Outstanding Principal (after k EMIs paid)

= P × (1+r)^k  −  EMI × [(1+r)^k − 1] / r

Where:  P   = Original Principal
        r   = Monthly ROI
        k   = Number of EMIs already paid
        EMI = Regular monthly instalment
```

> **WORKED EXAMPLE — Outstanding after 3 EMIs (₹50,000 @ 2.5%/month, 6 months)**
> ```
> P=50,000  r=0.025  EMI=9,079  k=3
>
> Outstanding = 50,000×(1.025)^3 − 9,079×((1.025)^3−1)/0.025
>             = 53,844 − 27,920
>             = ₹25,924
> ```

---

## 5. Late Payment, Bounce & Penalty Calculations

### 5.1 Bounce Charge on Failed Auto-Debit

```
Bounce Charge           =  ₹400 (eNACH) / ₹300 (UPI Autopay)
GST on Bounce Charge    =  Bounce Charge × 18%
Total Bounce Deduction  =  Bounce Charge + GST

Applied per failed debit attempt (max 2 retries → up to 3 bounce charges possible).
```

### 5.2 Late Payment Penalty (DPD 1–29)

```
Daily Penal Rate  =  2% per month on overdue amount  =  0.0667% per day

Penalty Amount  =  Overdue EMI  ×  (Penal Monthly Rate / 30)  ×  Days Overdue

GST on Penalty  =  Penalty Amount × 18%

Total Outstanding (with penalty):
  =  Overdue EMI  +  Bounce Charges (with GST)  +  Penalty (with GST)
```

> **WORKED EXAMPLE — Penalty (₹9,079 EMI overdue by 15 days, 1 bounce)**
> ```
> Overdue EMI         = ₹9,079
> Penal Rate          = 2% / month = 0.0667% / day
> Penalty             = 9,079 × 0.000667 × 15 = ₹91
> GST on Penalty      = 91 × 18%  = ₹16
> Bounce Charge       = ₹400
> GST on Bounce       = ₹72
> ─────────────────────────────────────────
> Total Outstanding   = 9,079 + 91 + 16 + 400 + 72 = ₹9,658
> ```

### 5.3 Penal Interest (DPD 30+ — Sustained Overdue)

```
Penal Interest Rate  =  3% – 5% per month on TOTAL overdue outstanding
                       (principal + accrued interest + earlier penalties)

Monthly Penal Interest  =  Total Overdue Outstanding × Penal Rate
GST on Penal Interest   =  Monthly Penal Interest × 18%

Compound escalation applies every 30 days until account is regularised.
```

### 5.4 DPD-Wise Outstanding Balance Calculation

| DPD | Charge Applied | Rate / Amount | GST | Cumulative Impact |
|---|---|---|---|---|
| DPD 1–7 | Bounce charge (if auto-debit attempted) | ₹400 / bounce | ₹72 | Soft — reminder only |
| DPD 8–15 | Late payment penalty accruing | 2% / month on OD | 18% | Penalty added daily |
| DPD 16–29 | Continued penalty + possible 2nd bounce | 2% / month + ₹400 | 18% | Penalty compounding |
| DPD 30+ | Penal interest kicks in | 3–5% / month on OD | 18% | Faster accumulation |
| DPD 60+ | Legal notice charges added | Actuals (min ₹500) | 18% | NPA imminent |
| DPD 90+ | NPA classification; write-off initiated | Full legal costs | 18% | Credit bureau reported |

---

## 6. Foreclosure & Part-Prepayment Calculations

### 6.1 Foreclosure (Full Early Closure)

```
Outstanding Principal at Time of Foreclosure (k EMIs paid):
  OP  =  P×(1+r)^k − EMI×[(1+r)^k − 1]/r

Foreclosure Charge   =  OP  ×  Foreclosure Rate
GST on FC Charge     =  Foreclosure Charge  ×  18%

Total Foreclosure Payment  =  OP  +  Foreclosure Charge  +  GST  +  Any Overdue

Foreclosure Rates (Alpha LMS policy):
  Band A: 2% of OP  |  Band B: 3%  |  Band C: 4%
  Within 3 months of disbursal: additional 1% surcharge
  Payday loans: No foreclosure charge (bullet structure)
```

> **WORKED EXAMPLE — Foreclosure after 3 EMIs (₹50,000 @ 2.5%/month, 6m, Band B)**
> ```
> Outstanding Principal (OP) = ₹25,924
> Foreclosure Rate           = 3%
> Foreclosure Charge         = 25,924 × 3% = ₹778
> GST on Foreclosure         = 778 × 18%   = ₹140
> ─────────────────────────────────────────────────
> Total Foreclosure Payment  = 25,924 + 778 + 140 = ₹26,842
>
> Interest Saved vs. completing loan:
>   Remaining interest (3 EMIs) = ₹1,313
>   Charge paid                 = ₹918
>   Net savings                 = ₹395
> ```

### 6.2 Part-Prepayment

```
Conditions (Alpha LMS policy, aligned with RBI FPC):
  • Minimum 3 EMIs must be paid before part-prepayment is allowed
  • Minimum prepayment = 1 full EMI amount
  • Maximum 2 part-prepayments per loan tenure

Part-Prepayment Charge  =  Prepayment Amount  ×  Part-Prepay Rate (2–3%)
GST                     =  Charge  ×  18%

After Part-Prepayment → LMS recalculates amortisation schedule:
  Option A: Reduce EMI (same tenure)
  Option B: Reduce Tenure (same EMI)   ← Alpha LMS default
```

---

## 7. DSA / Agent Commission Calculations

### 7.1 Commission Structure

| Slab (Disbursed Amt) | DSA Commission Rate | Sub-DSA Split | Alpha LMS Retention |
|---|---|---|---|
| ₹0 – ₹25,000 | 1.00% of disbursed amt | 0.25% to sub-DSA | 0.75% |
| ₹25,001 – ₹1,00,000 | 1.50% of disbursed amt | 0.40% to sub-DSA | 1.10% |
| ₹1,00,001 – ₹2,00,000 | 2.00% of disbursed amt | 0.50% to sub-DSA | 1.50% |

### 7.2 Commission Calculation Formula

```
Gross Commission  =  Net Disbursed Amount  ×  Commission Rate
TDS on Commission =  Gross Commission  ×  10%  (if agent PAN on file)
Net Payout        =  Gross Commission  −  TDS

GST: DSA must raise GST invoice (18%) if registered under GST.
If unregistered DSA (< ₹20L turnover): No GST invoice; reverse charge may apply.
```

> **WORKED EXAMPLE — DSA Commission (₹50,000 loan disbursed, Band B)**
> ```
> Net Disbursed      = ₹47,363
> Commission Rate    = 1.50%
> Gross Commission   = 47,363 × 1.5% = ₹711
> TDS (10%)          = ₹71
> Net Payout to DSA  = ₹711 − ₹71 = ₹640
> ```

---

## 8. Geofencing & Distance Rule Calculations

```
Distance Calculation (Haversine Formula via Google Maps API):

d  =  2R × arcsin( √[ sin²(Δlat/2) + cos(lat1)×cos(lat2)×sin²(Δlon/2) ] )

Where R     = 6,371 km (Earth's radius)
      lat1, lon1 = Aadhaar registered address coordinates
      lat2, lon2 = Nearest BP Securities branch coordinates

Alpha LMS Business Rules:
  Loan ≤ ₹20,000  →  No distance restriction
  Loan > ₹20,000  →  Customer address must be within 50 km of nearest branch
  Negative Pincode Zone  →  Auto-Reject regardless of loan amount
```

---

## 9. End-to-End Worked Examples

### Example 1 — Payday Loan: ₹10,000 for 21 Days (Band B)

| Item | Calculation | Amount (₹) |
|---|---|---|
| Sanctioned Amount | — | 10,000 |
| Processing Fee (5%) | 10,000 × 5% | 500 |
| GST on PF (18%) | 500 × 18% | 90 |
| Stamp Duty (Maharashtra) | min ₹100 | 100 |
| NACH Charge | — | 150 |
| GST on NACH | 150 × 18% | 27 |
| **Total Deductions** | 500+90+100+150+27 | **867** |
| **Net Disbursed to Customer** | 10,000 − 867 | **9,133** |
| Daily Interest Rate | 0.12% / day (Band B) | — |
| Total Interest (21 days) | 10,000 × 0.12% × 21 | 252 |
| **Total Repayable (Bullet)** | 10,000 + 252 | **10,252** |
| Total Cost of Credit | 252 + 867 | 1,119 |
| APR (simple) | (1,119/9,133)×(365/21)×100 | ~213% p.a. effective |

---

### Example 2 — EMI Loan: ₹50,000 for 6 Months (Band B)

| Item | Calculation | Amount (₹) |
|---|---|---|
| Sanctioned Amount | — | 50,000 |
| Monthly ROI | 2.5% / month (Band B) | — |
| EMI (reducing balance) | P×r×(1+r)^n / ((1+r)^n−1) | 9,079 |
| Processing Fee (3%) | 50,000 × 3% | 1,500 |
| GST on PF (18%) | 1,500 × 18% | 270 |
| Stamp Duty | min ₹100 (Maharashtra) | 100 |
| NACH Charge + GST | 150 + 27 | 177 |
| Insurance Premium (1%) + GST | 500 + 90 | 590 |
| **Total Deductions** | 1,500+270+100+177+590 | **2,637** |
| **Net Disbursed** | 50,000 − 2,637 | **47,363** |
| Total EMIs | 9,079 × 5 + 9,068 (adj.) | 54,463 |
| Total Interest Paid | 54,463 − 50,000 | 4,463 |
| **Total Cost of Credit** | 4,463 + 2,637 | **7,100** |
| APR (simple) | (7,100/47,363)×(365/180)×100 | ~30.4% p.a. |

---

### Example 3 — EMI Loan: ₹1,00,000 for 12 Months (Band A)

| Item | Calculation | Amount (₹) |
|---|---|---|
| Sanctioned Amount | — | 1,00,000 |
| Monthly ROI | 1.75% / month (Band A) | — |
| EMI (reducing balance) | P×r×(1+r)^12 / ((1+r)^12−1) | 9,319 |
| Processing Fee (2%) | 1,00,000 × 2% | 2,000 |
| GST on PF (18%) | 2,000 × 18% | 360 |
| Stamp Duty (Maha.) | capped at ₹500 | 100 |
| NACH Charge + GST | 150 + 27 | 177 |
| Insurance (1.5%) + GST | 1,500 + 270 | 1,770 |
| **Total Deductions** | 2,000+360+100+177+1,770 | **4,407** |
| **Net Disbursed** | 1,00,000 − 4,407 | **95,593** |
| Total Repaid (12 EMIs) | 9,319 × 12 (approx.) | 1,11,828 |
| Total Interest Paid | 1,11,828 − 1,00,000 | 11,828 |
| **Total Cost of Credit** | 11,828 + 4,407 | **16,235** |
| APR (simple) | (16,235/95,593)×(365/365)×100 | ~17.0% p.a. |

---

## 10. Key Fact Statement (KFS) — RBI Mandatory Disclosure

As per RBI Digital Lending Guidelines 2022, a KFS must be provided to the borrower before loan acceptance. The borrower has a minimum **3-day cooling-off period** to exit without penalty.

| KFS Field | Description | Example (₹50,000, 6m, Band B) |
|---|---|---|
| Lender Name | Name of NBFC / lending entity | BP Securities / Alpha LMS NBFC |
| Loan Product | Product type | Short-Term Personal Loan |
| Sanctioned Loan Amount | Approved principal | ₹50,000 |
| Net Disbursed Amount | Amount credited to borrower's account | ₹47,363 |
| Tenure | Loan repayment period | 6 months |
| Monthly Instalment (EMI) | Fixed monthly payment | ₹9,079 |
| Annual Percentage Rate (APR) | All-in annualised cost | ~30.4% p.a. |
| Rate of Interest | ROI per month (reducing balance) | 2.5% p.m. (30% p.a.) |
| Processing Fee | Upfront fee | ₹1,500 + ₹270 GST |
| Stamp Duty | State levy on loan agreement | ₹100 |
| Mandate Charge | eNACH / UPI Autopay registration | ₹177 (incl. GST) |
| Insurance Premium | Optional loan cover (opted in) | ₹590 (incl. GST) |
| Total Amount Payable | Sum of all EMIs | ₹54,463 |
| Total Cost of Credit | All charges + interest | ₹7,100 |
| Penal Charges on Default | Late fee + bounce charge | 2%/month + ₹400/bounce (+GST) |
| Foreclosure Charge | Early closure penalty | 3% of outstanding + GST |
| Cooling-off Period | Exit window without penalty | 3 business days from disbursal |
| Grievance Officer | Contact for complaints | [NBFC Grievance Officer details] |

---

## 11. Cross-Sell Eligibility Logic

Post loan closure, the BI Engine automatically flags customers for cross-sell based on repayment behaviour.

| Repayment Behaviour | Cross-Sell Product | Increment Rule | Processing Fee Incentive |
|---|---|---|---|
| Closed on time (0 DPD) | Next loan +50% ticket | ₹5K→₹7.5K, ₹20K→₹30K | 0.5% discount on PF |
| Closed 1–3 days early | Next loan +75% ticket | ₹5K→₹8.75K | 1.0% discount on PF |
| Closed with 1–2 DPD incidents | Same ticket, next loan | No increment | No discount |
| Closed with 3+ DPD incidents | Reduced ticket (−25%) | ₹20K→₹15K | PF rate +0.5% |

---

## 12. Quick Reference — Total Charge Load by Scenario

> **NOTE:** APR values are approximate (simple method). XIRR-based APR will differ slightly; use XIRR for KFS disclosure.

| Scenario | Loan | Tenor | Band | ROI/mo | PF+GST | Stamp | NACH | Insur. | Net Disb. | Total OD | APR~ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Payday Small | ₹10,000 | 21d | B | 0.12%/d | ₹590 | ₹100 | ₹177 | — | ₹9,133 | ₹10,252 | ~21% |
| Payday Large | ₹25,000 | 30d | A | 0.10%/d | ₹1,239 | ₹100 | ₹177 | — | ₹23,484 | ₹25,750 | ~15% |
| EMI Small | ₹20,000 | 3m | B | 2.50% | ₹708 | ₹100 | ₹177 | ₹236 | ₹18,779 | ₹21,552 | ~29% |
| EMI Mid | ₹50,000 | 6m | B | 2.50% | ₹1,770 | ₹100 | ₹177 | ₹590 | ₹47,363 | ₹54,463 | ~30% |
| EMI Large | ₹1,00,000 | 12m | A | 1.75% | ₹2,360 | ₹100 | ₹177 | ₹1,770 | ₹95,593 | ₹1,11,828 | ~17% |
| EMI Max Ticket | ₹2,00,000 | 12m | A | 1.50% | ₹4,720 | ₹200 | ₹177 | ₹3,540 | ₹1,91,363 | ₹2,19,576 | ~15% |

---

*Alpha LMS | Calculation & Charges Handbook v1.0 | Confidential | Compliant with RBI Digital Lending Guidelines 2022*
