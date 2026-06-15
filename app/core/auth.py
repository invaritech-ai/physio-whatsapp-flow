from __future__ import annotations

from typing import Any, Literal
import base64
from datetime import datetime, timezone
import json
import logging

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError
from jwt.types import Options
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import get_session
from app.models import AccessRequest, Therapist, User
from app.services.auth_audit import record_auth_event


_JWK_CLIENT: dict[str, Any] = {"url": None, "client": None}
_logger = logging.getLogger("app.auth")

def is_bot_only_suspend_email(email: str | None) -> bool:
    """Whether ``email`` is configured for bot-only suspension.

    These therapist accounts have their suspension applied as a WhatsApp-bot-only
    removal (Therapist profile deactivated, so the bot's ``Therapist.is_active ==
    True`` filters drop them) while keeping login and full dashboard access. For
    these emails, ``get_current_therapist`` does NOT deny on an inactive therapist
    profile. Configured via the file at ``settings.bot_only_suspend_emails_file``
    (one email per line); compared case-insensitively.
    """
    return bool(email) and email.lower() in settings.bot_only_suspend_emails_set


AuthErrorCode = Literal[
    "invalid_token",
    "access_pending",
    "access_denied",
    "account_inactive",
]


def _debug_log(message: str, **data: Any) -> None:
    if not settings.debug_mode:
        return
    try:
        payload = json.dumps(data, default=str)
    except TypeError:
        payload = repr(data)
    _logger.info("%s %s", message, payload)


def _token_fingerprint(token: str) -> str:
    if len(token) <= 12:
        return token
    return f"{token[:6]}...{token[-6:]}"


def _decode_unverified(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))


def _raise_auth_error(status_code: int, code: AuthErrorCode) -> None:
    raise HTTPException(status_code=status_code, detail=code)


def _deny_auth(
    status_code: int,
    code: AuthErrorCode,
    *,
    db: Session | None = None,
    user_id: int | None = None,
    user_sub: str | None = None,
    actor_user_id: int | None = None,
    event_type: str = "denied_access",
    **data: Any,
) -> None:
    try:
        payload = json.dumps(data, default=str)
    except TypeError:
        payload = repr(data)
    _logger.info("auth.denied %s %s", code, payload)

    if db is not None:
        record_auth_event(
            db,
            event_type=event_type,
            user_id=user_id,
            user_sub=user_sub,
            actor_user_id=actor_user_id,
            reason=data.get("reason"),
            details=data,
            commit=True,
        )

    _raise_auth_error(status_code=status_code, code=code)


def _datetime_from_iat(iat: Any) -> datetime | None:
    if iat is None:
        return None

    try:
        issued_at_epoch = float(iat)
    except (TypeError, ValueError):
        return None

    try:
        return datetime.fromtimestamp(issued_at_epoch, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _enforce_token_ttl_policy(claims: dict[str, Any]) -> None:
    """Optionally enforce max access-token lifetime based on iat/exp claims."""
    if not settings.auth_enforce_access_ttl:
        return

    issued_at = _datetime_from_iat(claims.get("iat"))
    expires_at = _datetime_from_iat(claims.get("exp"))
    if issued_at is None or expires_at is None or expires_at <= issued_at:
        _deny_auth(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_token",
            reason="missing_or_invalid_iat_exp",
        )

    token_ttl_seconds = int((expires_at - issued_at).total_seconds())
    if token_ttl_seconds > settings.auth_max_access_token_ttl_seconds:
        _deny_auth(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_token",
            reason="token_ttl_exceeded",
            token_ttl_seconds=token_ttl_seconds,
            allowed_ttl_seconds=settings.auth_max_access_token_ttl_seconds,
        )


def revoke_user_sessions(
    user: User,
    *,
    reason: str,
    actor_user_id: int | None = None,
    db: Session | None = None,
) -> None:
    """Invalidate all active sessions for a user by advancing revoked_at."""
    now = datetime.now(timezone.utc)
    user.revoked_at = now
    user.updated_at = now
    _logger.info(
        "auth.revoke %s",
        json.dumps(
            {
                "user_id": user.id,
                "reason": reason,
                "actor_user_id": actor_user_id,
                "timestamp": now.isoformat(),
            }
        ),
    )
    if db is not None:
        record_auth_event(
            db,
            event_type="revoke",
            user_id=user.id,
            actor_user_id=actor_user_id,
            reason=reason,
            details={"timestamp": now.isoformat()},
            commit=False,
        )


def check_token_revocation(
    user: User,
    current_user: dict[str, Any],
    db: Session | None = None,
) -> None:
    """Deny access if the user's sessions have been revoked after the token was issued."""
    if user.revoked_at is None:
        return
    token_issued_at = _datetime_from_iat(current_user.get("iat"))
    revoked_at = user.revoked_at
    if revoked_at.tzinfo is None:
        revoked_at = revoked_at.replace(tzinfo=timezone.utc)
    if token_issued_at is None or token_issued_at < revoked_at:
        _deny_auth(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_token",
            db=db,
            user_id=user.id,
            reason="token_revoked",
        )


def _get_jwk_client() -> PyJWKClient:
    if not settings.neon_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="NEON_JWKS_URL is not configured",
        )

    if _JWK_CLIENT["client"] is None or _JWK_CLIENT["url"] != settings.neon_jwks_url:
        _JWK_CLIENT["client"] = PyJWKClient(
            settings.neon_jwks_url,
            cache_jwk_set=True,
            lifespan=3600,
            cache_keys=True,
        )
        _JWK_CLIENT["url"] = settings.neon_jwks_url

    return _JWK_CLIENT["client"]


