import re
import secrets
from datetime import timedelta
from typing import Optional

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import COOKIE_SECURE, SESSION_DAYS
from .db import AuthSession, User, get_db, utcnow

COOKIE_NAME = "entente_session"
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_session(db: Session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token=token, user_id=user.id, expires_at=utcnow() + timedelta(days=SESSION_DAYS)))
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def destroy_session(db: Session, token: Optional[str], response: Response) -> None:
    if token:
        s = db.get(AuthSession, token)
        if s:
            db.delete(s)
            db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


def user_from_token(db: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    s = db.execute(select(AuthSession).where(AuthSession.token == token)).scalar_one_or_none()
    if not s or s.expires_at < utcnow():
        return None
    return s.user


def current_user(
    db: Session = Depends(get_db),
    entente_session: Optional[str] = Cookie(default=None),
) -> User:
    user = user_from_token(db, entente_session)
    if not user:
        raise HTTPException(401, "Not signed in")
    return user
