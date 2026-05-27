# Authorization & Access Control Design — Alpha LMS
## Alpha LMS — Post-Disbursal Authorization Framework

> **Version:** 2.0 | **Reference:** R&D-docs/v0/Alpha LMS_Authorization_Framework.md (platform-wide) · LMS_LLD_v2.md · LMS_HLD_v2.md
>
> **Regulatory basis:** RBI Digital Lending Guidelines 2022 · RBI Master Direction KYC 2016 (amended 2023) · RBI IT Framework for NBFCs (Oct 2017) · RBI Cyber Security Framework for NBFCs (2021) · RBI Master Direction NBFC-ND-SI 2016 · RBI Fair Practice Code · DPDP Act 2023 · IT Act 2000 — Section 43A · IT (SRPS) Rules 2011 · NPCI eMandate Guidelines · IRDAI (for credit-linked insurance opt-in)

---

## 1. Authorization Principles

| Principle | Implementation |
|---|---|
| **Least privilege** | Every role gets the minimum access required — no more |
| **Need-to-know** | PII (Aadhaar, PAN, mobile, bank account) accessible only to roles with legal necessity |
| **Maker-checker (four-eyes)** | All high-value / irreversible financial operations require two distinct users |
| **Tenant isolation** | A user from Tenant A can never read or write data belonging to Tenant B — enforced at DB level via PostgreSQL RLS |
| **Customer data sovereignty** | A customer can only access their own loans; no cross-customer lookup permitted |
| **Immutable audit trail** | Every access, every approval, every config change — INSERT-only log; 7-year retention (RBI mandate) |
| **Time-bound sessions** | Access tokens: 15 min; staff sessions: 8 hours; SUPER_ADMIN: 4 hours |
| **Revocability** | Any token or session can be invalidated immediately (termination, suspicious activity) |
| **Purpose limitation** | Every PII access logged with business action/purpose (DPDP Act 2023 — Section 6) |
| **Self-approval prohibited** | `checker_id ≠ maker_id` enforced at DB constraint level, not just application layer |

---

## 2. Roles & Definitions

### 2.1 Role Catalogue

| Role ID | Role Name | Category | Description |
|---|---|---|---|
| `BORROWER` | Borrower / Customer | Customer | Self-service; access limited to own loan data only |
| `DSA_AGENT` | DSA Field Agent | Partner | Submits leads; views loans they sourced only |
| `DSA_MANAGER` | DSA Manager | Partner | Views all loans under their DSA group |
| `CREDIT_ANALYST` | Credit Analyst | Staff | Reviews risk reports; recommends decisions; cannot approve |
| `CREDIT_OFFICER` | Credit Officer | Staff | Approves loans up to ₹1,00,000; LMS: initiates restructuring, OTS |
| `SR_CREDIT_OFFICER` | Senior Credit Officer | Staff | Approves loans up to ₹2,00,000; checker for disbursal; LMS: approves write-off initiation |
| `COLLECTIONS_AGENT` | Collections Agent | Staff | Manages DPD 1–30 accounts assigned to them |
| `COLLECTIONS_MANAGER` | Collections Manager | Staff | Views all delinquent accounts; DPD 31–90; approves field visits; initiates legal queue |
| `OPS_EXECUTIVE` | Operations Executive | Staff | Reconciliation, disbursal monitoring, mandate management |
| `FINANCE_OFFICER` | Finance Officer | Staff | Financial reports, GST filings, DSA commission payouts |
| `COMPLIANCE_OFFICER` | Compliance / Risk Officer | Staff | Audit logs, NPA management, RBI reporting, write-off approval |
| `AUDITOR` | Internal / External Auditor | Staff | Read-only across all records; no write permissions |
| `IT_ADMIN` | IT Administrator | Staff | User management, system config; no loan data access |
| `SUPER_ADMIN` | Super Administrator | Staff | Emergency break-glass only; every action requires 2nd approval + real-time alert |
| `SYSTEM` | Automated System | Internal | AI engine, scheduler, notification service (service account JWT) |
| `INTEGRATION` | External Integration | External | CIBIL, UIDAI, NPCI, Payment Gateway (API key + mTLS) |

### 2.2 Role Hierarchy

```
SUPER_ADMIN
     │
     ├── IT_ADMIN              (system config only — no loan data)
     ├── COMPLIANCE_OFFICER    (audit + NPA + write-off approval)
     ├── AUDITOR               (read-only everything)
     │
     ├── SR_CREDIT_OFFICER
     │         └── CREDIT_OFFICER
     │                   └── CREDIT_ANALYST
     │
     ├── COLLECTIONS_MANAGER   (DPD 31–90 + legal queue)
     │         └── COLLECTIONS_AGENT (DPD 1–30, assigned accounts)
     │
     ├── FINANCE_OFFICER
     ├── OPS_EXECUTIVE
     │
     ├── DSA_MANAGER
     │         └── DSA_AGENT
     │
     └── BORROWER              (own loans only)
```

---

## 3. Loan Sanctioning Authority (LSA) Matrix

RBI requires NBFCs to have a Board-approved Credit Policy defining sanctioning limits per role. No individual below the specified level may sanction beyond their limit.

```
  Loan Amount Range         Sanctioning Authority              Mode
  ──────────────────────────────────────────────────────────────────────
  ₹5,000   – ₹25,000       AI Engine (Auto)                   Automated
                            (Risk Band A/B only; Band C+ → manual)

  ₹25,001  – ₹50,000       CREDIT_OFFICER                     Manual review
                            (Maker) + System AI score          + AI assist

  ₹50,001  – ₹1,00,000     CREDIT_OFFICER (Maker)             4-Eyes:
                            + SR_CREDIT_OFFICER (Checker)      Maker-Checker

  ₹1,00,001 – ₹2,00,000    SR_CREDIT_OFFICER (Maker)          4-Eyes:
                            + COMPLIANCE_OFFICER (Checker)     Dual approval

  Restructuring (any amt)   CREDIT_OFFICER (Maker)             Credit Committee
                            + SR_CREDIT_OFFICER (Checker)      approval

  OTS — waiver ≤ ₹50,000   SR_CREDIT_OFFICER                  Single senior
  OTS — waiver > ₹50,000   COMPLIANCE_OFFICER                 + Documentation

  Write-off ≤ ₹1,00,000    COMPLIANCE_OFFICER (Maker)         4-Eyes
                            + MD / CEO (Checker)

  Write-off > ₹1,00,000    Board Resolution Required           Board minutes
                            (board_resolution_ref mandatory in loan_write_offs)
```

