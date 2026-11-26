from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from .config import DATABASE_URL


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class TZDateTime(TypeDecorator):
    """Store UTC, always hand back timezone-aware datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class AuthSession(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    user: Mapped[User] = relationship()


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (UniqueConstraint("requester_id", "addressee_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    addressee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | accepted
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    addressee: Mapped[User] = relationship(foreign_keys=[addressee_id])


class Game(Base):
    __tablename__ = "games"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="forming")  # forming | active | finished
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    assignment: Mapped[str] = mapped_column(String(16), default="random")  # random | choice
    press: Mapped[str] = mapped_column(String(16), default="full")  # full | public | none
    # Minutes per phase. None = only advance when every player is ready.
    deadline_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    variant: Mapped[str] = mapped_column(String(40), default="classic")
    # Custom variants: the exact map + geometry the game started with, so later edits
    # to the variant can never break a game in progress.
    map_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    geometry_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    engine_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phase: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: {"type": "solo"|"draw", "powers": [...]}
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
    creator: Mapped[User] = relationship()
    players: Mapped[list["GamePlayer"]] = relationship(
        back_populates="game", cascade="all, delete-orphan", order_by="GamePlayer.id"
    )


class GamePlayer(Base):
    __tablename__ = "game_players"
    __table_args__ = (UniqueConstraint("game_id", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    power: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    orders: Mapped[str] = mapped_column(Text, default="[]")  # JSON list, current phase only
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    draw_vote: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    game: Mapped[Game] = relationship(back_populates="players")
    user: Mapped[User] = relationship()


class GameInvite(Base):
    __tablename__ = "game_invites"
    __table_args__ = (UniqueConstraint("game_id", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    inviter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    game: Mapped[Game] = relationship()
    inviter: Mapped[User] = relationship(foreign_keys=[inviter_id])


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    sender: Mapped[str] = mapped_column(String(16))  # power name
    recipient: Mapped[str] = mapped_column(String(16))  # power name or GLOBAL
    body: Mapped[str] = mapped_column(Text)
    phase: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class Variant(Base):
    """A user-uploaded map. Built-in variants live in app/maps/ and never touch this table."""

    __tablename__ = "variants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected
    source_format: Mapped[str] = mapped_column(String(8), default="png")  # png | svg
    spec_json: Mapped[str] = mapped_column(Text)
    map_text: Mapped[str] = mapped_column(Text)
    geometry_json: Mapped[str] = mapped_column(Text)
    report_json: Mapped[str] = mapped_column(Text)
    mask_png: Mapped[bytes] = mapped_column(LargeBinary)
    image: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    image_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ai_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
    author: Mapped[User] = relationship()


def _add_missing_columns() -> None:
    """Tiny forward-only migration for columns added after the first release."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "games" not in insp.get_table_names():
        return
    have = {c["name"] for c in insp.get_columns("games")}
    adds = {
        "variant": "VARCHAR(40) DEFAULT 'classic'",
        "map_text": "TEXT",
        "geometry_json": "TEXT",
    }
    with engine.begin() as conn:
        for col, ddl in adds.items():
            if col not in have:
                conn.execute(text(f"ALTER TABLE games ADD COLUMN {col} {ddl}"))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
