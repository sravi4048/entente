"""Game lifecycle: starting, serialising, adjudicating, deadlines, draws."""
import json
import logging
import random
import threading
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import engine
from .db import Game, GamePlayer, Message, SessionLocal, User, utcnow
from .hub import hub
from .variants import registry

log = logging.getLogger("entente")

_locks: Dict[int, threading.Lock] = defaultdict(threading.Lock)


def game_lock(game_id: int) -> threading.Lock:
    return _locks[game_id]


def user_brief(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name}


def member_ids(game: Game) -> List[int]:
    return [p.user_id for p in game.players]


def notify_game(game: Game, event: str = "update") -> None:
    hub.publish(member_ids(game), {"type": "game", "game_id": game.id, "event": event})


def _deadline(game: Game):
    if game.deadline_minutes:
        return utcnow() + timedelta(minutes=game.deadline_minutes)
    return None


def player_for(game: Game, user_id: int) -> Optional[GamePlayer]:
    for p in game.players:
        if p.user_id == user_id:
            return p
    return None


def load_engine(game: Game):
    """Engine object for a started game, on whatever map it was started with."""
    db = Session.object_session(game)
    return engine.load(game.engine_state, registry.engine_map_for_game(db, game))


def variant_of(game: Game) -> Optional[registry.VariantRef]:
    return registry.resolve(Session.object_session(game), game.variant or registry.DEFAULT_SLUG)


def game_powers(game: Game) -> List[str]:
    if game.engine_state:
        return engine.powers(load_engine(game))
    ref = variant_of(game)
    return sorted(p["name"] for p in ref.powers) if ref else list(engine.CLASSIC_POWERS)


# ---------------------------------------------------------------- serialise

def serialize_summary(game: Game, user_id: int) -> dict:
    me = player_for(game, user_id)
    needs = False
    centers = None
    if game.status == "active" and me and me.power and game.engine_state:
        eng = load_engine(game)
        needs = engine.needs_orders(eng, me.power) and not me.ready
        centers = len(eng.get_centers(me.power))
    return {
        "id": game.id,
        "name": game.name,
        "status": game.status,
        "phase": game.phase,
        "phase_label": engine.phase_label(game.phase),
        "deadline_at": game.deadline_at,
        "deadline_minutes": game.deadline_minutes,
        "player_count": len(game.players),
        "my_power": me.power if me else None,
        "my_centers": centers,
        "needs_orders": needs,
        "result": json.loads(game.result) if game.result else None,
        "creator": user_brief(game.creator),
        "updated_at": game.updated_at,
        "variant": _variant_brief(game),
    }


def _variant_brief(game: Game) -> dict:
    ref = variant_of(game)
    if not ref:
        return {"slug": game.variant, "name": game.variant, "builtin": False, "players": 7}
    return {"slug": ref.slug, "name": ref.name, "builtin": ref.builtin, "players": len(ref.powers),
            "victory": ref.victory, "status": ref.status}


def serialize_game(game: Game, user_id: int) -> dict:
    me = player_for(game, user_id)
    out = serialize_summary(game, user_id)
    out.update(
        {
            "assignment": game.assignment,
            "press": game.press,
            "invite_code": game.invite_code if me else None,
            "is_creator": game.creator_id == user_id,
            "is_member": me is not None,
            "server_time": utcnow(),
            "powers": game_powers(game),
        }
    )
    eng = load_engine(game) if game.engine_state else None

    players = []
    for p in game.players:
        needs = bool(eng and p.power and game.status == "active" and engine.needs_orders(eng, p.power))
        players.append(
            {
                **user_brief(p.user),
                "user_id": p.user_id,
                "power": p.power,
                "ready": p.ready,
                "needs_orders": needs,
                "has_orders": bool(json.loads(p.orders)),
                "draw_vote": p.draw_vote,
                "online": hub.online(p.user_id),
            }
        )
    out["players"] = players

    if eng:
        out["board"] = engine.board(eng)
        out["history"] = engine.history_index(game.engine_state)
        if me and me.power and game.status == "active":
            out["my_orders"] = json.loads(me.orders)
            out["possible_orders"] = engine.possible_orders(eng, me.power)
            out["ready"] = me.ready
            out["draw_vote"] = me.draw_vote
        else:
            out["my_orders"] = []
            out["possible_orders"] = {}
    return out


# ------------------------------------------------------------------- start