### 3.1 Auto-Approval Engine Rules

```
  Auto-approval permitted ONLY when ALL conditions are met:
    ✅  Loan amount ≤ ₹25,000
    ✅  Risk Band = A or B  (P2P Score ≥ 550)
    ✅  KYC status = VERIFIED (all 3 checks passed)
    ✅  Fraud DB = CLEAN
    ✅  Geo check = ALLOWED zone
    ✅  FOIR ≤ 50% after new EMI
    ✅  No existing active loan for same PAN
    ✅  Cooling-off on prior loan (if any) fully elapsed

  Any single condition failing → routes to MANUAL_REVIEW queue
```

---

## 4. Permission Matrix

> Legend: ✅ Full access · 📖 Read-only · 🔒 Own / assigned records only · ➕ Initiate only (needs checker) · ❌ No access · ⚠️ With PII masking

### 4.1 Loan Account Operations

| Operation | BORROWER | DSA_AGENT | CREDIT_OFFICER | SR_CREDIT_OFFICER | COLLECTIONS_AGENT | COLLECTIONS_MANAGER | COMPLIANCE_OFFICER | OPS_EXEC | AUDITOR |
|---|---|---|---|---|---|---|---|---|---|
| View loan details | 🔒 own | 🔒 sourced | ✅ | ✅ | 🔒 assigned | ✅ (DPD 31+) | ✅ | ⚠️ masked | 📖 |
| View ledger | 🔒 own | ❌ | ✅ | ✅ | 🔒 assigned | ✅ | ✅ | 📖 | 📖 |
| View schedule | 🔒 own | 🔒 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 📖 |
| View outstanding | 🔒 own | 🔒 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 📖 |
| Cancel (cooling-off) | 🔒 own only | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Download NOC | 🔒 own | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | 📖 |
| Generate NOC (manual) | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ |
| Download KFS | 🔒 own | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | 📖 |
| Interest certificate | 🔒 own | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 📖 |

### 4.2 Payment & Mandate Operations

| Operation | BORROWER | DSA_AGENT | CREDIT_OFFICER | COLLECTIONS_AGENT | COLLECTIONS_MANAGER | OPS_EXEC | COMPLIANCE_OFFICER |
|---|---|---|---|---|---|---|---|
| Manual payment initiation | 🔒 own | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| View payment history | 🔒 own | 🔒 | ✅ | 🔒 assigned | ✅ | ✅ | ✅ |
| Generate payment link | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| View mandate | 🔒 own | ❌ | ✅ | 📖 | ✅ | ✅ | ✅ |
| Cancel / pause / resume mandate | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ (maker) | ✅ |
| Amend mandate (bank change) | 🔒 own | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ |

### 4.3 Closure & Settlement Operations

| Operation | BORROWER | CREDIT_OFFICER | SR_CREDIT_OFFICER | COLLECTIONS_MANAGER | COMPLIANCE_OFFICER |
|---|---|---|---|---|---|
| Foreclosure — get quote | 🔒 own | ✅ | ✅ | ✅ | ✅ |
| Foreclosure — initiate | 🔒 own | ✅ | ✅ | ✅ | ✅ |
| Part-prepayment — get quote | 🔒 own | ✅ | ✅ | ✅ | ✅ |
| Part-prepayment — initiate | 🔒 own | ✅ | ✅ | ✅ | ✅ |
| Restructuring — apply | ❌ | ➕ maker | ✅ checker | ➕ recommend | ✅ |
| Restructuring — approve | ❌ | ❌ | ✅ | ❌ | ✅ |
| OTS — offer / initiate | ❌ | ➕ | ✅ (waiver ≤ ₹50K) | ❌ | ✅ (waiver > ₹50K) |
| OTS — accept + payment | ❌ | ❌ | ✅ | ❌ | ✅ |
| Write-off — initiate | ❌ | ❌ | ➕ recommend | ❌ | ➕ maker |
| Write-off — approve | ❌ | ❌ | ❌ | ❌ | ✅ (+ board ref if > ₹1L) |
| Recovery post write-off | ❌ | ✅ | ✅ | ❌ | ✅ |
| Rate reset — trigger | ❌ | ➕ | ✅ | ❌ | ✅ |

### 4.4 Waiver Authority

| Waiver Amount | Minimum Role |
|---|---|
| ≤ ₹500 | `COLLECTIONS_AGENT` (or `CUSTOMER_SUPPORT`) |
| ≤ ₹5,000 | `COLLECTIONS_MANAGER` |
| ≤ ₹50,000 | `SR_CREDIT_OFFICER` |
| > ₹50,000 | `COMPLIANCE_OFFICER` |
| Unlimited | `COMPLIANCE_OFFICER` + MD co-sign |

### 4.5 Configuration (Master Tables)

| Operation | OPS_EXEC | SR_CREDIT_OFFICER | COMPLIANCE_OFFICER | IT_ADMIN | SUPER_ADMIN |
|---|---|---|---|---|---|
| charge_master — create/edit | ❌ | ➕ checker | ➕ maker | ❌ | ✅ |
| product_master — create/edit | ❌ | ➕ checker | ➕ maker | ❌ | ✅ |
| collection_rule_master — edit | ❌ | ➕ checker | ➕ maker | ❌ | ✅ |
| tenant_configs — edit | ❌ | ❌ | ➕ maker | ➕ maker | ✅ checker |
| Pincode whitelist/blacklist | ❌ | ➕ checker | ➕ maker | ❌ | ✅ |
| ROI rule change | ❌ | ➕ checker | ➕ maker | ❌ | ✅ |
| User account management | ❌ | ❌ | ❌ | ➕ maker | ✅ checker |