def _verify_neon_token(token: str) -> dict[str, Any]:
    _debug_log(
        "auth.verify.start",
        token=_token_fingerprint(token),
        jwks_url=settings.neon_jwks_url,
        issuer=settings.neon_jwt_issuer,
        audience=settings.neon_jwt_audience,
    )
    _debug_log("auth.verify.claims_unverified", claims=_decode_unverified(token))
    try:
        jwk_client = _get_jwk_client()
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if not alg:
            _deny_auth(status.HTTP_401_UNAUTHORIZED, "invalid_token", reason="missing_alg")
        options: Options = {
            "verify_aud": bool(settings.neon_jwt_audience),
            "verify_iss": bool(settings.neon_jwt_issuer),
        }
        claims = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=[alg],
            audience=settings.neon_jwt_audience,
            issuer=settings.neon_jwt_issuer,
            options=options,
        )
        _debug_log("auth.verify.success", subject=claims.get("sub"), email=claims.get("email"))
        return claims
    except (jwt.InvalidTokenError, PyJWKClientError, ValueError, TypeError):
        _debug_log("auth.verify.failure", error="InvalidTokenError")
        _deny_auth(status.HTTP_401_UNAUTHORIZED, "invalid_token", reason="jwt_verification_failed")


def _get_bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization:
        _deny_auth(status.HTTP_401_UNAUTHORIZED, "invalid_token", reason="missing_authorization_header")

    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        _deny_auth(status.HTTP_401_UNAUTHORIZED, "invalid_token", reason="malformed_authorization_header")

    return authorization[len(prefix) :].strip()


def get_current_user(token: str = Depends(_get_bearer_token)) -> dict[str, Any]:
    claims = _verify_neon_token(token)
    _enforce_token_ttl_policy(claims)
    user_id = claims.get("sub")
    if not user_id:
        _deny_auth(status.HTTP_401_UNAUTHORIZED, "invalid_token", reason="missing_sub_claim")
    return {
        "user_id": user_id,
        "email": claims.get("email"),
        "iat": claims.get("iat"),
    }


def get_or_create_access_request(
    db: Session,
    neon_auth_sub: str,
    email: str | None,
) -> AccessRequest:
    """Return existing access request, or create a pending one for first-time users."""
    access_request = db.exec(
        select(AccessRequest).where(AccessRequest.neon_auth_sub == neon_auth_sub)
    ).first()
    if access_request:
        return access_request

    access_request = AccessRequest(
        neon_auth_sub=neon_auth_sub,
        email=email or "",
        status="pending",
    )
    db.add(access_request)
    try:
        db.commit()
        db.refresh(access_request)
        _logger.info(f"Created access request for {email or ''} ({neon_auth_sub})")
    except IntegrityError:
        # Another request may have created the row first; re-read and continue.
        db.rollback()
        access_request = db.exec(
            select(AccessRequest).where(AccessRequest.neon_auth_sub == neon_auth_sub)
        ).first()
        if not access_request:
            raise

    return access_request


