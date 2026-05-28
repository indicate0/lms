"""
Auth middleware for Alpha LMS.

Validates Keycloak RS256 JWTs issued by https://sso.sudosys.org/realms/sudosys.
The JWKS is fetched once at startup and cached in-process; it refreshes
automatically on key-rotation (unknown kid triggers a re-fetch).

Tenant identity comes from the X-Tenant-Id request header (same convention
as the IAM Gateway — tenant_id is NOT embedded in the JWT).

Two caller types:
  1. Human users  — Bearer <Keycloak JWT>
  2. Internal jobs — Bearer <INTERNAL_SERVICE_TOKEN>  (cron endpoints)
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwk, jwt
from jose.utils import base64url_decode

from src.core.config import settings
from src.core.logging import get_logger

log = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)

# ── Keycloak JWKS cache ────────────────────────────────────────────────────────

def _keycloak_issuer() -> str:
    return f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"

def _jwks_uri() -> str:
    return f"{_keycloak_issuer()}/protocol/openid-connect/certs"

_jwks_cache: dict = {}
_jwks_lock = threading.Lock()


def _fetch_jwks() -> dict:
    resp = httpx.get(_jwks_uri(), timeout=5)
    resp.raise_for_status()
    data = resp.json()
    return {k["kid"]: k for k in data["keys"]}


def _get_jwks(force_refresh: bool = False) -> dict:
    global _jwks_cache
    with _jwks_lock:
        if not _jwks_cache or force_refresh:
            try:
                _jwks_cache = _fetch_jwks()
            except Exception as e:
                log.error("jwks_fetch_failed", error=str(e))
                # Return stale cache if available; fail hard on first load
                if not _jwks_cache:
                    raise
        return _jwks_cache


def _get_public_key(kid: str):
    keys = _get_jwks()
    if kid not in keys:
        # Unknown kid — key may have been rotated; force refresh once
        keys = _get_jwks(force_refresh=True)
    if kid not in keys:
        raise JWTError(f"Unknown JWK kid: {kid}")
    return jwk.construct(keys[kid])


# ── Role constants (Keycloak realm roles) ─────────────────────────────────────

class Role:
    BORROWER              = "BORROWER"
    DSA_AGENT             = "DSA_AGENT"
    DSA_MANAGER           = "DSA_MANAGER"
    CREDIT_ANALYST        = "CREDIT_ANALYST"
    CREDIT_OFFICER        = "CREDIT_OFFICER"
    SR_CREDIT_OFFICER     = "SR_CREDIT_OFFICER"
    COLLECTIONS_AGENT     = "COLLECTIONS_AGENT"
    COLLECTIONS_MANAGER   = "COLLECTIONS_MANAGER"
    OPS_EXECUTIVE         = "OPS_EXECUTIVE"
    FINANCE_OFFICER       = "FINANCE_OFFICER"
    COMPLIANCE_OFFICER    = "COMPLIANCE_OFFICER"
    AUDITOR               = "AUDITOR"
    IT_ADMIN              = "IT_ADMIN"
    SUPER_ADMIN           = "SUPER_ADMIN"
    SYSTEM                = "SYSTEM"
    INTEGRATION           = "INTEGRATION"


# ── LMS action permissions (mapped from roles) ────────────────────────────────
# Permissions are derived from the caller's realm roles at token validation time.
# They are NOT stored in the JWT — this avoids stale-permission bugs on role changes.

class Permission:
    LOAN_VIEW_OWN           = "loan:view:own"
    LOAN_VIEW_ALL           = "loan:view:all"
    LOAN_DISBURSE_MAKER     = "loan:disburse:maker"
    LOAN_DISBURSE_CHECKER   = "loan:disburse:checker"
    LOAN_WRITEOFF_INITIATE  = "loan:writeoff:initiate"
    LOAN_WRITEOFF_APPROVE   = "loan:writeoff:approve"
    LOAN_RESTRUCTURE        = "loan:restructure:initiate"
    LOAN_OTS                = "loan:ots"
    LOAN_COOLING_OFF_CANCEL = "loan:cooling_off_cancel"
    PII_VIEW_MASKED         = "pii:view:masked"
    PII_VIEW_FULL           = "pii:view:full"
    PII_EXPORT              = "pii:export"
    COLLECTION_VIEW_ALL     = "collection:view:all"
    COLLECTION_VIEW_ASSIGNED = "collection:view:assigned"
    PAYMENT_POST            = "payment:post"
    REPORT_RBI              = "report:rbi"
    CONFIG_CHARGE_MASTER    = "config:charge_master"
    AUDIT_VIEW              = "audit:view"
    AUDIT_EXPORT            = "audit:export"
    ADMIN_USER              = "admin:user"


_ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BORROWER: [
        Permission.LOAN_VIEW_OWN,
        Permission.LOAN_COOLING_OFF_CANCEL,
    ],
    Role.DSA_AGENT: [Permission.LOAN_VIEW_OWN],
    Role.DSA_MANAGER: [Permission.LOAN_VIEW_ALL],
    Role.CREDIT_ANALYST: [Permission.LOAN_VIEW_ALL, Permission.PII_VIEW_MASKED],
    Role.CREDIT_OFFICER: [
        Permission.LOAN_VIEW_ALL,
        Permission.LOAN_DISBURSE_MAKER,
        Permission.LOAN_RESTRUCTURE,
        Permission.PII_VIEW_MASKED,
        Permission.PAYMENT_POST,
    ],
    Role.SR_CREDIT_OFFICER: [
        Permission.LOAN_VIEW_ALL,
        Permission.LOAN_DISBURSE_MAKER,
        Permission.LOAN_DISBURSE_CHECKER,
        Permission.LOAN_RESTRUCTURE,
        Permission.LOAN_OTS,
        Permission.LOAN_WRITEOFF_INITIATE,
        Permission.PII_VIEW_MASKED,
        Permission.PAYMENT_POST,
    ],
    Role.COLLECTIONS_AGENT: [
        Permission.COLLECTION_VIEW_ASSIGNED,
        Permission.PII_VIEW_MASKED,
        Permission.PAYMENT_POST,
    ],
    Role.COLLECTIONS_MANAGER: [
        Permission.COLLECTION_VIEW_ALL,
        Permission.LOAN_VIEW_ALL,
        Permission.PII_VIEW_MASKED,
        Permission.PAYMENT_POST,
    ],
    Role.OPS_EXECUTIVE: [
        Permission.LOAN_VIEW_ALL,
        Permission.PII_VIEW_MASKED,
        Permission.PAYMENT_POST,
    ],
    Role.FINANCE_OFFICER: [
        Permission.LOAN_VIEW_ALL,
        Permission.REPORT_RBI,
        Permission.PII_VIEW_MASKED,
    ],
    Role.COMPLIANCE_OFFICER: [
        Permission.LOAN_VIEW_ALL,
        Permission.LOAN_WRITEOFF_INITIATE,
        Permission.LOAN_WRITEOFF_APPROVE,
        Permission.REPORT_RBI,
        Permission.CONFIG_CHARGE_MASTER,
        Permission.AUDIT_VIEW,
        Permission.AUDIT_EXPORT,
        Permission.PII_VIEW_MASKED,
        Permission.PII_VIEW_FULL,
    ],
    Role.AUDITOR: [
        Permission.LOAN_VIEW_ALL,
        Permission.AUDIT_VIEW,
        Permission.PII_VIEW_MASKED,
    ],
    Role.IT_ADMIN: [Permission.ADMIN_USER],
    Role.SUPER_ADMIN: [
        Permission.LOAN_VIEW_ALL,
        Permission.LOAN_WRITEOFF_APPROVE,
        Permission.LOAN_RESTRUCTURE,
        Permission.LOAN_OTS,
        Permission.REPORT_RBI,
        Permission.CONFIG_CHARGE_MASTER,
        Permission.AUDIT_VIEW,
        Permission.AUDIT_EXPORT,
        Permission.PII_VIEW_FULL,
        Permission.PII_EXPORT,
        Permission.ADMIN_USER,
        Permission.PAYMENT_POST,
    ],
    Role.SYSTEM: [
        Permission.LOAN_VIEW_ALL,
        Permission.PAYMENT_POST,
        Permission.REPORT_RBI,
    ],
    Role.INTEGRATION: [Permission.LOAN_VIEW_ALL],
}


def _permissions_for_roles(roles: list[str]) -> list[str]:
    """Union of permissions across all the caller's roles."""
    perms: set[str] = set()
    for role in roles:
        perms.update(_ROLE_PERMISSIONS.get(role, []))
    return list(perms)