### 4.6 Reporting & Audit

| Operation | FINANCE_OFFICER | COMPLIANCE_OFFICER | AUDITOR | SUPER_ADMIN |
|---|---|---|---|---|
| Admin dashboard / DPD report | ❌ | ✅ | 📖 | ✅ |
| NPA list | ❌ | ✅ | 📖 | ✅ |
| Bureau submission | ❌ | ✅ | ❌ | ✅ |
| RBI monthly return | ✅ | ✅ | 📖 | ✅ |
| View audit logs | ❌ | ✅ | ✅ | ✅ |
| Export audit logs / PII dataset | ❌ | ✅ (+ SUPER_ADMIN approval) | ❌ | ✅ |
| Cross-sell eligible list | ❌ | ✅ | ❌ | ✅ |
| DSA commission payouts | ✅ maker | ❌ | 📖 | ✅ checker |

---

## 5. Maker-Checker (Four-Eyes) Policy

Mandatory for all high-value or irreversible financial actions per RBI IT Framework (2017) Section 7.3.

### 5.1 Maker-Checker Triggers

| Action | Maker Role | Checker Role | Timeout | On Timeout |
|---|---|---|---|---|
| Loan disbursal > ₹50,000 | `CREDIT_OFFICER` | `SR_CREDIT_OFFICER` | 4 hours | Auto-escalate |
| eNACH mandate cancellation | `OPS_EXECUTIVE` | `COLLECTIONS_MANAGER` | 2 hours | Action blocked |
| Loan restructuring | `CREDIT_OFFICER` | `SR_CREDIT_OFFICER` | 24 hours | Escalate to Compliance |
| OTS agreement | `SR_CREDIT_OFFICER` | `COMPLIANCE_OFFICER` | 48 hours | Escalate to MD |
| Write-off ≤ ₹1,00,000 | `COMPLIANCE_OFFICER` | MD / CEO | 72 hours | Board resolution required |
| Write-off > ₹1,00,000 | `COMPLIANCE_OFFICER` | Board resolution | — | Board minutes mandatory |
| charge_master / product_master change | `COMPLIANCE_OFFICER` | `SR_CREDIT_OFFICER` | 24 hours | Rollback |
| ROI rule change | `COMPLIANCE_OFFICER` | `SR_CREDIT_OFFICER` | 24 hours | Rollback |
| tenant_configs edit | `COMPLIANCE_OFFICER` | `SUPER_ADMIN` | 8 hours | Rollback |
| User privilege escalation | `IT_ADMIN` | `SUPER_ADMIN` | 1 hour | Action blocked |
| Bulk DSA payout > ₹1 lakh | `FINANCE_OFFICER` | `SR_CREDIT_OFFICER` | 4 hours | Payout blocked |
| PII dataset export | `COMPLIANCE_OFFICER` | `SUPER_ADMIN` | 2 hours | Export blocked |
| Rate reset | `SR_CREDIT_OFFICER` | `COMPLIANCE_OFFICER` | 24 hours | Action blocked |

### 5.2 Maker-Checker DB Table

```sql
pending_approvals (
  id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID         NOT NULL,
  resource_type    VARCHAR(50)  NOT NULL,
    -- 'write_off' | 'charge_master' | 'product_master' | 'restructuring'
    -- | 'ots' | 'rate_reset' | 'user_role' | 'roi_rule' | 'pii_export'
  resource_id      UUID         NOT NULL,
  action           VARCHAR(50)  NOT NULL,   -- 'create' | 'update' | 'approve'
  payload          JSONB        NOT NULL,   -- proposed change (before state snapshot)
  initiated_by     UUID         NOT NULL REFERENCES users(id),
  initiated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  approved_by      UUID         REFERENCES users(id),
  approved_at      TIMESTAMPTZ,
  rejection_reason TEXT,
  expires_at       TIMESTAMPTZ  NOT NULL,
  status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- 'pending' | 'approved' | 'rejected' | 'expired'

  CONSTRAINT chk_no_self_approve CHECK (approved_by IS NULL OR approved_by != initiated_by)
);
```

### 5.3 Maker-Checker Flow

```
  MAKER initiates action
         │
         ▼
  System creates PENDING record in pending_approvals
  (payload_hash stored for tamper detection)
         │
         ▼
  CHECKER receives in-app + email notification
         │
         ├── CHECKER APPROVES
         │     System enforces: checker_id ≠ maker_id (DB constraint)
         │     Action executed → audit_log: maker_id, checker_id, timestamp, IP
         │
         ├── CHECKER REJECTS
         │     Action voided → maker notified → reason logged
         │
         └── TIMEOUT
               Action auto-blocked → escalation notification sent
               SLA breach logged for supervisor review
```

---

## 6. Authentication Framework

### 6.1 Customer Authentication

```
  Step 1: Mobile OTP (Primary Factor)
    OTP:          6 digits
    TTL:          3 minutes (Redis, auto-expire)
    Storage:      bcrypt hash (never plaintext)
    Max attempts: 3 per session → 30-minute lock
    Resend limit: 3 per hour per mobile

  Step 2 (loan amount > ₹1,00,000): Aadhaar OTP (Second Factor)
    UIDAI OTP to Aadhaar-registered mobile
    Validated via UIDAI API before offer generation

  Token Issuance:
    Access Token:  JWT (RS256), 15-minute TTL
    Refresh Token: Opaque, 7-day TTL, single-use, stored in Redis
    Device Binding: device_fingerprint embedded in JWT claims
```

### 6.2 Staff Authentication

