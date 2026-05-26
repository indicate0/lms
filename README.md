# Loan Management System (LMS)
### True Loan Bazaar (TLB) — BP Securities NBFC

> Post-disbursal loan lifecycle management for a regulated Indian micro-lending platform.
> Compliant with RBI Digital Lending Guidelines 2022, Penal Charges Circular (Jan 2024),
> NPA Prudential Norms, SARFAESI Act 2002, CGST Act 2017, and DPDP Act 2023.

---

## Service Scope

The LMS owns the loan lifecycle **from the moment a loan is disbursed until it is fully repaid,
foreclosed, settled, or written off.**

```
LOS (Loan Origination System)
  └── loan.disbursed event
          │
          ▼
    LMS takes ownership ────────────────────────────────────────────┐
          │                                                         │
          │  Repayment schedule generation                          │
          │  Daily interest accrual                                 │
          │  EMI auto-debit (eNACH / UPI Autopay)                  │
          │  Bounce handling & retry                                │
          │  DPD tracking & SMA classification                      │
          │  Penalty & penal charge engine                          │
          │  NPA classification & provisioning                      │
          │  NPA upgrade (de-classification)                        │
          │  Foreclosure & part-prepayment                          │
          │  Loan restructuring & OTS settlement                    │
          │  NOC generation (72-hr SLA)                             │
          │  Credit bureau reporting (CIBIL / Equifax / Experian)   │
          │  RBI regulatory reporting (DNBS-02, CRILC)              │
          │  Collection escalation (tele-call → agency → legal)     │
          │  Waiver governance (tiered maker-checker approval)       │
          │  Write-off (board approval) & recovery posting          │
          │  Float rate reset handler                               │
          │  Cross-sell eligibility engine                          │
          └────────────────────────────────────────────────────────┘
```

### What LMS does NOT own

| Concern | Owner |
|---|---|
| Loan application, underwriting, credit scoring | LOS |
| Interest rate assignment (ROI) | LOS / AI Risk Engine |
| KYC, Aadhaar, PAN verification | LOS |
| Processing fee deduction at disbursal | LOS |
| DSA commission payouts | DSA Engine (shared service) |
| Grievance ticket management | Grievance Service (shared service) |
| Customer onboarding | LOS |

---

## Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| **Backend API** | Python 3.12 + FastAPI | Async, native Decimal arithmetic, auto OpenAPI docs |
| **Calculation engines / crons** | Python + Celery Beat | Safe financial arithmetic, APScheduler for 18 cron jobs |
| **Frontend** | React 18 + TypeScript | Strict TypeScript throughout — no `any`, interfaces on every prop, API response, and store slice |
| **Build tool** | Vite | Fast HMR, native ESM, optimised production builds |
| **State management** | Redux Toolkit (RTK) | Predictable global state; integrates with RTK Query for server state |
| **API / server state** | RTK Query | Auto caching, background re-fetch, optimistic updates; replaces manual axios boilerplate |
| **Forms** | React Hook Form + Zod | Performant uncontrolled forms; Zod schemas shared with TypeScript types for runtime validation |
| **UI components** | shadcn/ui + Tailwind CSS | Accessible, unstyled components + Tailwind utility classes; no CSS files |
| **Database** | PostgreSQL 15 (RDS Multi-AZ) | ACID, RLS for multi-tenant isolation, range partitioning |
| **ORM / migrations** | SQLAlchemy 2.0 + Alembic | Type-safe queries, versioned schema migrations |
| **Cache** | Redis 7 (ElastiCache) | DPD cache, idempotency keys, circuit breaker state, config TTL |
| **Message queue** | Apache Kafka (AWS MSK) | Event-driven async — 17 topics + DLQ pairs |
| **Webhook service** | Node.js 20 + Express | Digio eNACH + Razorpay inbound webhooks (pure I/O) |
| **PDF service** | Node.js 20 + Puppeteer | NOC, account statements, RBI reports |
| **Object storage** | AWS S3 (ap-south-1) | Documents: NOC, KFS, statements, RBI reports |
| **Infrastructure** | AWS EKS (Kubernetes) | Auto-scaling pods; K8s CronJobs for 18 background jobs |
| **Secrets** | AWS Secrets Manager | Digio, Razorpay, bureau API credentials |
| **Monitoring** | Datadog APM + Sentry | Request tracing, error tracking, cron health |

