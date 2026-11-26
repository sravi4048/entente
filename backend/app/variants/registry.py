"""One place to look up a variant by slug, whether built-in or uploaded."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import MAPS_CACHE_DIR
from ..db import Game, Variant

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "maps"
DEFAULT_SLUG = "classic"


@dataclass
class VariantRef:
    slug: str
    name: str
    description: str
    builtin: bool
    status: str  # builtin | approved | pending | rejected
    engine_map: str  # engine map name, or path to a generated .map file
    powers: List[dict] = field(default_factory=list)  # [{name, adjective, color}]
    victory: int = 18
    supply_centers: int = 34
    author: Optional[dict] = None
    rules_text: str = ""
    db_id: Optional[int] = None

    def brief(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "builtin": self.builtin,
            "status": self.status,
            "players": len(self.powers),
            "powers": self.powers,
            "victory": self.victory,
            "supply_centers": self.supply_centers,
            "author": self.author,
            "rules_text": self.rules_text,
        }


@lru_cache(maxsize=1)
def _builtin_meta() -> Dict[str, dict]:
    return json.loads((BUILTIN_DIR / "builtin.json").read_text())


@lru_cache(maxsize=16)
def builtin_geometry(slug: str) -> dict:
    return json.loads((BUILTIN_DIR / f"{slug}.json").read_text())


@lru_cache(maxsize=16)
def _engine_stats(map_name: str) -> tuple:
    from diplomacy import Game as EngineGame

    g = EngineGame(map_name=map_name)
    return int(g.victory[0]), len(g.map.scs), tuple(sorted(g.powers))


def ensure_map_file(map_text: str) -> str:
    """Content-addressed copy of a generated map on disk (the engine loads maps by path)."""
    MAPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(map_text.encode()).hexdigest()[:16]
    path = MAPS_CACHE_DIR / f"{digest}.map"
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_text(map_text)
        tmp.replace(path)
    return str(path)


def _builtin(slug: str) -> Optional[VariantRef]:
    meta = _builtin_meta().get(slug)
    if not meta:
        return None
    geo = builtin_geometry(slug)
    victory, scs, _ = _engine_stats(meta["map"])
    return VariantRef(
        slug=slug, name=meta["name"], description=meta["description"], builtin=True, status="builtin",
        engine_map=meta["map"], powers=geo["powers"], victory=victory, supply_centers=scs,
    )


def _custom(v: Variant) -> VariantRef:
    geo = json.loads(v.geometry_json)
    report = json.loads(v.report_json)
    spec = json.loads(v.spec_json)
    return VariantRef(
        slug=v.slug, name=v.name, description=v.description, builtin=False, status=v.status,
        engine_map=ensure_map_file(v.map_text), powers=geo.get("powers", []),
        victory=int(report.get("stats", {}).get("victory") or 0),
        supply_centers=int(report.get("stats", {}).get("supply_centers") or 0),
        author={"id": v.author.id, "username": v.author.username, "display_name": v.author.display_name},
        rules_text=spec.get("rules", ""), db_id=v.id,
    )


def builtin_slugs() -> List[str]:
    return list(_builtin_meta().keys())


def resolve(db: Session, slug: str) -> Optional[VariantRef]:
    ref = _builtin(slug)
    if ref:
        return ref
    v = db.execute(select(Variant).where(Variant.slug == slug)).scalar_one_or_none()
    return _custom(v) if v else None


def can_play(ref: VariantRef, user_id: int, is_admin: bool) -> bool:
    if ref.builtin or ref.status == "approved":
        return True
    # Authors and admins may playtest a map that's still waiting for review.
    return ref.status == "pending" and (is_admin or (ref.author and ref.author["id"] == user_id))


def geometry_for_game(db: Session, game: Game) -> Optional[dict]:
    if game.geometry_json:
        geo = json.loads(game.geometry_json)
    else:
        ref = resolve(db, game.variant or DEFAULT_SLUG)
        if not ref:
            return None
        geo = builtin_geometry(ref.slug) if ref.builtin else json.loads(
            db.execute(select(Variant.geometry_json).where(Variant.slug == ref.slug)).scalar_one()
        )
    return with_image_url(geo, game.variant or DEFAULT_SLUG)


def with_image_url(geo: dict, slug: str) -> dict:
    if geo.get("style") == "image":
        geo = {**geo, "image": f"/api/variants/{slug}/image"}
    return geo


def engine_map_for_game(db: Session, game: Game) -> str:
    if game.map_text:
        return ensure_map_file(game.map_text)
    ref = resolve(db, game.variant or DEFAULT_SLUG)
    if not ref:
        raise LookupError(f"Unknown variant {game.variant}")
    return ref.engine_map


def list_all(db: Session, user_id: int, is_admin: bool) -> Dict[str, list]:
    builtin = [r.brief() for r in (_builtin(s) for s in builtin_slugs()) if r]
    rows = list(db.execute(select(Variant).order_by(Variant.created_at.desc())).scalars())
    approved, mine, queue = [], [], []
    for v in rows:
        ref = _custom(v)
        b = {**ref.brief(), "updated_at": v.updated_at, "review_note": v.review_note}
        if v.status == "approved":
            approved.append(b)
        if v.author_id == user_id and v.status != "approved":
            mine.append(b)
        if is_admin and v.status == "pending":
            queue.append(b)
    return {"builtin": builtin, "approved": approved, "mine": mine, "queue": queue}