```
  Step 1: Username + Password
    Min 12 characters | Uppercase + Lowercase + Number + Special char
    No dictionary words | No repeat of last 6 passwords
    Mandatory change every 90 days
    bcrypt (cost factor ≥ 12)

  Step 2: TOTP MFA (Mandatory for ALL staff)
    Google Authenticator / Authy (RFC 6238)
    30-second window | ±1 window tolerance

  Step 3 (SUPER_ADMIN / IT_ADMIN only): Hardware Security Key
    FIDO2 / WebAuthn (YubiKey or equivalent)
    Required for every privileged session

  Session:
    Staff session TTL:    8 hours
    Idle timeout:         30 minutes
    Concurrent sessions:  Max 1 per user (new login terminates old)
    IP binding:           Session locked to IP at login; warn on change
```

### 6.3 API / Integration Authentication

```
  External integrations (CIBIL, UIDAI, NPCI, Payment GW):
    API Key + Secret (HMAC-SHA256 request signing)
    Key rotation: Every 90 days (mandatory)
    IP whitelist: Only NBFC's static IP range
    Rate limit: Per integration, per minute
    mTLS: Required for UIDAI and NPCI connections

  Internal service-to-service:
    Service tokens (JWT, RS256, 5-minute TTL)
    Client credentials flow (OAuth 2.0)
    Scoped to specific service: aud claim checked at gateway
    Stored in AWS Secrets Manager; rotated every 30 days
```

---

## 7. JWT Token Structure

### 7.1 Customer JWT Claims

```json
{
  "sub":          "USR_1234567890",
  "mobile":       "+91XXXXXXX789",
  "tenant_id":    "ten_BP_SECURITIES",
  "role":         "BORROWER",
  "scope":        "own",
  "customer_id":  "cust_01HXZ...",
  "loan_ids":     ["LN_20240001"],
  "device_fp":    "hash_of_device_fingerprint",
  "session_id":   "ses_01HXZ...",
  "iat":          1716000000,
  "exp":          1716000900,
  "jti":          "unique_token_id",
  "iss":          "https://api.tlb.in",
  "aud":          "tlb-lms"
}
```

### 7.2 Staff JWT Claims

```json
{
  "sub":          "STF_987654",
  "name":         "Rahul Sharma",
  "tenant_id":    "ten_BP_SECURITIES",
  "role":         "CREDIT_OFFICER",
  "scope":        "tenant",
  "permissions":  [
    "loan:approve:lte_100000",
    "loan:view:all",
    "loan:restructure:initiate",
    "pii:view:masked"
  ],
  "branch_id":    "BR_MUM_001",
  "agent_id":     null,
  "ip_bound":     "203.0.113.45",
  "mfa_verified": true,
  "session_id":   "ses_01HXZ...",
  "iat":          1716000000,
  "exp":          1716028800,
  "jti":          "unique_token_id",
  "iss":          "https://api.tlb.in",
  "aud":          "tlb-lms"
}
```

### 7.3 Permission Scopes (OAuth2-style)

| Scope | Description | Granted To |
|---|---|---|
| `loan:view:own` | View own loan details | `BORROWER`, `DSA_AGENT` |
| `loan:view:all` | View all loans in tenant | `CREDIT_OFFICER` and above |
| `loan:approve:lte_25000` | AI auto-approval | `SYSTEM` (AI engine) |
| `loan:approve:lte_100000` | Approve ≤ ₹1,00,000 | `CREDIT_OFFICER` |
| `loan:approve:lte_200000` | Approve ≤ ₹2,00,000 | `SR_CREDIT_OFFICER` |
| `loan:disburse:maker` | Initiate disbursal | `CREDIT_OFFICER` |
| `loan:disburse:checker` | Confirm disbursal | `SR_CREDIT_OFFICER` |
| `loan:restructure:initiate` | Initiate restructuring | `CREDIT_OFFICER` |
| `loan:ots` | Initiate / approve OTS | `SR_CREDIT_OFFICER` |
| `loan:writeoff:initiate` | Recommend write-off | `COMPLIANCE_OFFICER` |
| `loan:writeoff:approve` | Approve write-off | MD / CEO via `SUPER_ADMIN` |
| `loan:cooling_off_cancel` | Cancel within cooling-off window | `BORROWER` only |
| `pii:view:masked` | View masked PII fields | All staff roles |
| `pii:view:full` | View unmasked PII (with audit log entry) | `CREDIT_OFFICER` + approval |
| `pii:export` | Export PII dataset | `COMPLIANCE_OFFICER` + `SUPER_ADMIN` approval |
| `collection:view:assigned` | View assigned DPD accounts | `COLLECTIONS_AGENT` |
| `collection:view:all` | View all delinquent accounts | `COLLECTIONS_MANAGER` |
| `config:charge_master` | Modify charge master | `COMPLIANCE_OFFICER` (maker) |
| `config:roi` | Modify ROI rules | `COMPLIANCE_OFFICER` (maker) |
| `config:pincode` | Modify pincode zones | `COMPLIANCE_OFFICER` (maker) |
| `admin:user` | Create / modify user accounts | `IT_ADMIN` |
| `audit:view` | Read audit logs | `COMPLIANCE_OFFICER`, `AUDITOR` |
| `audit:export` | Export audit logs | `COMPLIANCE_OFFICER` + `SUPER_ADMIN` |
| `report:rbi` | Generate RBI regulatory reports | `FINANCE_OFFICER`, `COMPLIANCE_OFFICER` |
| `integration:cibil` | Pull CIBIL scores | `SYSTEM` (AI engine only) |
| `integration:uidai` | UIDAI Aadhaar API | `SYSTEM` (KYC service only) |

---

## 8. Data Scope Rules (Row-Level Enforcement)

Enforced in LMS API middleware — not left to individual query logic.

### 8.1 Scope Injection Pattern

