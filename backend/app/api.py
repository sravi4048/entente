import json
import secrets
from typing import List, Literal, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import engine, service
from .auth import (
    USERNAME_RE,
    check_password,
    create_session,
    current_user,
    destroy_session,
    hash_password,
)
from .config import ANTHROPIC_API_KEY, SIGNUP_CODE, SOURCE_URL
from .db import Friendship, Game, GameInvite, GamePlayer, Message, User, get_db
from .hub import hub
from .service import user_brief
from .users import is_admin, me_brief
from .variants import registry

router = APIRouter(prefix="/api")


# ===================================================================== auth

class RegisterIn(BaseModel):
    username: str
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=64)
    invite_code: Optional[str] = Field(default=None, max_length=64)


class LoginIn(BaseModel):
    username: str
    password: str


@router.get("/config")
def config():
    return {"source_url": SOURCE_URL, "signup_code_required": bool(SIGNUP_CODE), "ai_enabled": bool(ANTHROPIC_API_KEY)}


@router.post("/auth/register")
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    # SIGNUP_CODE may list several comma-separated codes; any one works (case-insensitive).
    codes = {c.strip().lower() for c in SIGNUP_CODE.split(",") if c.strip()}
    if codes and (body.invite_code or "").strip().lower() not in codes:
        raise HTTPException(403, "That sign-up code isn't right — ask whoever invited you")
    if not USERNAME_RE.match(body.username):
        raise HTTPException(400, "Username must be 3–20 letters, numbers or underscores")
    exists = db.execute(select(User).where(func.lower(User.username) == body.username.lower())).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "That username is taken")
    user = User(
        username=body.username,
        display_name=(body.display_name or body.username).strip()[:64] or body.username,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    create_session(db, user, response)
    return me_brief(db, user)


@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(func.lower(User.username) == body.username.lower())).scalar_one_or_none()
    if not user or not check_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong username or password")
    create_session(db, user, response)
    return me_brief(db, user)


