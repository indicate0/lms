import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core.auth import require_roles, Role
from src.core.config import settings
from src.core.exceptions import LMSError
from src.core.logging import configure_logging, get_logger, request_id_ctx
from src.db.session import AsyncSessionLocal, engine
from src.api.v1.routers import admin, foreclosure, loans, prepayment, repayments, webhooks
from src.services.dpd_service import run_dpd_cron
from src.services.interest_accrual_service import run_interest_accrual_cron
from src.services.noc_service import process_noc_queue, run_closure_detector
from src.services.penalty_service import run_penalty_cron
from src.services.bounce_service import process_retry_queue

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(level=settings.LOG_LEVEL, json_logs=settings.LOG_JSON)
    log.info("alpha_lms_started", env=settings.APP_ENV)
    yield
    await engine.dispose()
    log.info("alpha_lms_shutdown")


app = FastAPI(
    title="Alpha LMS",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)


# ── Request-ID middleware ──────────────────────────────────────────────────────

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    token = request_id_ctx.set(rid)
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    request_id_ctx.reset(token)
    return response


# ── Access log middleware ──────────────────────────────────────────────────────

@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    response = await call_next(request)
    log.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    return response


# ── Error handlers ─────────────────────────────────────────────────────────────

@app.exception_handler(LMSError)
async def lms_error_handler(request: Request, exc: LMSError):
    log.warning(
        "lms_error",
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "detail": exc.detail,
            "request_id": request_id_ctx.get(),
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    log.exception("unhandled_exception", path=request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
            "request_id": request_id_ctx.get(),
        },
    )


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/api/v1/lms/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.get("/api/v1/lms/ready", tags=["health"])
async def ready():
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "fail"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
    )


# ── API routers ────────────────────────────────────────────────────────────────

app.include_router(loans.router,        prefix="/api/v1/lms/loans",               tags=["loans"])
app.include_router(repayments.router,   prefix="/api/v1/lms/repayments",          tags=["repayments"])
app.include_router(foreclosure.router,  prefix="/api/v1/lms/foreclosure",         tags=["foreclosure"])
app.include_router(prepayment.router,   prefix="/api/v1/lms/prepayment",          tags=["prepayment"])
app.include_router(webhooks.router,     prefix="/api/v1/lms/repayments/webhook",  tags=["webhooks"])
app.include_router(admin.router,        prefix="/api/v1/lms/admin",               tags=["admin"])


_system_only = [Depends(require_roles(Role.SYSTEM))]

# ── Cron trigger endpoints (internal — SYSTEM token only, not via public gateway)

@app.post("/api/v1/lms/admin/cron/interest-accrual", tags=["admin"], dependencies=_system_only)
async def trigger_interest_accrual():
    async with AsyncSessionLocal() as session:
        return await run_interest_accrual_cron(session)


@app.post("/api/v1/lms/admin/cron/dpd", tags=["admin"], dependencies=_system_only)
async def trigger_dpd_cron():
    async with AsyncSessionLocal() as session:
        return await run_dpd_cron(session)


@app.post("/api/v1/lms/admin/cron/penalty", tags=["admin"], dependencies=_system_only)
async def trigger_penalty_cron():
    async with AsyncSessionLocal() as session:
        return await run_penalty_cron(session)


@app.post("/api/v1/lms/admin/cron/noc-queue", tags=["admin"], dependencies=_system_only)
async def trigger_noc_queue():
    async with AsyncSessionLocal() as session:
        return await process_noc_queue(session)


@app.post("/api/v1/lms/admin/cron/closure-detector", tags=["admin"], dependencies=_system_only)
async def trigger_closure_detector():
    async with AsyncSessionLocal() as session:
        return await run_closure_detector(session)


@app.post("/api/v1/lms/admin/cron/enach-retry", tags=["admin"], dependencies=_system_only)
async def trigger_enach_retry():
    async with AsyncSessionLocal() as session:
        return await process_retry_queue(session)