```
Middleware extracts scope from JWT and injects into DB session:

  1. verifyJWT()          → decode RS256, check signature + expiry
  2. checkRevocation()    → Redis lookup on session_id
  3. injectScope()        → set tenant_id, customer_id, agent_id in request context
  4. enforceRLS()         → SET LOCAL app.tenant_id = jwt.tenant_id in DB session
  5. [route handler runs]
  6. maskPII()            → if role has masked PII scope, apply masking before response
  7. auditLog()           → INSERT INTO audit_trail (always, even on 403)

Every DB query builder appends:
  AND tenant_id = :tenant_id                           -- always, no exceptions
  AND (scope != 'own'      OR customer_id = :cust_id) -- BORROWER role
  AND (scope != 'assigned' OR agent_id = :agent_id)   -- AGENT / COLLECTIONS_AGENT
```

### 8.2 Scope by Role

| Role | `scope` value | Additional DB filter |
|---|---|---|
| `SUPER_ADMIN` | `cross_tenant` | No tenant filter (logged + alerted every query) |
| `COMPLIANCE_OFFICER` / `SR_CREDIT_OFFICER` | `tenant` | `tenant_id = jwt.tenant_id` |
| `CREDIT_OFFICER` | `tenant` | `tenant_id = jwt.tenant_id` |
| `COLLECTIONS_MANAGER` | `tenant` | `tenant_id = jwt.tenant_id` AND `dpd >= 31` |
| `COLLECTIONS_AGENT` | `assigned` | `agent_id = jwt.agent_id` AND `dpd BETWEEN 1 AND 30` |
| `DSA_AGENT` | `assigned` | `loans.agent_id = jwt.agent_id` |
| `OPS_EXECUTIVE` | `tenant` | `tenant_id = jwt.tenant_id` |
| `AUDITOR` | `tenant` | `tenant_id = jwt.tenant_id` (read-only, all tables) |
| `BORROWER` | `own` | `loans.customer_id = jwt.customer_id` |

### 8.3 Tenant Isolation — PostgreSQL RLS

Every LMS table has Row-Level Security enabled. Application connects via a role that has `tenant_id` set as a session variable.

```sql
ALTER TABLE loans ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON loans
  USING (tenant_id = current_setting('app.tenant_id')::UUID);

-- App sets this on every connection checkout from pool:
SET LOCAL app.tenant_id = '<jwt.tenant_id>';
```

A buggy query that omits `WHERE tenant_id = ?` returns zero rows — not wrong-tenant data. RLS is the last line of defence.

`SUPER_ADMIN` connects via a separate DB role (`lms_superadmin`) with `BYPASSRLS`. Every query under this role triggers a real-time Slack + email alert to CTO and Compliance Officer.

---

## 9. PII Access Control & Data Masking

### 9.1 Masking Rules

| Field | Stored Format | Displayed to Staff (default) | Displayed to Customer |
|---|---|---|---|
| Aadhaar Number | AES-256-GCM encrypted | XXXX-XXXX-1234 (last 4) | XXXX-XXXX-1234 (own) |
| PAN Number | AES-256-GCM encrypted | XXXXX1234X | ABCDE1234F (own) |
| Bank Account No. | AES-256-GCM encrypted | XXXXXXXX1234 (last 4) | XXXXXXXX1234 (own) |
| IFSC Code | Plaintext | Visible | Visible |
| Mobile Number | Plaintext (indexed) | +91XXXXXX789 (last 3) | Own number visible |
| Email Address | Plaintext | XXX@domain.com | Own email visible |
| Date of Birth | Plaintext | DD/MM/YYYY | Own DOB visible |
| CIBIL Score | Plaintext | Numeric score (staff) | Own score (own) |
| Full Address | Plaintext | City + Pincode only | Own address visible |

### 9.2 PII Vault Architecture

```
  Regular PostgreSQL DB          PII Vault DB (Firewalled Schema)
  ─────────────────────          ──────────────────────────────────
  loan_id · status · dates       aadhaar_encrypted  (AES-256-GCM)
  risk_score · band              pan_encrypted      (AES-256-GCM)
  outstanding_amount             bank_acc_encrypted (AES-256-GCM)
  tenant_id · agent_id           dob · name · address
                                 selfie_path (S3 signed URL)
  ← Regular staff can query      ← Separate encryption keys (AWS KMS)
                                    Separate DB user (least privilege)
                                    VPC firewall (IP whitelist only)
                                    Every access requires audit log entry
```

### 9.3 Unmasked PII Access Flow

```
  Staff requests unmasked PII (e.g. for recovery call)
         │
         ▼
  System prompts: "State business justification" (min 50 chars)
         │
         ▼
  INSERT into pii_access_requests:
    requester_id, loan_id, field_requested, justification, timestamp
         │
         ▼
  Auto-approved if: role = CREDIT_OFFICER or above
                AND loan is in active underwriting or recovery stage
  Escalated to Compliance if: unusual access pattern detected
         │
         ▼
  Unmasked data shown for 60 seconds only (auto-hides)
  Cannot be copy-pasted (UI restriction)
  Full audit log entry created with pii_accessed = TRUE
```

---

## 10. Customer Consent Framework

RBI DLG 2022 and DPDP Act 2023 require explicit, informed, granular consent before any data collection or processing.

### 10.1 Consent Events

| # | Event | Consent Summary | Withdrawal |
|---|---|---|---|
| C1 | Registration & Profile | Consent to collect name, income, purpose | Delete account (before KYC) |
| C2 | KYC — Aadhaar OTP | Authorize UIDAI to share Aadhaar XML with NBFC | Cannot withdraw post-KYC |
| C3 | PAN Verification | Authorize NSDL to verify PAN | Cannot withdraw post-KYC |
| C4 | Credit Bureau Pull | Authorize CIBIL / Equifax pull | Cannot withdraw post-pull |
| C5 | Bank Statement Upload | Consent to processing bank statement for income verification | Can delete statement post-decision |
| C6 | e-Mandate (eNACH / UPI Autopay) | Authorize auto-debit of ₹[EMI] on [date] monthly | Cancel mandate via app or bank |
| C7 | Loan Agreement e-Sign | Accept KFS and Loan Agreement terms | Cooling-off exit (3 business days) |
| C8 | Data Sharing with DSA | Consent to DSA partner being informed of loan status | Withdraw (DSA untags from account) |
| C9 | Marketing Communications | Consent to receive offers via SMS/WhatsApp | Opt-out via app at any time |
| C10 | Data Retention Post-Closure | Consent to 7-year retention for regulatory purposes | Cannot withdraw (RBI mandate) |