---

## Repository Structure

```
lms/
├── backend/
│   ├── app/
│   │   ├── api/                  # FastAPI route handlers (one file per module)
│   │   │   ├── loans.py          # GET/POST /loans
│   │   │   ├── repayments.py     # payment posting, webhooks
│   │   │   ├── mandates.py       # eNACH / UPI mandate management
│   │   │   ├── foreclosure.py    # quote + payment
│   │   │   ├── prepayment.py     # eligibility + initiation
│   │   │   ├── restructure.py    # maker-checker restructuring
│   │   │   ├── ots.py            # OTS settlement workflow
│   │   │   ├── documents.py      # NOC, KFS, statements
│   │   │   ├── admin.py          # dashboard, reports, write-off
│   │   │   └── health.py         # /health /ready /metrics
│   │   │
│   │   ├── engines/              # Core calculation engines (pure functions)
│   │   │   ├── schedule.py       # EMI generation (reducing, flat, bullet)
│   │   │   ├── accrual.py        # daily interest accrual
│   │   │   ├── dpd.py            # DPD + SMA classification
│   │   │   ├── penalty.py        # late payment + penal interest
│   │   │   ├── payment.py        # waterfall allocation engine
│   │   │   ├── npa.py            # NPA classify + upgrade
│   │   │   ├── foreclosure.py    # foreclosure quote + processing
│   │   │   ├── prepayment.py     # part-prepayment + schedule recalc
│   │   │   ├── bounce.py         # bounce charge + retry logic
│   │   │   ├── closure.py        # loan closure detector
│   │   │   └── writeoff.py       # write-off + recovery
│   │   │
│   │   ├── jobs/                 # Celery Beat tasks (18 cron jobs)
│   │   │   ├── daily.py          # accrual, DPD, penalty, NPA (00:05–01:30)
│   │   │   ├── collection.py     # reminders, escalation, agency (08:00–11:30)
│   │   │   ├── monthly.py        # bureau, RBI return, statement, NPA upgrade
│   │   │   └── noc.py            # NOC generation queue (every 30 min)
│   │   │
│   │   ├── models/               # SQLAlchemy ORM models (one per table)
│   │   ├── schemas/              # Pydantic request / response schemas
│   │   ├── services/             # Business logic layer (between API and engines)
│   │   │   ├── digio.py          # eNACH API client (circuit breaker wrapped)
│   │   │   ├── razorpay.py       # UPI Autopay + payment links
│   │   │   ├── bureau.py         # CIBIL / Equifax / Experian submission
│   │   │   ├── notification.py   # Kafka event publisher to Notification Svc
│   │   │   └── pdf.py            # HTTP client to PDF service
│   │   │
│   │   └── core/
│   │       ├── config.py         # settings from env vars
│   │       ├── database.py       # SQLAlchemy async engine + session
│   │       ├── redis.py          # Redis client + circuit breaker helpers
│   │       ├── kafka.py          # Kafka producer + consumer setup
│   │       ├── security.py       # JWT decode, RBAC dependency
│   │       └── errors.py         # standardised error envelope middleware
│   │
│   ├── migrations/               # Alembic migration files
│   │   ├── versions/
│   │   └── env.py
│   │
│   ├── tests/
│   │   ├── unit/                 # engine logic tests (no DB)
│   │   └── integration/          # API tests (test DB)
│   │
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── alembic.ini
│   ├── celeryconfig.py
│   ├── Dockerfile
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── store.ts          # Redux store setup (typed RootState + AppDispatch)
│   │   │   └── hooks.ts          # useAppDispatch / useAppSelector typed wrappers
│   │   │
│   │   ├── api/                  # RTK Query API slices (one per LMS module)
│   │   │   ├── baseApi.ts        # createApi with baseQuery + JWT inject
│   │   │   ├── loansApi.ts       # getLoan, getSchedule, getLedger, getOutstanding
│   │   │   ├── repaymentsApi.ts  # postPayment, getNextDue, getOverdue
│   │   │   ├── foreclosureApi.ts # getQuote, initiateForeclosure
│   │   │   ├── prepaymentApi.ts  # checkEligibility, getQuote, initiate
│   │   │   ├── adminApi.ts       # dashboard, DPD report, NPA list, write-off
│   │   │   └── masterApi.ts      # charge_master, product_master, tenant_configs
│   │   │
│   │   ├── features/             # RTK slices for local/UI state (not server state)
│   │   │   ├── auth/
│   │   │   │   ├── authSlice.ts  # JWT token, user role, tenant_id
│   │   │   │   └── AuthGuard.tsx # role-based route protection
│   │   │   └── ui/
│   │   │       └── uiSlice.ts    # sidebar open, active filters, pagination state
│   │   │
│   │   ├── pages/
│   │   │   ├── dashboard/        # DPD buckets, NPA count, collection rate
│   │   │   ├── loans/            # Loan list + detail view
│   │   │   │   ├── LoanList.tsx
│   │   │   │   └── LoanDetail.tsx
│   │   │   ├── repayments/       # Payment history + manual payment form
│   │   │   ├── foreclosure/      # Quote view + payment initiation
│   │   │   ├── collection/       # DPD queue, tele-call queue, agency assignments
│   │   │   ├── reports/          # RBI return, bureau queue, NPA list
│   │   │   └── settings/         # Master tables (CRUD with maker-checker forms)
│   │   │
│   │   ├── components/           # Shared UI components (shadcn/ui based)
│   │   │   ├── forms/            # React Hook Form + Zod schema forms
│   │   │   │   ├── PaymentForm.tsx
│   │   │   │   ├── WaiverForm.tsx
│   │   │   │   └── RestructureForm.tsx
│   │   │   ├── tables/           # Typed data tables with pagination
│   │   │   ├── charts/           # DPD trend, collection charts
│   │   │   └── layout/           # Sidebar, header, breadcrumbs
│   │   │
│   │   ├── hooks/                # Custom typed React hooks
│   │   │   ├── useAuth.ts        # reads authSlice; exposes role/permissions
│   │   │   └── usePagination.ts  # RTK Query pagination helper
│   │   │
│   │   └── types/                # TypeScript interfaces (source of truth)
│   │       ├── loan.ts           # Loan, RepaymentSchedule, LoanLedger
│   │       ├── payment.ts        # Payment, PaymentAllocation
│   │       ├── api.ts            # ApiSuccessResponse<T>, ApiErrorResponse, Paginated<T>
│   │       └── enums.ts          # LoanStatus, EntryType, SmaCategory, Role
│   │
│   ├── public/
│   ├── index.html                # Vite entry point
│   ├── vite.config.ts
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── tailwind.config.ts
│   ├── Dockerfile
│   └── .env.example
│
├── webhook-service/              # Node.js — Digio + Razorpay inbound webhooks
│   ├── src/
│   │   ├── handlers/
│   │   │   ├── digio.js          # eNACH debit success/failure
│   │   │   └── razorpay.js       # UPI Autopay + payment link
│   │   ├── middleware/
│   │   │   └── hmac.js           # HMAC-SHA256 signature verification
│   │   └── index.js
│   ├── package.json
│   └── Dockerfile
│
├── pdf-service/                  # Node.js Puppeteer — NOC, statements, reports
│   ├── src/
│   │   ├── templates/            # Handlebars HTML templates
│   │   │   ├── noc.html
│   │   │   ├── statement.html
│   │   │   └── rbi_return.html
│   │   └── index.js
│   ├── package.json
│   └── Dockerfile
│
├── docs/                         # Canonical design documents
│   ├── LMS_HLD.md
│   ├── LMS_LLD.md
│   ├── LMS_AUTH.md
│   ├── LMS_CALCULATIONS.md
│   ├── TLB_Calculations_and_Charges.md
│   ├── TLB_Payment_Flows_and_Calculations.md
│   └── TLB_Collection_and_Delinquency.md
│
├── archive/                      # Version history (v1–v4 design docs)
├── docker-compose.yml            # Local dev: postgres, redis, kafka, all services
├── docker-compose.test.yml       # CI: isolated test DB
└── README.md
```