def start_game(db: Session, game: Game) -> None:
    ref = variant_of(game)
    if ref is None:
        raise ValueError("This game's map no longer exists")
    if not ref.builtin:
        from .db import Variant

        v = db.execute(select(Variant).where(Variant.slug == ref.slug)).scalar_one()
        game.map_text = v.map_text
        game.geometry_json = v.geometry_json
        eng = engine.new_game(registry.ensure_map_file(v.map_text))
    else:
        eng = engine.new_game(ref.engine_map)
    all_powers = engine.powers(eng)
    if game.assignment == "random":
        for p in game.players:
            p.power = None
    taken = {p.power for p in game.players if p.power}
    free = [pw for pw in all_powers if pw not in taken]
    random.shuffle(free)
    for p in game.players:
        if not p.power:
            p.power = free.pop()
        p.orders = "[]"
        p.ready = False
        p.draw_vote = False
    game.status = "active"
    game.engine_state = engine.dump(eng)
    game.phase = eng.get_current_phase()
    game.deadline_at = _deadline(game)
    db.commit()
    notify_game(game, "started")


# ------------------------------------------------------------- adjudicate

def _humans_needing_orders(game: Game, eng) -> List[GamePlayer]:
    return [p for p in game.players if p.power and engine.needs_orders(eng, p.power)]


def process_if_ready(game_id: int, force: bool = False) -> bool:
    """Adjudicate the current phase if everyone is ready (or `force`, i.e. deadline hit).

    Opens its own DB session and holds the per-game lock so concurrent
    'ready' clicks and the deadline scheduler cannot double-process.
    """
    with game_lock(game_id):
        db = SessionLocal()
        try:
            q = select(Game).where(Game.id == game_id)
            if db.bind.dialect.name == "postgresql":
                q = q.with_for_update()
            game = db.execute(q).scalar_one_or_none()
            if not game or game.status != "active" or not game.engine_state:
                return False
            eng = load_engine(game)
            waiting = _humans_needing_orders(game, eng)
            if not force and any(not p.ready for p in waiting):
                return False

            orders = {p.power: json.loads(p.orders) for p in game.players if p.power}
            engine.process(eng, orders)
            # Skip phases where only civil-disorder powers have anything to do.
            guard = 0
            while not engine.is_done(eng) and not _humans_needing_orders(game, eng) and guard < 12:
                engine.process(eng, {})
                guard += 1

            game.engine_state = engine.dump(eng)
            game.phase = eng.get_current_phase()
            for p in game.players:
                p.orders = "[]"
                p.ready = False
            if engine.is_done(eng):
                winner = engine.solo_winner(eng)
                game.status = "finished"
                game.deadline_at = None
                game.result = json.dumps(
                    {"type": "solo", "powers": [winner]} if winner else {"type": "draw", "powers": engine.alive_powers(eng)}
                )
            else:
                game.deadline_at = _deadline(game)
            db.commit()
            notify_game(game, "processed")
            return True
        except Exception:
            db.rollback()
            log.exception("failed to process game %s", game_id)
            return False
        finally:
            db.close()


def check_draw(db: Session, game: Game) -> bool:
    if game.status != "active":
        return False
    eng = load_engine(game)
    alive = set(engine.alive_powers(eng))
    voters = [p for p in game.players if p.power in alive]
    if voters and all(p.draw_vote for p in voters):
        game.status = "finished"
        game.deadline_at = None
        game.result = json.dumps({"type": "draw", "powers": sorted(alive)})
        db.commit()
        notify_game(game, "finished")
        return True
    return False


def due_game_ids() -> List[int]:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Game.id).where(Game.status == "active", Game.deadline_at.is_not(None), Game.deadline_at <= utcnow())
        ).scalars()
        return list(rows)
    finally:
        db.close()


# ------------------------------------------------------------------- press

def visible_messages(db: Session, game: Game, power: Optional[str]) -> List[Message]:
    q = select(Message).where(Message.game_id == game.id).order_by(Message.id)
    msgs = list(db.execute(q).scalars())
    if game.status == "finished":
        return msgs  # all press is revealed once the game is over
    if not power:
        return [m for m in msgs if m.recipient == "GLOBAL"]
    return [m for m in msgs if m.recipient in ("GLOBAL", power) or m.sender == power]


def serialize_message(m: Message) -> dict:
    return {
        "id": m.id,
        "sender": m.sender,
        "recipient": m.recipient,
        "body": m.body,
        "phase": m.phase,
        "created_at": m.created_at,
    }


def message_audience(game: Game, m: Message) -> List[int]:
    if m.recipient == "GLOBAL":
        return member_ids(game)
    return [p.user_id for p in game.players if p.power in (m.sender, m.recipient)]