# ── Principal ──────────────────────────────────────────────────────────────────

@dataclass
class Principal:
    sub: str                              # Keycloak user UUID
    username: str
    email: Optional[str]
    roles: list[str]                      # Keycloak realm roles
    permissions: list[str]               # derived from roles
    tenant_id: Optional[uuid.UUID]       # from X-Tenant-Id header
    is_internal: bool = False            # True for INTERNAL_SERVICE_TOKEN

    def has(self, *perms: str) -> bool:
        return all(p in self.permissions for p in perms)

    def any(self, *perms: str) -> bool:
        return any(p in self.permissions for p in perms)

    def has_role(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles)


# ── JWT validation ─────────────────────────────────────────────────────────────

def _verify_keycloak_token(token: str) -> dict:
    """Decode and verify a Keycloak RS256 JWT."""
    # Peek at header to get kid without full decode
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    if not kid:
        raise JWTError("JWT missing kid header")

    public_key = _get_public_key(kid)

    claims = jwt.decode(
        token,
        public_key.to_pem().decode(),
        algorithms=["RS256"],
        issuer=_keycloak_issuer(),
        options={"verify_aud": False},  # audience varies by client; verify issuer only
    )
    return claims


def _claims_to_principal(claims: dict, tenant_id: Optional[uuid.UUID]) -> Principal:
    roles: list[str] = (
        claims.get("realm_access", {}).get("roles", [])
    )
    return Principal(
        sub=claims.get("sub", ""),
        username=claims.get("preferred_username", ""),
        email=claims.get("email"),
        roles=roles,
        permissions=_permissions_for_roles(roles),
        tenant_id=tenant_id,
    )