---

## Implementation Phases

| Phase | Weeks | Deliverables |
|---|---|---|
| **1** | 1–4 | DB migrations, loan account API, schedule generator, manual payment posting, basic admin dashboard |
| **2** | 5–8 | eNACH / UPI webhook handlers, bounce engine, DPD engine, penalty engine, pre-debit notification cron |
| **3** | 9–12 | Foreclosure, part-prepayment, NOC generator, NPA classifier, monthly bureau reporting |
| **4** | 13–16 | Loan restructuring, OTS settlement, RBI monthly return, CRILC, reconciliation engine, waiver governance |
| **5** | 17–20 | Collection agency integration, legal proceedings tracker, SARFAESI pipeline, float rate reset |
| **6** | Ongoing | Cross-sell engine, BI dashboards, provisioning automation, Ombudsman return |

---

## Getting Started

### Prerequisites

- Python 3.12
- Node.js 20
- Docker + Docker Compose
- AWS CLI (for S3/Secrets Manager in staging)

### Local Development

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd lms

# 2. Start infrastructure (PostgreSQL, Redis, Kafka, Zookeeper)
docker-compose up -d postgres redis kafka

# 3. Backend setup
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env        # fill in local values

# Run DB migrations
alembic upgrade head

# Seed master tables
python -m app.scripts.seed