### 10.2 `consent_log` Table

```sql
consent_log (
  id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID         NOT NULL REFERENCES users(id),
  consent_type        VARCHAR(5)   NOT NULL,     -- 'C1' through 'C10'
  consent_text_hash   VARCHAR(64)  NOT NULL,     -- SHA-256 of exact text shown to user
  consented           BOOLEAN      NOT NULL,
  timestamp           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  ip_address          INET         NOT NULL,
  device_fingerprint  VARCHAR(200),
  channel             VARCHAR(20)  NOT NULL,     -- 'APP' | 'WEB' | 'AGENT_ASSISTED'
  version             VARCHAR(10)  NOT NULL      -- consent template version e.g. 'v2.1'
);
-- INSERT-only. No UPDATE or DELETE permitted (RLS enforced).
```

### 10.3 DPDP Act 2023 — Customer Data Rights

| Right | Customer Action | NBFC Response Time | Exception |
|---|---|---|---|
| Right to Access | Request copy of all personal data | 30 days | — |
| Right to Correction | Request correction of inaccurate data | 30 days | — |
| Right to Erasure | Request deletion of personal data | 30 days | Cannot erase if loan active or within 7-year RBI retention |
| Withdraw Consent (C9 marketing) | Opt-out in app | Immediate | C2–C7 irrevocable post-execution |
| Grievance Redressal | Raise complaint with Data Protection Officer | Acknowledge 48h; resolve 30 days | — |

### 10.4 Data Protection Officer (DPO)

Mandatory under DPDP Act 2023 for significant data fiduciaries.

- Monitor DPDP Act compliance
- Handle data principal requests (access, correction, erasure)
- Liaise with Data Protection Board of India (DPBI)
- Conduct annual data audit
- Report data breaches to DPBI within **72 hours**
- Maintain Records of Processing Activities (ROPA)

---

## 11. API Gateway Authorization

### 11.1 Request Authorization Flow

```
  Incoming API Request
         │
         ▼
  API Gateway (Kong / AWS API GW):
    1. Validate JWT signature (RS256 public key)
    2. Check token expiry (exp claim)
    3. Extract role + permissions[] from claims
    4. Match request (method + path) against required permission scope
    5. Verify tenant_id matches resource being accessed
    6. Check IP binding (for staff tokens)
    7. Rate limit check (per role, per endpoint)
         │
         ├── ANY CHECK FAILS → 401 / 403
         │                     audit_trail INSERT (failed access logged)
         │
         └── ALL PASS → Route to LMS service
                        Inject headers: X-User-Id, X-Role, X-Tenant-Id, X-Session-Id
```

### 11.2 Rate Limits by Role

| Role | Global Rate Limit | Sensitive Endpoints | Burst |
|---|---|---|---|
| `BORROWER` | 60 req/min | 5 req/min (OTP, mandate) | 10 |
| `DSA_AGENT` | 120 req/min | 10 req/min | 20 |
| `CREDIT_OFFICER` | 300 req/min | 30 req/min | 50 |
| `COLLECTIONS_AGENT` | 200 req/min | 20 req/min | 30 |
| `SYSTEM` (AI engine) | 1,000 req/min | 500 req/min | 200 |
| `INTEGRATION` (CIBIL etc.) | 100 req/min | 100 req/min | 10 |

### 11.3 Admin Route IP Restriction

```yaml
# Admin-grade routes require office network or VPN
routes matching: /api/v1/lms/admin/*, /write-off, /rate-reset, /bureau-submit
  ip-restriction:
    allow: [office_cidr_block, vpn_cidr_block]
    deny: all others → 403 + security alert
```

---

## 12. Session Management

### 12.1 Session Policies

| Policy | Customer | Staff | SUPER_ADMIN |
|---|---|---|---|
| Access token TTL | 15 minutes | 15 minutes | 15 minutes |
| Session / refresh TTL | 7 days | 8 hours | 4 hours |
| Idle timeout | 10 minutes | 30 minutes | 15 minutes |
| Concurrent sessions | 2 (mobile + web) | 1 (single device) | 1 (with MFA refresh) |
| Re-auth for sensitive action | OTP re-verify for e-sign / mandate | MFA re-verify for disbursal | Hardware key |
| IP change detection | Warn + re-verify OTP | Block + re-auth | Block + alert Compliance |

### 12.2 Account Lockout Policy

```
  Customer (Mobile OTP):
    Max failed OTPs:     3 per session
    Lockout:             30 minutes
    Max resends:         3 per hour per mobile
    After 5 lockouts:    24-hour ban + manual review flag

  Staff (Password + MFA):
    Max failed logins:   5 consecutive
    Lockout:             15 minutes (auto-unlock)
    After 3 lockouts:    Account suspended → IT_ADMIN must unlock
    Suspicious login:    New country/city → Block + email alert
```

### 12.3 Forced Revocation (Employee Termination)

```
  HR triggers: DELETE /auth/sessions?user_id={id}
    → All active sessions purged from Redis
    → All refresh tokens deleted
    → User marked inactive in users table
    → Audit event: 'forced_revocation' with reason
    → User cannot log in until reactivated by IT_ADMIN
```

---

## 13. Audit Trail

RBI IT Framework (2017) Section 8 + DPDP Act 2023 Section 8(7) require complete, tamper-proof log of all data access and mutations.

### 13.1 `audit_trail` Table

