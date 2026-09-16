"""Browser login and current-user endpoints.

These endpoints issue short-lived JWTs for Vue.  They are intentionally
separate from the internal token used by the TCP parser and worker.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Role, User
from ..schemas import AuthLoginResponse, AuthUserResponse
from ..services.auth import (
    create_access_token,
    get_current_user,
    user_role,
    verify_password,
)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_response(db: Session, user: User) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user_role(db, user),
    )


@router.post("/login", response_model=AuthLoginResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> AuthLoginResponse:
    user = db.scalar(select(User).where(User.username == form.username))
    if user is None or not user.enabled or not verify_password(form.password, user.password_hash):
        raise _invalid_credentials()
    role = db.get(Role, user.role_id)
    if role is None:
        raise _invalid_credentials()
    token = create_access_token(user_id=user.id, username=user.username, role=role.name)
    return AuthLoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.auth_jwt_expire_seconds,
        user=AuthUserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=role.name,
        ),
    )


@router.get("/me", response_model=AuthUserResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthUserResponse:
    return _user_response(db, user)