# Start API server
uvicorn app.main:app --reload --port 8000

# Start Celery worker (separate terminal)
celery -A app.jobs worker --loglevel=info

# Start Celery Beat scheduler (separate terminal)
celery -A app.jobs beat --loglevel=info

# 4. Frontend setup (separate terminal)
cd ../frontend
npm install
cp .env.example .env.local   # set VITE_API_URL=http://localhost:8000
npm run dev                  # runs on http://localhost:5173 (Vite HMR)

# 5. Webhook service (separate terminal)
cd ../webhook-service
npm install
npm run dev                  # runs on http://localhost:3001

# 6. PDF service (separate terminal)
cd ../pdf-service
npm install
npm run dev                  # runs on http://localhost:3002
```

### Running Tests

```bash
# Backend unit tests (no DB required)
cd backend
pytest tests/unit

# Backend integration tests (spins up test DB via docker-compose.test.yml)
pytest tests/integration

# Frontend
cd frontend
npm test
```

---

## Environment Variables

### Backend (`backend/.env`)

```env
# Database
DATABASE_URL=postgresql+asyncpg://lms:password@localhost:5432/lms_dev
DATABASE_POOL_SIZE=20

# Redis
REDIS_URL=redis://localhost:6379/0

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_CONSUMER_GROUP=lms-service

# JWT (RS256 — public key only; private key is in LOS / Auth service)
JWT_PUBLIC_KEY_PATH=./keys/public.pem

# AWS
AWS_REGION=ap-south-1
AWS_S3_BUCKET=tlb-lms-documents
AWS_SECRETS_MANAGER_PREFIX=tlb/lms

# Integrations (loaded from Secrets Manager in prod/uat; set directly for dev)
DIGIO_API_KEY=
DIGIO_API_SECRET=
DIGIO_WEBHOOK_SECRET=
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=

# Service URLs
PDF_SERVICE_URL=http://localhost:3002
NOTIFICATION_SERVICE_URL=http://localhost:4000