```sql
audit_trail (
  id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID,                       -- NULL for SUPER_ADMIN cross-tenant actions
  actor_id        UUID         NOT NULL,
  actor_role      VARCHAR(50)  NOT NULL,
  session_id      VARCHAR(100) NOT NULL,
  event_type      VARCHAR(100) NOT NULL,
    -- 'loan:read' | 'payment:write' | 'write_off:initiate' | 'pii:access'
    -- | 'login' | 'logout' | 'token_refresh' | 'forced_revocation'
    -- | 'master_change:initiate' | 'master_change:approve' | 'access_denied'
    -- | 'consent:given' | 'consent:withdrawn' | 'pii:export'
  resource_type   VARCHAR(50),
  resource_id     UUID,
  http_method     VARCHAR(10),
  endpoint        VARCHAR(200),
  before_state    JSONB,                      -- for config / master table changes
  after_state     JSONB,
  request_ip      INET         NOT NULL,
  device_info     JSONB,
  status_code     INTEGER      NOT NULL,      -- 200 / 403 / 404 — failures always logged
  result          VARCHAR(20)  NOT NULL,      -- 'SUCCESS' | 'FAILURE' | 'BLOCKED'
  failure_reason  TEXT,
  pii_accessed    BOOLEAN      NOT NULL DEFAULT FALSE,
  request_id      UUID,                       -- API traceability
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Enforce immutability
CREATE RULE no_update_audit AS ON UPDATE TO audit_trail DO INSTEAD NOTHING;
CREATE RULE no_delete_audit AS ON DELETE TO audit_trail DO INSTEAD NOTHING;
-- Partitioned by month for query performance
```

### 13.2 What is Always Logged

| Event | Additional fields |
|---|---|
| Every API call (success or failure) | actor_id, role, endpoint, method, resource_id, status_code, IP |
| PII field access | `pii_accessed = TRUE`; field name; loan/customer resource_id |
| Login / logout / token refresh | session_id, IP, user_agent |
| Forced revocation | actor_id, revoked_by, reason |
| Master table change | resource_type, resource_id, before_state, after_state |
| Consent given / withdrawn | consent_type (C1–C10); consent_text_hash |
| Access denied (403) | Always logged; repeated 403s → security alert |
| Cross-tenant access | Separate `cross_tenant_access_log` + real-time CTO + Compliance alert |

### 13.3 Audit Log Retention

```
  Active (searchable in UI):  2 years
  Archive (S3 Glacier):       7 years total  (RBI mandate)
  Destruction:                After 7 years, with documented destruction certificate

  Integrity: Hash chain — each entry hashes the previous entry (tamper detection)
  Verification: Daily hash verification cron; alerts Compliance on mismatch
```

---

## 14. Privileged Access Management (PAM)

RBI IT Framework (2017) Section 10.

| Control | Implementation |
|---|---|
| `SUPER_ADMIN` login | TOTP MFA + FIDO2 hardware key + IP whitelist; break-glass OTP for production |
| `SR_CREDIT_OFFICER` + `COMPLIANCE_OFFICER` | TOTP MFA mandatory |
| All other staff | TOTP MFA mandatory |
| Production DB access | No direct DB access for any role except `SUPER_ADMIN` break-glass; all access via API |
| SSH / server access | Bastion host only; session recorded; auto-terminated after 4 hours |
| API keys / secrets | AWS Secrets Manager; rotated every 30 days; zero hardcoded secrets |
| Webhook secrets | AWS Secrets Manager; never in env vars or config files |
| `SUPER_ADMIN` actions | Real-time Slack + email to CTO + Compliance; logged to immutable trail |

---

## 15. Third-Party & Integration Authorization

| Integration | Auth Method | IP Whitelist | Data Shared | Audit Logged |
|---|---|---|---|---|
| CIBIL / Equifax / Experian | API Key + Secret | Yes (bureau IP range) | PAN + DOB | Yes |
| UIDAI (Aadhaar) | PKI Cert + mTLS | Yes (UIDAI endpoint) | Aadhaar + OTP | Yes |
| NSDL (PAN verify) | API Key | Yes | PAN + name | Yes |
| NPCI (eNACH) | mTLS + NPCI cert | Yes | Account + mandate details | Yes |
| Digio (eNACH API) | API Key + HMAC-SHA256 | Yes | Mandate details | Yes |
| Razorpay (UPI Autopay / Payment Links) | API Key + HMAC-SHA256 webhook | Yes | Amount + account | Yes |
| Tata DLT (SMS) | API Key | Yes | Mobile + OTP text | Yes |
| Zoho ZeptoMail | API Token | Yes | Email + NOC PDF | Yes |
| AWS S3 | IAM Role (AWS STS) | VPC endpoint only | Signed URL access | Yes (CloudTrail) |

### 15.1 DSA Partner Authorization

```
  DSA onboarding:
    1. Agreement signed (physical + DocuSign)
    2. GST registration verified
    3. Aadhaar + PAN of DSA owner verified
    4. API credentials issued (if API-integrated DSA)
    5. Scope: loan:create, loan:view:own_attributed ONLY
    6. Data residency agreement signed (no PII export to DSA)

  DSA portal — data visible:   Lead status, conversion rate, commission earned
  DSA portal — NOT visible:    Customer PAN, Aadhaar, bank account, CIBIL score
```

---

## 16. Emergency (Break-Glass) Access

```
  Break-Glass Procedure:
    1. SUPER_ADMIN requests break-glass via OOB channel (phone call to MD — recorded)
    2. MD + Compliance Officer issue verbal approval
    3. IT_ADMIN enables break-glass: time-limited (max 2 hours), full-access token
    4. ALL actions during break-glass:
         → Logged in real-time to immutable audit_trail
         → Streamed live to Compliance Officer's dashboard
         → Reviewed within 24 hours by Compliance Officer
    5. Token auto-expires after 2 hours (non-renewable)
    6. Post-incident report filed within 48 hours
    7. RBI notified if incident involves customer data breach (within 6 hours)
```

---

## 17. Periodic Access Review

RBI IT Framework (2017) mandates formal periodic review of user access rights.

