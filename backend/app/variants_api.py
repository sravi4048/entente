"""Map variants: browse, upload (SVG or PNG + mask), review, AI rule interpretation."""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import mapbuild
from .auth import current_user
from .config import MAX_UPLOAD_BYTES
from .db import Game, SessionLocal, User, Variant, get_db
from .hub import hub
from .users import is_admin
from .variants import ai_rules, mapgeom, registry

log = logging.getLogger("entente")
router = APIRouter(prefix="/api")
EXAMPLES = Path(__file__).resolve().parent / "examples"


# ------------------------------------------------------------------ helpers

def _admin_ids(db: Session) -> List[int]:
    return [u.id for u in db.execute(select(User)).scalars() if is_admin(db, u)]


def _get(db: Session, slug: str) -> Variant:
    v = db.execute(select(Variant).where(Variant.slug == slug)).scalar_one_or_none()
    if not v:
        raise HTTPException(404, "Map not found")
    return v


def _can_manage(db: Session, v: Variant, user: User) -> bool:
    return v.author_id == user.id or is_admin(db, user)


def _can_view(db: Session, v: Variant, user: User) -> bool:
    return v.status == "approved" or _can_manage(db, v, user)


def _slugify(db: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "map"
    taken = set(registry.builtin_slugs()) | {"template", "examples"}
    slug, n = base, 2
    while slug in taken or db.execute(select(Variant.id).where(Variant.slug == slug)).first():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _sniff(data: bytes) -> Optional[str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    head = data[:2048].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head:
        return "image/svg+xml"
    return None


async def _read(f: Optional[UploadFile], what: str) -> Optional[bytes]:
    if f is None or not f.filename:
        return None
    data = await f.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The {what} is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    return data or None


def _parse_spec(text: str) -> Dict[str, Any]:
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HTTPException(422, {"errors": [f"The spec isn't valid YAML/JSON: {exc}"], "warnings": []})
    if not isinstance(spec, dict):
        raise HTTPException(422, {"errors": ["The spec must be a YAML/JSON object with name, powers and provinces."], "warnings": []})
    return spec


def _image_size(data: bytes):
    from PIL import Image
    import io

    with Image.open(io.BytesIO(data)) as im:
        return im.size


def build_from_upload(spec: Dict[str, Any], image: Optional[bytes], mask: Optional[bytes]) -> dict:
    """Shared by upload, re-upload and 'apply changes'. Returns everything needed to store a variant."""
    image_type = _sniff(image) if image else None
    if image and image_type is None:
        return {"ok": False, "report": {"errors": ["The map image must be a PNG, JPEG or SVG file."], "warnings": []}}
    if mask and _sniff(mask) != "image/png":
        return {"ok": False, "report": {"errors": ["The province mask must be a PNG (JPEG compression blurs the colors)."], "warnings": []}}

    pre_warn: List[str] = []
    source = "png"
    spec = json.loads(json.dumps(spec))
    if image_type == "image/svg+xml":
        source = "svg"
        provs = [p for p in spec.get("provinces") or [] if isinstance(p, dict)]
        codes = [str(p.get("code", "")).strip().upper() for p in provs]
        auto = mapgeom.auto_colors(codes)
        for p, code in zip(provs, codes):
            if not mapbuild.HEX_RE.match(str(p.get("color") or "")):
                p["color"] = auto[code]
        spec["color_tolerance"] = 0
        try:
            mask, _size, _found, warns = mapgeom.svg_to_mask(image, {c: p["color"] for p, c in zip(provs, codes) if c})
        except ValueError as exc:
            return {"ok": False, "report": {"errors": [str(exc)], "warnings": []}}
        pre_warn += warns
    elif mask is None:
        if image is not None:
            return {"ok": False, "report": {"errors": ["PNG/JPEG maps also need a province mask PNG (or upload an SVG instead)."], "warnings": []}}
        return {"ok": False, "report": {"errors": ["Upload a map image (SVG), or a province mask PNG."], "warnings": []}}
    elif image is not None:
        try:
            iw, ih = _image_size(image)
            mw, mh = _image_size(mask)
        except Exception:
            return {"ok": False, "report": {"errors": ["Couldn't read the uploaded images."], "warnings": []}}
        if abs(iw / ih - mw / mh) > 0.01:
            return {"ok": False, "report": {"errors": [f"The map image ({iw}×{ih}) and mask ({mw}×{mh}) must have the same shape."], "warnings": []}}
        if (iw, ih) != (mw, mh):
            pre_warn.append(f"The map image is {iw}×{ih} and the mask {mw}×{mh}; the image will be scaled to match.")

    res = mapbuild.build(spec, mask, has_display=image is not None)
    res.warnings = pre_warn + res.warnings
    if res.ok:
        mapbuild.engine_check(registry.ensure_map_file(res.map_text), res)
    return {
        "ok": res.ok,
        "report": res.report(),
        "geometry": res.geometry if res.ok else None,
        "map_text": res.map_text if res.ok else None,
        "spec": spec,
        "mask": mask,
        "image": image,
        "image_type": image_type,
        "source": source,
    }


def _run_ai(variant_id: int) -> None:
    db = SessionLocal()
    try:
        v = db.get(Variant, variant_id)
        if not v:
            return
        try:
            out = ai_rules.interpret(json.loads(v.spec_json), json.loads(v.report_json))
        except ai_rules.AIError as exc:
            out = {"error": str(exc)}
        v.ai_json = json.dumps(out)
        db.commit()
        hub.publish(list({v.author_id, *_admin_ids(db)}), {"type": "variants", "slug": v.slug})
    finally:
        db.close()


def _detail(db: Session, v: Variant, user: User) -> dict:
    ref = registry.resolve(db, v.slug)
    manage = _can_manage(db, v, user)
    out = {
        **ref.brief(),
        "source_format": v.source_format,
        "has_image": v.image is not None,
        "report": json.loads(v.report_json),
        "version": v.version,
        "created_at": v.created_at,
        "updated_at": v.updated_at,
        "review_note": v.review_note,
        "can_manage": manage,
        "can_review": is_admin(db, user),
        "games": db.execute(select(func.count(Game.id)).where(Game.variant == v.slug)).scalar(),
    }
    if manage:
        out["ai"] = json.loads(v.ai_json) if v.ai_json else None
        out["ai_enabled"] = ai_rules.enabled()
    return out


# ---------------------------------------------------------------- browsing

@router.get("/variants")
def list_variants(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return registry.list_all(db, user.id, is_admin(db, user))


@router.get("/variants/{slug}")
def variant_detail(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ref = registry.resolve(db, slug)
    if not ref:
        raise HTTPException(404, "Map not found")
    if ref.builtin:
        return {**ref.brief(), "can_manage": False, "can_review": False, "has_image": False}
    v = _get(db, slug)
    if not _can_view(db, v, user):
        raise HTTPException(404, "Map not found")
    return _detail(db, v, user)


@router.get("/variants/{slug}/map")
def variant_map(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ref = registry.resolve(db, slug)
    if not ref:
        raise HTTPException(404, "Map not found")
    if ref.builtin:
        return registry.builtin_geometry(slug)
    v = _get(db, slug)
    if not _can_view(db, v, user):
        raise HTTPException(404, "Map not found")
    return registry.with_image_url(json.loads(v.geometry_json), slug)


_START_CACHE: Dict[str, dict] = {}


@router.get("/variants/{slug}/start")
def variant_start(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The opening position, for previews in the lobby and game rooms."""
    from . import engine

    ref = registry.resolve(db, slug)
    if not ref:
        raise HTTPException(404, "Map not found")
    if not ref.builtin and not _can_view(db, _get(db, slug), user):
        raise HTTPException(404, "Map not found")
    if ref.engine_map not in _START_CACHE:
        _START_CACHE[ref.engine_map] = engine.board(engine.new_game(ref.engine_map))
    return _START_CACHE[ref.engine_map]


@router.get("/variants/{slug}/image")
def variant_image(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _get(db, slug)
    if not v.image:
        raise HTTPException(404, "This map has no artwork")
    # Uploaded SVGs are drawn with <image>, where scripts never run; the CSP also
    # neuters them if someone opens the URL directly.
    return Response(
        v.image,
        media_type=v.image_type or "application/octet-stream",
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
            "ETag": f'"{v.slug}-{v.version}"',
        },
    )


@router.get("/variants/{slug}/files/{name}")
def variant_file(slug: str, name: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _get(db, slug)
    if not _can_view(db, v, user):
        raise HTTPException(404, "Map not found")
    if name == "spec.yaml":
        body = yaml.safe_dump(json.loads(v.spec_json), sort_keys=False, allow_unicode=True)
        return Response(body, media_type="text/yaml", headers={"Content-Disposition": f'attachment; filename="{slug}.yaml"'})
    if name == "mask.png":
        return Response(v.mask_png, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{slug}-mask.png"'})
    if name == "engine.map":
        return Response(v.map_text, media_type="text/plain")
    raise HTTPException(404, "Unknown file")


@router.get("/examples/{name}")
def example_file(name: str, user: User = Depends(current_user)):
    allowed = {"spec.yaml": "text/yaml", "map.png": "image/png", "mask.png": "image/png", "map.svg": "image/svg+xml"}
    if name not in allowed:
        raise HTTPException(404, "Unknown file")
    return FileResponse(EXAMPLES / "toy-islands" / name, media_type=allowed[name], filename=f"toy-islands-{name}")


# ----------------------------------------------------------------- upload

@router.post("/variants")
async def upload_variant(
    background: BackgroundTasks,
    spec_file: Optional[UploadFile] = File(default=None),
    spec_text: Optional[str] = Form(default=None),
    image: Optional[UploadFile] = File(default=None),
    mask: Optional[UploadFile] = File(default=None),
    dry_run: bool = Form(default=False),
    replace: Optional[str] = Form(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    raw = await _read(spec_file, "spec")
    text = raw.decode("utf-8", errors="replace") if raw else (spec_text or "")
    if not text.strip():
        raise HTTPException(422, {"errors": ["Include the spec (YAML or JSON)."], "warnings": []})
    spec = _parse_spec(text)
    img, msk = await _read(image, "map image"), await _read(mask, "province mask")

    existing = None
    if replace:
        existing = _get(db, replace)
        if not _can_manage(db, existing, user):
            raise HTTPException(403, "You can only update your own maps")
        if existing.status == "approved" and not is_admin(db, user):
            raise HTTPException(400, "This map is already live; ask the admin to update it")
        if img is None and msk is None:  # spec-only edit: reuse stored art
            img = existing.image
            msk = existing.mask_png if existing.source_format == "png" else None

    from starlette.concurrency import run_in_threadpool

    built = await run_in_threadpool(build_from_upload, spec, img, msk)
    if not built["ok"]:
        raise HTTPException(422, built["report"])
    if dry_run:
        return {"ok": True, "report": built["report"], "geometry": built["geometry"]}

    name = built["spec"].get("name") or "Untitled map"
    if existing:
        v = existing
        v.version += 1
        if v.status == "rejected":
            v.status = "pending"
    else:
        v = Variant(slug=_slugify(db, name), author_id=user.id, status="pending")
        db.add(v)
    v.name = name[:60]
    v.description = built["spec"].get("description", "")
    v.source_format = built["source"]
    v.spec_json = json.dumps(built["spec"])
    v.map_text = built["map_text"]
    v.geometry_json = json.dumps(built["geometry"])
    v.report_json = json.dumps(built["report"])
    v.mask_png = built["mask"]
    v.image = built["image"]
    v.image_type = built["image_type"]
    v.ai_json = None
    db.commit()
    hub.publish(list({user.id, *_admin_ids(db)}), {"type": "variants", "slug": v.slug})
    if ai_rules.enabled() and (built["spec"].get("rules") or "").strip():
        background.add_task(_run_ai, v.id)
    return _detail(db, v, user)


# ----------------------------------------------------------------- review

class ReviewIn(BaseModel):
    action: str = Field(pattern="^(approve|reject|unpublish)$")
    note: Optional[str] = Field(default=None, max_length=2000)


@router.post("/variants/{slug}/review")
def review(slug: str, body: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not is_admin(db, user):
        raise HTTPException(403, "Only the admin can review maps")
    v = _get(db, slug)
    v.status = {"approve": "approved", "reject": "rejected", "unpublish": "pending"}[body.action]
    v.review_note = (body.note or "").strip() or None
    db.commit()
    hub.publish(list({v.author_id, *_admin_ids(db)}), {"type": "variants", "slug": v.slug})
    return _detail(db, v, user)


@router.post("/variants/{slug}/ai")
def run_ai(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _get(db, slug)
    if not _can_manage(db, v, user):
        raise HTTPException(403, "Not your map")
    try:
        out = ai_rules.interpret(json.loads(v.spec_json), json.loads(v.report_json))
    except ai_rules.AIError as exc:
        raise HTTPException(503, str(exc))
    v.ai_json = json.dumps(out)
    db.commit()
    return _detail(db, v, user)


class ApplyIn(BaseModel):
    changes: List[Dict[str, Any]] = Field(max_length=200)


@router.post("/variants/{slug}/apply")
def apply_changes(slug: str, body: ApplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Apply AI proposals or hand edits (same change format), then rebuild and re-validate."""
    v = _get(db, slug)
    if not _can_manage(db, v, user):
        raise HTTPException(403, "Not your map")
    if v.status == "approved" and not is_admin(db, user):
        raise HTTPException(400, "This map is live; ask the admin to change it")
    spec = mapbuild.merge_spec_changes(json.loads(v.spec_json), body.changes)
    # rebuild from the stored mask (SVG uploads already have their mask rasterised)
    built = build_from_upload(spec, v.image if v.source_format == "png" else None, v.mask_png)
    if not built["ok"]:
        raise HTTPException(422, built["report"])
    v.spec_json = json.dumps(spec)
    v.map_text = built["map_text"]
    v.geometry_json = json.dumps({**built["geometry"], "style": "image" if v.image else "flat"})
    v.report_json = json.dumps(built["report"])
    v.version += 1
    if v.ai_json:
        ai = json.loads(v.ai_json)
        applied = {json.dumps(c, sort_keys=True) for c in body.changes}
        for c in ai.get("changes", []):
            if json.dumps(c, sort_keys=True) in applied:
                c["applied"] = True
        v.ai_json = json.dumps(ai)
    db.commit()
    return _detail(db, v, user)


@router.delete("/variants/{slug}")
def delete_variant(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _get(db, slug)
    if not _can_manage(db, v, user):
        raise HTTPException(403, "Not your map")
    used = db.execute(select(func.count(Game.id)).where(Game.variant == slug)).scalar()
    if used:
        raise HTTPException(400, f"{used} game(s) use this map. Reject or unpublish it instead.")
    if v.status == "approved" and not is_admin(db, user):
        raise HTTPException(400, "This map is live; ask the admin to remove it")
    db.delete(v)
    db.commit()
    hub.publish(list({user.id, *_admin_ids(db)}), {"type": "variants", "slug": slug})
    return {"ok": True}