# App
APP_ENV=dev                 # dev | uat | prod
LOG_LEVEL=INFO
TENANT_ID=                  # set for single-tenant local dev
```

### Frontend (`frontend/.env.local`)

```env
VITE_API_URL=http://localhost:8000
VITE_APP_ENV=dev            # dev | uat | prod
```

---

## Frontend Architecture

### State Management

```
Server state (API data)  →  RTK Query (loansApi, repaymentsApi, adminApi …)
Global UI / auth state   →  Redux Toolkit slices (authSlice, uiSlice)
Form state               →  React Hook Form (never in Redux)
Local component state    →  useState / useReducer
```

### RTK Query Pattern

Every LMS module has its own API slice injected into the base API.

```ts
// src/api/loansApi.ts
import { baseApi } from './baseApi'
import type { Loan, Paginated, LoanLedgerEntry } from '@/types/loan'

export const loansApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getLoan: builder.query<Loan, string>({
      query: (id) => `/loans/${id}`,
      providesTags: (_result, _err, id) => [{ type: 'Loan', id }],
    }),
    getLedger: builder.query<Paginated<LoanLedgerEntry>, { id: string; page: number }>({
      query: ({ id, page }) => `/loans/${id}/ledger?page=${page}&limit=50`,
    }),
  }),
})

export const { useGetLoanQuery, useGetLedgerQuery } = loansApi
```

### React Hook Form + Zod Pattern

Zod schema is the single source of truth — it drives both runtime validation and the TypeScript type.

```ts
// src/components/forms/PaymentForm.tsx
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'

const paymentSchema = z.object({
  amount:  z.number().positive().multipleOf(0.01),
  channel: z.enum(['upi_manual', 'neft', 'imps', 'rtgs']),
  utr_ref: z.string().min(6).max(100),
})

type PaymentFormValues = z.infer<typeof paymentSchema>  // derived — never duplicated

export function PaymentForm({ loanId }: { loanId: string }) {
  const { register, handleSubmit, formState: { errors } } = useForm<PaymentFormValues>({
    resolver: zodResolver(paymentSchema),
  })
  // ...
}
```

---

## TypeScript Conventions

Strict TypeScript is enforced everywhere. `"strict": true` in `tsconfig.json`. No `any`.

### Rules

| Rule | Detail |
|---|---|
| No `any` | Use `unknown` and narrow, or define a proper interface |
| API response types | Every RTK Query endpoint has explicit `<ResponseType, ArgType>` generics |
| Enums | Use `const` enums in `src/types/enums.ts`; import where needed |
| Props | Every component has an explicit `interface Props {}` — no inline object types |
| Event handlers | Type event parameters explicitly: `(e: React.ChangeEvent<HTMLInputElement>)` |
| Zod + RHF | Zod schema → `z.infer<typeof schema>` → pass to `useForm<T>` — never duplicate types |
| Store slices | `RootState` and `AppDispatch` exported from `store.ts`; use typed hooks from `hooks.ts` |

### Typed API Response Envelope

Matches the backend standardised error envelope exactly.

```ts
// src/types/api.ts
export interface ApiSuccess<T> {
  success: true
  data: T
  request_id: string
  timestamp: string
}

export interface ApiError {
  success: false
  error_code: string
  message: string
  request_id: string
  timestamp: string
}

export interface Paginated<T> {
  success: true
  data: T[]
  pagination: {
    page: number
    limit: number
    total: number
    has_more: boolean
  }
  request_id: string
  timestamp: string
}
```

---

## API Documentation

FastAPI auto-generates interactive docs. Once the backend is running:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI JSON:** `http://localhost:8000/openapi.json`

All endpoints require a `Bearer` JWT token except `/health` and `/ready`.

---

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Financial arithmetic | Python `Decimal` | No floating-point rounding errors on monetary values |
| Multi-tenancy | PostgreSQL RLS + `tenant_id` on every table | Row-level isolation enforced at DB layer |
| Ledger immutability | INSERT-only `loan_ledger` via RLS policy | Tamper-proof audit trail; no UPDATE/DELETE permitted |
| Payment idempotency | UTR-based dedup in Redis (7-day TTL) | Duplicate webhooks silently acknowledged |
| Config hot-reload | `tenant_configs` table + Redis (5-min TTL) | No deployment needed to change operational thresholds |
| Webhook processing | Separate Node.js service | Pure I/O; isolates high-throughput inbound traffic from calculation engines |
| PDF generation | Separate Node.js Puppeteer service | Puppeteer is Node-native; avoids Python subprocess overhead |
| Circuit breaker | Redis state (`circuit:{vendor}`) | Shared across all LMS pods; prevents cascade failure when Digio/Razorpay is down |