# ── FastAPI dependency ─────────────────────────────────────────────────────────

def _parse_tenant_header(request: Request) -> Optional[uuid.UUID]:
    raw = request.headers.get("X-Tenant-Id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_TENANT", "message": "X-Tenant-Id must be a valid UUID"},
        )


async def get_current_principal(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Principal:
    """
    Resolves the caller. Accepts:
      1. INTERNAL_SERVICE_TOKEN — cron / Kafka consumer calls (no tenant header needed)
      2. Keycloak Bearer JWT    — all human API calls (requires X-Tenant-Id header)
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "MISSING_TOKEN", "message": "Authorization: Bearer <token> required"},
        )

    token = credentials.credentials

    # ── Internal service token ─────────────────────────────────────────────────
    if token == settings.INTERNAL_SERVICE_TOKEN:
        return Principal(
            sub="system",
            username="system",
            email=None,
            roles=[Role.SYSTEM],
            permissions=_ROLE_PERMISSIONS[Role.SYSTEM],
            tenant_id=_parse_tenant_header(request),
            is_internal=True,
        )

    # ── Keycloak JWT ───────────────────────────────────────────────────────────
    tenant_id = _parse_tenant_header(request)

    try:
        claims = _verify_keycloak_token(token)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "TOKEN_EXPIRED", "message": "Access token has expired — please refresh"},
        )
    except JWTError as e:
        log.warning("jwt_verification_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_TOKEN", "message": "Token verification failed"},
        )

    principal = _claims_to_principal(claims, tenant_id)
    request.state.principal = principal

    log.debug(
        "auth_ok",
        sub=principal.sub,
        username=principal.username,
        roles=principal.roles,
        tenant_id=str(tenant_id) if tenant_id else None,
    )
    return principal


# ── Guard factories ────────────────────────────────────────────────────────────

def require(*permissions: str):
    """All listed permissions must be held."""
    async def _guard(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has(*permissions):
            log.warning(
                "permission_denied",
                sub=principal.sub,
                roles=principal.roles,
                required=list(permissions),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "PERMISSION_DENIED",
                    "message": f"Required permissions: {', '.join(permissions)}",
                },
            )
        return principal
    return _guard


def require_any(*permissions: str):
    """At least one of the listed permissions must be held."""
    async def _guard(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.any(*permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "PERMISSION_DENIED",
                    "message": f"One of {', '.join(permissions)} required",
                },
            )
        return principal
    return _guard


def require_roles(*roles: str):
    """Principal must hold at least one of the listed Keycloak realm roles."""
    async def _guard(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has_role(*roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "ROLE_DENIED",
                    "message": f"One of these roles required: {', '.join(roles)}",
                },
            )
        return principal
    return _guard