| Frequency | Scope | Responsible |
|---|---|---|
| Monthly | All `SUPER_ADMIN` and `IT_ADMIN` accounts | Compliance Officer |
| Quarterly | All staff roles and permissions | Compliance Officer + IT_ADMIN |
| Semi-annually | All integration API keys (revoke unused) | IT_ADMIN |
| Annually | Full RBAC policy review vs. Board-approved credit policy | Compliance Officer + Board |
| On Event | Any role change, resignation, or security incident | IT_ADMIN (within 24 hours) |

### 17.1 Joiner-Mover-Leaver Policy

```
  JOINER (new employee):
    → IT_ADMIN creates account with minimum required role
    → Maker-Checker approval for any role above CREDIT_ANALYST
    → Day 1: mandatory security training before access activated

  MOVER (role change / promotion):
    → Old permissions revoked before new permissions granted (no overlap window)
    → All active sessions terminated
    → Maker-Checker approval for any privilege escalation

  LEAVER (resignation / termination):
    → All access revoked within 1 hour of HR notification
    → All active sessions force-terminated
    → API keys revoked immediately
    → Offboarding checklist signed by IT_ADMIN + Compliance Officer
    → Audit log preserved per retention policy
```

---

## 18. Compliance Summary

| Regulation | Requirement | Implementation |
|---|---|---|
| RBI IT Framework 2017 — S7.3 | Maker-checker for critical transactions | `pending_approvals` table; same-user approval blocked at DB level |
| RBI IT Framework 2017 — S6 | Short sessions for privileged users | 8-hour max for staff; 4-hour for SUPER_ADMIN; 15-min access token |
| RBI IT Framework 2017 — S8 | Immutable audit trail for all access | `audit_trail` INSERT-only; hash chain; 7-year retention |
| RBI IT Framework 2017 — S10 | Privileged access management | MFA for all staff; FIDO2 for admins; no direct DB; PAM controls |
| RBI Cyber Security Framework 2021 | Role-based access control; least privilege | RBAC with explicit permission list in JWT; RLS on all tables |
| RBI DLG 2022 | Customer right to access own data | `BORROWER` scope: self-service read on own loans only |
| RBI DLG 2022 | Cooling-off cancellation right | `POST /:id/cancel-cooling-off`; `BORROWER` only; 403 after window |
| RBI DLG 2022 | Agent / DSA data isolation | `assigned` scope; agent sees only their own portfolio |
| RBI DLG 2022 — LSA | Board-approved loan sanctioning limits | LSA matrix enforced via permission scopes in JWT |
| RBI Master Direction NBFC 2016 | No unauthorized access to borrower PII | PII masking for non-owner staff; RLS on all tables |
| RBI Prudential Norms | Write-off requires board approval | `board_resolution_ref` mandatory; two-step approve API; maker-checker |
| DPDP Act 2023 — S6 | Purpose limitation | Every PII access logged with event_type (purpose) |
| DPDP Act 2023 — S11 | Informed consent before data collection | `consent_log` table; C1–C10 events; INSERT-only |
| DPDP Act 2023 — S13 | Data principal rights (access, correction, erasure) | Customer self-service APIs; DPO handles erasure requests |
| DPDP Act 2023 — S8(6) | Breach notification to DPBI within 72 hours | Anomaly detection pipeline; DPO notified; RBI within 6 hours |
| IT Act 2000 — S43A | Reasonable security practices for sensitive data | AES-256-GCM PII; RS256 JWT; HMAC webhooks; mTLS for UIDAI/NPCI |
| IT (SRPS) Rules 2011 | Mandatory IS policy, access control, audit logs | This document + audit_trail table |
| NPCI eMandate Guidelines | Two-factor authentication before mandate registration | MFA verified claim in JWT; `C6` consent before mandate API call |

---

## 19. Quick Reference

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  LOAN SANCTIONING LIMITS (LSA):
    ≤ ₹25,000    → AI Auto  (Risk Band A/B, all checks pass)
    ≤ ₹1,00,000  → CREDIT_OFFICER
    ≤ ₹2,00,000  → SR_CREDIT_OFFICER
    Restructure  → Credit Committee (Maker + Checker)
    Write-off ≤ ₹1L → Compliance + MD/CEO
    Write-off > ₹1L → Board Resolution (board_resolution_ref mandatory)

  MAKER-CHECKER MANDATORY FOR:
    Disbursal > ₹50K | Restructuring | OTS | Write-off
    charge_master / product_master change | ROI rule change
    User privilege change | PII dataset export

  TOKEN TTL:
    Access Token:       15 minutes (all roles)
    Staff Session:      8 hours
    SUPER_ADMIN:        4 hours
    Refresh Token:      7 days customer / 8 hours staff (single-use)
    Service Token:      5 minutes

  PII MASKING (default for all staff):
    Aadhaar → XXXX-XXXX-1234  |  PAN → XXXXX1234X
    Bank A/c → XXXXXXXX1234   |  Mobile → +91XXXXXX789

  CONSENT REQUIRED BEFORE:
    C2: Aadhaar OTP  |  C4: CIBIL pull  |  C6: eNACH setup
    C7: Loan Agreement e-sign

  AUDIT LOG:
    Every write + every PII access logged (immutable, hash chain)
    Retention: 2 years active | 7 years archive (RBI)

  SESSION LOCKOUT:
    Customer: 3 failed OTPs → 30-min lock
    Staff:    5 failed logins → 15-min lock → 3rd lockout → suspended

  BREAK-GLASS:
    Max 2 hours | MD verbal approval | All actions streamed live to Compliance
    RBI notified within 6 hours if customer data involved
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

*Alpha LMS | LMS Authorization & Access Control Framework v2.0 | Confidential*
*Compliant with: RBI DLG 2022 · RBI Master Direction KYC 2023 · RBI IT Framework for NBFCs 2017 · RBI Cyber Security Framework 2021 · DPDP Act 2023 · IT Act 2000 (Sec. 43A) · IT (SRPS) Rules 2011 · NPCI eMandate Guidelines*