---

## Regulatory Compliance

| Regulation | Coverage |
|---|---|
| RBI Digital Lending Guidelines 2022 | KFS accessibility, 3-day cooling-off, T-1 pre-debit notification, APR disclosure |
| RBI Penal Charges Circular (Jan 2024) | Penal charges never capitalised; separate ledger; disclosed in KFS |
| RBI Floating Rate Reset Circular (Aug 2023) | Customer notified; 14-day consent window; zero foreclosure charge |
| RBI NPA / Prudential Norms | 90-day NPA, tiered provisioning (10/25/40/100%), NPA upgrade after 1 quarter |
| RBI Fair Practice Code | Payment waterfall order; free annual statement; NOC within 72 hours |
| SARFAESI Act 2002 | Section-13(2) notice tracked; CERSAI registration/release |
| CGST Act 2017 | 18% GST on all fees/charges; interest exempt; SAC codes per charge type |
| DPDP Act 2023 | PII encrypted (AES-256-GCM); AWS KMS per tenant; all data in ap-south-1 |
| IT Act 2000 | 7-year audit log retention; INSERT-only audit_logs table |

Full compliance checklist: [`docs/LMS_HLD.md`](docs/LMS_HLD.md) — Section 17.

---

## Documentation

| Document | Description |
|---|---|
| [`docs/LMS_HLD.md`](docs/LMS_HLD.md) | System architecture, module descriptions, event flows, compliance framework |
| [`docs/LMS_LLD.md`](docs/LMS_LLD.md) | Full DB schema (30 tables), engine pseudocode (16 engines), all API endpoints, cron schedule |
| [`docs/LMS_AUTH.md`](docs/LMS_AUTH.md) | Auth framework — JWT, 16-role RBAC, LSA matrix, maker-checker, PII vault, DPDP consent |
| [`docs/LMS_CALCULATIONS.md`](docs/LMS_CALCULATIONS.md) | LMS-scoped formula reference — EMI, accrual, waterfall, penalty, foreclosure, OTS |
| [`docs/TLB_Calculations_and_Charges.md`](docs/TLB_Calculations_and_Charges.md) | Full charge master, risk band ROI matrix, worked examples end-to-end |
| [`docs/TLB_Payment_Flows_and_Calculations.md`](docs/TLB_Payment_Flows_and_Calculations.md) | All payment types with accounting entries — EMI, bullet, overdue, foreclosure, OTS |
| [`docs/TLB_Collection_and_Delinquency.md`](docs/TLB_Collection_and_Delinquency.md) | DPD escalation flows, collection agency integration, legal proceedings |

---

## Branching Strategy

```
main          ← prod; protected; requires PR + review
uat           ← pre-prod; deployed to UAT environment
dev           ← integration branch; all feature branches merge here

feature/LMS-{ticket}-{short-description}   ← feature work
fix/LMS-{ticket}-{short-description}       ← bug fixes
hotfix/LMS-{ticket}-{short-description}    ← prod hotfixes (branch from main)
```

---

## Related Services

| Service | Repo | Interaction |
|---|---|---|
| LOS (Loan Origination System) | `tlb/los` | Sends `loan.disbursed` event to LMS; owns KYC, underwriting, ROI |
| Grievance Service | `tlb/grievance` | Calls LMS read APIs; LMS accepts `POST /waiver` from it |
| Notification Service | `tlb/notifications` | Consumes LMS Kafka events; sends SMS, WhatsApp, email |
| AI / Risk Engine | `tlb/risk` | Sends `rate.changed` event for float rate resets |
| DSA Engine | `tlb/dsa` | Consumes `loan.closed` + `loan.prepayment_applied` events |

---

*True Loan Bazaar (TLB) | LMS Service | BP Securities NBFC | Confidential*
