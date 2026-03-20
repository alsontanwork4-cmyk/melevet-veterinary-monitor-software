from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import AuthLoginRequest, AuthSessionOut, AuthUserOut, CsrfTokenOut, LogoutResponse
from ..services.auth_service import (
    authenticate_user,
    clear_csrf_cookie,
    clear_session_cookie,
    create_session,
    enforce_csrf,
    invalidate_session,
    read_csrf_cookie,
    require_active_session,
    require_active_user,
    set_csrf_cookie,
    set_session_cookie,
)


router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=AuthSessionOut)
def login(payload: AuthLoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, username=payload.username, password=payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    tokens = create_session(db, user=user)
    set_session_cookie(response, tokens.session_token)
    set_csrf_cookie(response, tokens.csrf_token)
    return AuthSessionOut(user=user, csrf_token=tokens.csrf_token, expires_at=tokens.expires_at)


@router.get("/auth/session", response_model=AuthSessionOut)
def session_state(request: Request, session=Depends(require_active_session)):
    csrf_token = read_csrf_cookie(request, session)
    return AuthSessionOut(user=session.user, csrf_token=csrf_token, expires_at=session.expires_at)


@router.post("/auth/logout", response_model=LogoutResponse)
def logout(
    response: Response,
    _csrf: None = Depends(enforce_csrf),
    session = Depends(require_active_session),
    db: Session = Depends(get_db),
):
    invalidate_session(db, session)
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    return LogoutResponse(logged_out=True)


@router.get("/auth/me", response_model=AuthUserOut)
def me(user=Depends(require_active_user)):
    return user


@router.get("/auth/csrf", response_model=CsrfTokenOut)
def csrf_token(request: Request, session=Depends(require_active_session)):
    token = read_csrf_cookie(request, session)
    return CsrfTokenOut(csrf_token=token)
