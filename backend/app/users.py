from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import ADMIN_USERNAMES
from .db import User


def is_admin(db: Session, user: User) -> bool:
    if ADMIN_USERNAMES:
        return user.username.lower() in ADMIN_USERNAMES
    first = db.execute(select(func.min(User.id))).scalar()
    return user.id == first


def me_brief(db: Session, user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "is_admin": is_admin(db, user)}
