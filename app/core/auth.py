from __future__ import annotations

from typing import Any
import base64
import json
import logging

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from jwt.types import Options
from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import get_session
from app.models import Therapist, User


_JWK_CLIENT: dict[str, Any] = {"url": None, "client": None}
_logger = logging.getLogger("app.auth")


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
    jwk_client = _get_jwk_client()
    signing_key = jwk_client.get_signing_key_from_jwt(token)
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    if not alg:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing alg")
    options: Options = {
        "verify_aud": bool(settings.neon_jwt_audience),
        "verify_iss": bool(settings.neon_jwt_issuer),
    }
    try:
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
    except jwt.InvalidTokenError:
        _debug_log("auth.verify.failure", error="InvalidTokenError")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _get_bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header")

    return authorization[len(prefix) :].strip()


def get_current_user(token: str = Depends(_get_bearer_token)) -> dict[str, Any]:
    claims = _verify_neon_token(token)
    return {
        "user_id": claims.get("sub"),
        "email": claims.get("email"),
    }


def get_current_therapist(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> Therapist:
    """Get current therapist from JWT claims.

    Validates that the authenticated user is a therapist and returns their full profile.

    Raises:
        HTTPException 401: User not found in database
        HTTPException 403: User is not a therapist or therapist account is inactive
        HTTPException 404: Therapist profile not found
    """
    # Lookup user by neon_auth_sub (which matches JWT "sub" claim)
    user = db.exec(
        select(User).where(User.neon_auth_sub == current_user["user_id"])
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if user.role != "therapist":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: therapist role required",
        )

    # Get therapist profile
    therapist = db.exec(
        select(Therapist).where(Therapist.user_id == user.id)
    ).first()

    if not therapist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Therapist profile not found",
        )

    if not therapist.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Therapist account is inactive",
        )

    return therapist
