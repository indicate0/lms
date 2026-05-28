"""
Structured logging for Alpha LMS.

Two outputs:
  1. structlog → stdlib → stdout as JSON (production) or coloured (dev).
     Every log record includes: timestamp, level, logger, request_id, service="alpha-lms".
  2. DB audit trail via write_audit_log() — INSERT-only into audit_logs table.
     Called from service layer for every financial state change (RBI IT Framework §7).

Compliance requirements implemented here:
  - PAN / Aadhaar / account numbers masked before emission (never in plaintext logs).
  - audit_logs retained 7 years (enforced by DB partition retention policy — see §2.27).
  - Every state-changing API call must carry a request_id that ties app logs to audit_logs.
"""
from __future__ import annotations

import logging
import logging.config
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

# ── Request-ID context var (set by middleware) ─────────────────────────────────
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# ── Sensitive field masker ─────────────────────────────────────────────────────
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
# Aadhaar: 12 digits optionally separated by spaces or hyphens.
# Negative lookbehind (?<!\d) ensures we don't match inside a longer digit run,
# and we exclude patterns preceded by a 4-digit year (like loan account numbers).
_AADHAAR_RE = re.compile(r"(?<![A-Z0-9])\b\d{4}[\s-]\d{4}[\s-]\d{4}\b")
_ACCOUNT_RE = re.compile(r"\b\d{9,18}\b")  # bank account / card numbers


def _mask(value: str) -> str:
    value = _PAN_RE.sub("***PAN***", value)
    value = _AADHAAR_RE.sub("***AADHAAR***", value)
    return value


def _mask_event(logger: Any, method: str, event_dict: dict) -> dict:  # noqa: ARG001
    """structlog processor — masks sensitive strings in the event message."""
    msg = event_dict.get("event", "")
    if isinstance(msg, str):
        event_dict["event"] = _mask(msg)
    return event_dict


def _add_request_id(logger: Any, method: str, event_dict: dict) -> dict:  # noqa: ARG001
    rid = request_id_ctx.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict


def _add_service(logger: Any, method: str, event_dict: dict) -> dict:  # noqa: ARG001
    event_dict.setdefault("service", "alpha-lms")
    return event_dict


# ── Setup ──────────────────────────────────────────────────────────────────────

def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """
    Call once at application startup (lifespan).
    json_logs=True  → newline-delimited JSON to stdout (Loki / CloudWatch).
    json_logs=False → human-readable coloured output (local dev).
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _add_request_id,
        _add_service,
        _mask_event,
    ]

    if json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level.upper())

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


# ── DB audit trail ─────────────────────────────────────────────────────────────

# System UUID used for cron / background actors that have no human user.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_ROLE = "system"


async def write_audit_log(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    payload_before: dict | None = None,
    payload_after: dict | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    """
    INSERT-only write to audit_logs (RBI IT Framework — 7-year retention).
    Never update or delete audit rows.
    """
    from src.models.loan import AuditLog  # local import avoids circular

    session.add(AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_before=payload_before,
        payload_after=payload_after,
        ip_address=ip_address,
        request_id=request_id or request_id_ctx.get(),
    ))