@router.post("/auth/logout")
def logout(response: Response, db: Session = Depends(get_db), entente_session: Optional[str] = Cookie(default=None)):
    destroy_session(db, entente_session, response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_brief(db, user)


# ================================================================== friends

def _friendships(db: Session, uid: int) -> List[Friendship]:
    return list(
        db.execute(
            select(Friendship).where(or_(Friendship.requester_id == uid, Friendship.addressee_id == uid))
        ).scalars()
    )


def friend_ids(db: Session, uid: int) -> set:
    out = set()
    for f in _friendships(db, uid):
        if f.status == "accepted":
            out.add(f.addressee_id if f.requester_id == uid else f.requester_id)
    return out


@router.get("/friends")
def list_friends(user: User = Depends(current_user), db: Session = Depends(get_db)):
    friends, incoming, outgoing = [], [], []
    for f in _friendships(db, user.id):
        other = f.addressee if f.requester_id == user.id else f.requester
        item = {"id": f.id, "user": {**user_brief(other), "online": hub.online(other.id)}}
        if f.status == "accepted":
            friends.append(item)
        elif f.addressee_id == user.id:
            incoming.append(item)
        else:
            outgoing.append(item)
    friends.sort(key=lambda i: i["user"]["display_name"].lower())
    return {"friends": friends, "incoming": incoming, "outgoing": outgoing}


class FriendRequestIn(BaseModel):
    username: str


@router.post("/friends/request")
def request_friend(body: FriendRequestIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    other = db.execute(select(User).where(func.lower(User.username) == body.username.strip().lower())).scalar_one_or_none()
    if not other:
        raise HTTPException(404, "No player with that username")
    if other.id == user.id:
        raise HTTPException(400, "You can't friend yourself")
    for f in _friendships(db, user.id):
        if other.id in (f.requester_id, f.addressee_id):
            if f.status == "pending" and f.addressee_id == user.id:
                f.status = "accepted"  # they already asked you: accept
                db.commit()
                hub.publish([other.id, user.id], {"type": "friends"})
                return {"status": "accepted"}
            return {"status": f.status}
    db.add(Friendship(requester_id=user.id, addressee_id=other.id))
    db.commit()
    hub.publish([other.id], {"type": "friends"})
    return {"status": "pending"}


def _own_friendship(db: Session, fid: int, user: User) -> Friendship:
    f = db.get(Friendship, fid)
    if not f or user.id not in (f.requester_id, f.addressee_id):
        raise HTTPException(404, "Not found")
    return f


@router.post("/friends/{fid}/accept")
def accept_friend(fid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _own_friendship(db, fid, user)
    if f.addressee_id != user.id:
        raise HTTPException(403, "Only the recipient can accept")
    f.status = "accepted"
    db.commit()
    hub.publish([f.requester_id, f.addressee_id], {"type": "friends"})
    return {"ok": True}


@router.delete("/friends/{fid}")
def remove_friend(fid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _own_friendship(db, fid, user)
    ids = [f.requester_id, f.addressee_id]
    db.delete(f)
    db.commit()
    hub.publish(ids, {"type": "friends"})
    return {"ok": True}


# ==================================================================== games

class CreateGameIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    deadline_minutes: Optional[int] = Field(default=1440, ge=5, le=60 * 24 * 7)
    assignment: Literal["random", "choice"] = "random"
    press: Literal["full", "public", "none"] = "full"
    variant: str = Field(default="classic", max_length=40)


def _load_game(db: Session, gid: int) -> Game:
    g = db.get(Game, gid)
    if not g:
        raise HTTPException(404, "Game not found")
    return g


def _member(game: Game, user: User) -> GamePlayer:
    p = service.player_for(game, user.id)
    if not p:
        raise HTTPException(403, "You're not in this game")
    return p


@router.get("/games")
def my_games(user: User = Depends(current_user), db: Session = Depends(get_db)):
    games = db.execute(
        select(Game).join(GamePlayer).where(GamePlayer.user_id == user.id).order_by(Game.updated_at.desc())
    ).scalars()
    invites = db.execute(select(GameInvite).where(GameInvite.user_id == user.id)).scalars()
    inv = []
    for i in invites:
        if i.game.status == "forming" and not service.player_for(i.game, user.id):
            inv.append({"id": i.id, "game": service.serialize_summary(i.game, user.id), "inviter": user_brief(i.inviter)})
    return {"games": [service.serialize_summary(g, user.id) for g in games], "invites": inv}


@router.post("/games")
def create_game(body: CreateGameIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ref = registry.resolve(db, body.variant)
    if not ref or not registry.can_play(ref, user.id, is_admin(db, user)):
        raise HTTPException(400, "That map isn't available")
    g = Game(
        variant=ref.slug,
        name=body.name.strip(),
        creator_id=user.id,
        invite_code=secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")[:8],
        assignment=body.assignment,
        press=body.press,
        deadline_minutes=body.deadline_minutes,
    )
    g.players.append(GamePlayer(user_id=user.id))
    db.add(g)
    db.commit()
    return service.serialize_game(g, user.id)


@router.get("/games/{gid}")
def get_game(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    _member(g, user)
    return service.serialize_game(g, user.id)


@router.get("/games/code/{code}")
def game_by_code(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.execute(select(Game).where(Game.invite_code == code)).scalar_one_or_none()
    if not g:
        raise HTTPException(404, "That invite link isn't valid")
    return {"id": g.id, "name": g.name, "status": g.status, "player_count": len(g.players),
            "is_member": service.player_for(g, user.id) is not None, "creator": user_brief(g.creator)}


def _join(db: Session, g: Game, user: User) -> dict:
    if service.player_for(g, user.id):
        return service.serialize_game(g, user.id)
    if g.status != "forming":
        raise HTTPException(400, "This game has already started")
    ref = service.variant_of(g)
    if len(g.players) >= (len(ref.powers) if ref else 7):
        raise HTTPException(400, "This game is full")
    g.players.append(GamePlayer(user_id=user.id))
    for inv in db.execute(select(GameInvite).where(GameInvite.game_id == g.id, GameInvite.user_id == user.id)).scalars():
        db.delete(inv)
    db.commit()
    service.notify_game(g, "joined")
    return service.serialize_game(g, user.id)


@router.post("/games/code/{code}/join")
def join_by_code(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.execute(select(Game).where(Game.invite_code == code)).scalar_one_or_none()
    if not g:
        raise HTTPException(404, "That invite link isn't valid")
    return _join(db, g, user)


@router.post("/games/{gid}/join")
def join_invited(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    invited = db.execute(select(GameInvite).where(GameInvite.game_id == gid, GameInvite.user_id == user.id)).scalar_one_or_none()
    if not invited and not service.player_for(g, user.id):
        raise HTTPException(403, "You need an invite or the game link")
    return _join(db, g, user)


@router.post("/games/{gid}/decline")
def decline_invite(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for inv in db.execute(select(GameInvite).where(GameInvite.game_id == gid, GameInvite.user_id == user.id)).scalars():
        db.delete(inv)
    db.commit()
    return {"ok": True}


class InviteIn(BaseModel):
    user_id: int


@router.post("/games/{gid}/invite")
def invite(gid: int, body: InviteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    _member(g, user)
    if g.status != "forming":
        raise HTTPException(400, "Game already started")
    if body.user_id not in friend_ids(db, user.id):
        raise HTTPException(403, "You can only invite friends")
    if service.player_for(g, body.user_id):
        return {"ok": True}
    exists = db.execute(select(GameInvite).where(GameInvite.game_id == gid, GameInvite.user_id == body.user_id)).scalar_one_or_none()
    if not exists:
        db.add(GameInvite(game_id=gid, user_id=body.user_id, inviter_id=user.id))
        db.commit()
    hub.publish([body.user_id], {"type": "invite", "game_id": gid})
    return {"ok": True}


@router.get("/games/{gid}/invites")
def list_invites(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    _member(g, user)
    return [i.user_id for i in db.execute(select(GameInvite).where(GameInvite.game_id == gid)).scalars()]


@router.post("/games/{gid}/leave")
def leave(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    p = _member(g, user)
    if g.status != "forming":
        raise HTTPException(400, "You can't leave a game in progress")
    if g.creator_id == user.id:
        ids = service.member_ids(g)
        db.delete(g)
        db.commit()
        hub.publish(ids, {"type": "game", "game_id": gid, "event": "deleted"})
        return {"deleted": True}
    g.players.remove(p)
    db.commit()
    service.notify_game(g, "left")
    hub.publish([user.id], {"type": "lobby"})
    return {"ok": True}


class PowerIn(BaseModel):
    power: Optional[str] = None


@router.post("/games/{gid}/power")
def choose_power(gid: int, body: PowerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    p = _member(g, user)
    if g.status != "forming" or g.assignment != "choice":
        raise HTTPException(400, "Powers can't be chosen in this game")
    if body.power is not None:
        if body.power not in service.game_powers(g):
            raise HTTPException(400, "Unknown power")
        if any(o.power == body.power and o.user_id != user.id for o in g.players):
            raise HTTPException(409, "Someone already picked that power")
    p.power = body.power
    db.commit()
    service.notify_game(g)
    return service.serialize_game(g, user.id)


@router.post("/games/{gid}/start")
def start(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    _member(g, user)
    if g.creator_id != user.id:
        raise HTTPException(403, "Only the game's creator can start it")
    if g.status != "forming":
        raise HTTPException(400, "Already started")
    with service.game_lock(gid):
        try:
            service.start_game(db, g)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return service.serialize_game(g, user.id)


@router.get("/games/{gid}/map")
def game_map(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    _member(g, user)
    geo = registry.geometry_for_game(db, g)
    if not geo:
        raise HTTPException(404, "Map not found")
    return geo


class OrdersIn(BaseModel):
    orders: List[str] = Field(max_length=40)


@router.post("/games/{gid}/orders")
def submit_orders(gid: int, body: OrdersIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    p = _member(g, user)
    if g.status != "active" or not p.power:
        raise HTTPException(400, "No orders to give right now")
    with service.game_lock(gid):
        db.refresh(g)
        eng = service.load_engine(g)
        try:
            cleaned = engine.validate_orders(eng, p.power, body.orders)
        except ValueError as e:
            raise HTTPException(400, str(e))
        p.orders = json.dumps(cleaned)
        db.commit()
    service.notify_game(g, "orders")
    return {"orders": cleaned}


class ReadyIn(BaseModel):
    ready: bool


@router.post("/games/{gid}/ready")
def set_ready(gid: int, body: ReadyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    p = _member(g, user)
    if g.status != "active" or not p.power:
        raise HTTPException(400, "Nothing to be ready for")
    p.ready = body.ready
    db.commit()
    processed = service.process_if_ready(gid) if body.ready else False
    if not processed:
        service.notify_game(g, "ready")
    db.expire_all()
    return service.serialize_game(_load_game(db, gid), user.id)


class DrawIn(BaseModel):
    vote: bool


@router.post("/games/{gid}/draw")
def vote_draw(gid: int, body: DrawIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    p = _member(g, user)
    if g.status != "active" or not p.power:
        raise HTTPException(400, "Can't vote now")
    with service.game_lock(gid):
        p.draw_vote = body.vote
        db.commit()
        if not service.check_draw(db, g):
            service.notify_game(g, "draw_vote")
    return service.serialize_game(g, user.id)


@router.get("/games/{gid}/history/{phase}")
def history(gid: int, phase: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    _member(g, user)
    if not g.engine_state:
        raise HTTPException(404, "No history yet")
    h = engine.history_phase(g.engine_state, phase.upper())
    if not h:
        raise HTTPException(404, "No such phase")
    return h


# ==================================================================== press

class MessageIn(BaseModel):
    to: str
    body: str = Field(min_length=1, max_length=2000)


@router.get("/games/{gid}/messages")
def get_messages(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    p = _member(g, user)
    return [service.serialize_message(m) for m in service.visible_messages(db, g, p.power)]


@router.post("/games/{gid}/messages")
def send_message(gid: int, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _load_game(db, gid)
    p = _member(g, user)
    to = body.to.upper()
    if g.status == "forming":
        # Lobby chat before powers exist.
        sender = "LOBBY"
        to = "GLOBAL"
    else:
        if g.status != "active" or not p.power:
            raise HTTPException(400, "Press is closed")
        if g.press == "none":
            raise HTTPException(400, "This is a no-press game")
        if to != "GLOBAL" and (to not in service.game_powers(g) or to == p.power):
            raise HTTPException(400, "Unknown recipient")
        if g.press == "public" and to != "GLOBAL":
            raise HTTPException(400, "Only public press is allowed in this game")
        sender = p.power
    m = Message(game_id=g.id, sender=sender, recipient=to, body=body.body.strip(), phase=g.phase or "")
    if sender == "LOBBY":
        m.body = f"{user.display_name}: {m.body}"
    db.add(m)
    db.commit()
    hub.publish(service.message_audience(g, m), {"type": "message", "game_id": g.id, "message": service.serialize_message(m)})
    return service.serialize_message(m)