def get_current_approved_user(
    required_role: Literal["admin", "therapist"],
    current_user: dict[str, Any],
    db: Session,
) -> User:
    """
    Resolve and validate current approved user for protected routes.

    Enforces:
    - authenticated JWT user identity
    - approved user exists in database
    - user account is active
    - route role permission
    """
    neon_auth_sub = current_user["user_id"]
    email = current_user.get("email")
    user = db.exec(
        select(User).where(User.neon_auth_sub == neon_auth_sub)
    ).first()

    if not user:
        access_request = get_or_create_access_request(db, neon_auth_sub, email)
        if access_request.status == "rejected":
            _deny_auth(
                status.HTTP_403_FORBIDDEN,
                "access_denied",
                db=db,
                user_sub=neon_auth_sub,
                reason="access_request_rejected",
            )
        if access_request.status == "approved":
            _deny_auth(
                status.HTTP_403_FORBIDDEN,
                "access_denied",
                db=db,
                user_sub=neon_auth_sub,
                reason="approved_without_user_record",
            )
        _deny_auth(
            status.HTTP_403_FORBIDDEN,
            "access_pending",
            db=db,
            user_sub=neon_auth_sub,
            reason="access_request_pending",
        )

    if not user.is_active:
        _deny_auth(
            status.HTTP_403_FORBIDDEN,
            "account_inactive",
            db=db,
            user_id=user.id,
            reason="user_inactive",
        )

    check_token_revocation(user, current_user, db)

    if user.role != required_role:
        _deny_auth(
            status.HTTP_403_FORBIDDEN,
            "access_denied",
            db=db,
            user_id=user.id,
            reason=f"insufficient_role:{user.role}->{required_role}",
        )

    _logger.info(
        "auth.authorized %s",
        json.dumps(
            {
                "user_id": user.id,
                "role": user.role,
                "required_role": required_role,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )

    return user


def get_current_therapist(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> Therapist:
    """Get current therapist from JWT claims.

    Validates that the authenticated user is a therapist and returns their full profile.

    If user doesn't exist in database, creates/looks up AccessRequest and raises 403.

    Raises:
        HTTPException 403: access_pending, access_denied, or account_inactive
    """
    user = get_current_approved_user(
        required_role="therapist",
        current_user=current_user,
        db=db,
    )

    # Get therapist profile
    therapist = db.exec(
        select(Therapist).where(Therapist.user_id == user.id)
    ).first()

    if not therapist:
        _deny_auth(
            status.HTTP_403_FORBIDDEN,
            "access_denied",
            db=db,
            user_id=user.id,
            reason="missing_therapist_profile",
        )

    # Bot-only suspension: an inactive Therapist profile normally blocks the
    # dashboard, but for designated accounts suspension only removes them from
    # the WhatsApp bot — login and dashboard access stay intact.
    if not therapist.is_active and not is_bot_only_suspend_email(user.email):
        _deny_auth(
            status.HTTP_403_FORBIDDEN,
            "account_inactive",
            db=db,
            user_id=user.id,
            reason="therapist_profile_inactive",
        )

    return therapist


def get_current_therapist_allow_inactive(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> Therapist:
    """Get current therapist from JWT claims, allowing inactive therapists.

    Used for onboarding endpoints where therapist may not yet be active.

    Raises:
        HTTPException 403: access_pending or access_denied
    """
    user = get_current_approved_user(
        required_role="therapist",
        current_user=current_user,
        db=db,
    )

    # Get therapist profile
    therapist = db.exec(
        select(Therapist).where(Therapist.user_id == user.id)
    ).first()

    if not therapist:
        _deny_auth(
            status.HTTP_403_FORBIDDEN,
            "access_denied",
            db=db,
            user_id=user.id,
            reason="missing_therapist_profile",
        )

    # Allow inactive therapists for onboarding
    return therapist


def get_current_admin(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> User:
    """Get current admin user from JWT claims.

    Validates that the authenticated user has admin role.

    Raises:
        HTTPException 403: access_pending, access_denied, or account_inactive
    """
    return get_current_approved_user(
        required_role="admin",
        current_user=current_user,
        db=db,
    )
