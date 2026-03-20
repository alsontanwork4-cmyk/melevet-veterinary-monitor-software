from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db, run_with_sqlite_retry
from ..models import User, UserSession
from ..utils import coerce_utc, utcnow


PASSWORD_HASHER = PasswordHasher()
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class SessionTokens:
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: UserSession




def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def _session_cookie_max_age() -> int:
    return max(1, settings.session_ttl_hours) * 60 * 60


def _csrf_cookie_max_age() -> int:
    return _session_cookie_max_age()


def ensure_bootstrap_user(db: Session) -> User | None:
    existing = db.scalar(select(User).order_by(User.id.asc()))
    if existing is not None:
        return existing

    if not settings.auth_bootstrap_username or not settings.auth_bootstrap_password:
        raise RuntimeError(
            "Authentication is enabled but no users exist. Set AUTH_BOOTSTRAP_USERNAME and "
            "AUTH_BOOTSTRAP_PASSWORD in backend/.env before starting the app."
        )

    user = User(
        username=settings.auth_bootstrap_username.strip(),
        password_hash=hash_password(settings.auth_bootstrap_password),
        is_active=True,
    )
    def _create_user() -> None:
        db.add(user)
        db.commit()

    run_with_sqlite_retry(db, _create_user, operation_name="bootstrap user creation")
    db.refresh(user)
    return user


def purge_expired_sessions(db: Session) -> int:
    expired = db.scalars(select(UserSession).where(UserSession.expires_at <= utcnow())).all()
    if not expired:
        return 0
    deleted = len(expired)

    def _purge() -> None:
        for session in expired:
            db.delete(session)
        db.commit()

    run_with_sqlite_retry(db, _purge, operation_name="expired session purge")
    return deleted


def authenticate_user(db: Session, *, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username.strip()))
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_session(db: Session, *, user: User) -> SessionTokens:
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(hours=max(1, settings.session_ttl_hours))
    session = UserSession(
        user_id=user.id,
        token_hash=_hash_token(session_token),
        csrf_token_hash=_hash_token(csrf_token),
        expires_at=expires_at,
        last_seen_at=utcnow(),
    )

    def _create() -> None:
        db.add(session)
        db.commit()

    run_with_sqlite_retry(db, _create, operation_name="session creation")
    return SessionTokens(session_token=session_token, csrf_token=csrf_token, expires_at=expires_at)


def invalidate_session(db: Session, session: UserSession) -> None:
    def _invalidate() -> None:
        db.delete(session)
        db.commit()

    run_with_sqlite_retry(db, _invalidate, operation_name="session invalidation")


def set_session_cookie(response: Response, session_token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        max_age=_session_cookie_max_age(),
        httponly=True,
        secure=settings.effective_session_cookie_secure,
        samesite="lax",
        path="/",
    )


def set_csrf_cookie(response: Response, csrf_token: str) -> None:
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=_csrf_cookie_max_age(),
        httponly=False,
        secure=settings.effective_session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path="/", samesite="lax")


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.csrf_cookie_name, path="/", samesite="lax")


def read_csrf_cookie(request: Request, session: UserSession) -> str:
    csrf_token = request.cookies.get(settings.csrf_cookie_name)
    if not csrf_token or _hash_token(csrf_token) != session.csrf_token_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="CSRF session state is missing. Please sign in again.",
        )
    return csrf_token


def _load_auth_context(request: Request, db: Session) -> AuthContext | None:
    if hasattr(request.state, "auth_context_loaded"):
        return getattr(request.state, "auth_context", None)

    token = request.cookies.get(settings.session_cookie_name)
    context: AuthContext | None = None
    if token:
        session = db.scalar(
            select(UserSession)
            .options(joinedload(UserSession.user))
            .where(UserSession.token_hash == _hash_token(token))
        )
        if session is not None:
            if coerce_utc(session.expires_at) > utcnow() and session.user.is_active:
                context = AuthContext(user=session.user, session=session)

    request.state.auth_context = context
    request.state.auth_context_loaded = True
    return context


def require_active_user(request: Request, db: Session = Depends(get_db)) -> User:
    context = _load_auth_context(request, db)
    if context is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return context.user


def require_active_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    context = _load_auth_context(request, db)
    if context is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return context.session


def enforce_csrf(request: Request, session: UserSession = Depends(require_active_session)) -> None:
    if request.method in SAFE_METHODS:
        return

    header_value = request.headers.get(settings.csrf_header_name)
    if not header_value or _hash_token(header_value) != session.csrf_token_hash:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
