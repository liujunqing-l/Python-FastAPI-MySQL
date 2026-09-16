"""Password hashing, signed browser tokens, and the current-user dependency.

The service intentionally uses only Python's standard library for password
hashing and JWT signing.  TCP ingestion never imports this module: it remains
protected by the separate ``X-Internal-Token`` contract.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Role, User


PBKDF2_ITERATIONS = 240_000
_HASH_SCHEME = "pbkdf2_sha256"
_BEARER = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Return a self-describing PBKDF2-HMAC-SHA256 password hash."""

    if not isinstance(password, str) or not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return "$".join(
        (
            _HASH_SCHEME,
            str(PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification of a PBKDF2 hash; malformed values fail closed."""

    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        scheme, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if scheme != _HASH_SCHEME:
            return False
        iterations = int(iterations_text)
        if iterations <= 0:
            return False
        padding = "=" * (-len(salt_text) % 4)
        salt = base64.urlsafe_b64decode((salt_text + padding).encode("ascii"))
        padding = "=" * (-len(digest_text) % 4)
        expected = base64.urlsafe_b64decode((digest_text + padding).encode("ascii"))
    except (AttributeError, ValueError, TypeError, UnicodeError, binascii.Error):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not value or not isinstance(value, str):
        raise ValueError("malformed token")
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_access_token(
    *,
    user_id: int,
    username: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
    now: Optional[datetime] = None,
) -> str:
    """Create an HS256 JWT with an explicit expiry and browser-user claims."""

    current = now or datetime.now(timezone.utc)
    issued_at = int(current.timestamp())
    lifetime = expires_delta or timedelta(seconds=settings.auth_jwt_expire_seconds)
    expires_at = int((current + lifetime).timestamp())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": issued_at,
        "exp": expires_at,
    }
    encoded_header = _b64encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(
        settings.auth_jwt_secret.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64encode(signature)}"


def verify_access_token(token: str) -> dict[str, Any]:
    """Verify token structure, signature, and expiration, returning its claims."""

    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        expected_signature = hmac.new(
            settings.auth_jwt_secret.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        actual_signature = _b64decode(encoded_signature)
        if not hmac.compare_digest(actual_signature, expected_signature):
            raise ValueError("invalid token signature")
        header = json.loads(_b64decode(encoded_header).decode("utf-8"))
        claims = json.loads(_b64decode(encoded_payload).decode("utf-8"))
        if header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise ValueError("invalid token header")
        if not isinstance(claims, dict) or not claims.get("sub"):
            raise ValueError("invalid token claims")
        expires = claims.get("exp")
        if not isinstance(expires, (int, float)):
            raise ValueError("invalid token expiry")
        if time.time() >= float(expires):
            raise ValueError("token expired")
        int(claims["sub"])
        if not isinstance(claims.get("username"), str) or not isinstance(
            claims.get("role"), str
        ):
            raise ValueError("invalid token claims")
        return claims
    except binascii.Error as exc:
        raise ValueError("malformed token") from exc
    except ValueError:
        raise
    except (
        AttributeError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        IndexError,
    ) as exc:
        raise ValueError("malformed token") from exc


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_BEARER),
    db: Session = Depends(get_db),
) -> User:
    """Resolve an enabled database user from an ``Authorization: Bearer`` token."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_error()
    try:
        claims = verify_access_token(credentials.credentials)
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _authentication_error() from exc
    user = db.get(User, user_id)
    if user is None or not user.enabled:
        raise _authentication_error()
    # A deleted role is equivalent to a disabled account for authorization.
    if db.scalar(select(Role.id).where(Role.id == user.role_id)) is None:
        raise _authentication_error()
    return user


def user_role(db: Session, user: User) -> str:
    role = db.get(Role, user.role_id)
    if role is None:
        raise _authentication_error()
    return role.name
