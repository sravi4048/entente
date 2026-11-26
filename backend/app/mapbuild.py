"""Turn an uploaded map (province-mask PNG + spec JSON) into:

* an engine `.map` file (adjacencies, powers, units, centers) the adjudicator loads,
* render geometry (province outlines, unit/center/label positions) for the UI,
* a report (errors, warnings, the adjacency list) for the uploader and reviewer.

The mask is a PNG where every province is painted one flat color listed in the
spec. Province outlines, unit positions and a draft adjacency list are all
derived from it; the spec's `adjacency.add/remove` lists fix the exceptions.
"""
from __future__ import annotations

import io
import json
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

MAX_SIDE = 4096
MIN_SIDE = 200
MIN_PIXELS = 30
GROW_PX = 6  # border lines up to ~2*GROW_PX wide are absorbed into neighbouring provinces
MIN_BORDER = 4  # pixel-pairs of shared edge needed to call two provinces adjacent
RESERVED = {"VIA", "ALL", "UNO"}
CODE_RE = re.compile(r"^[A-Z]{3}$")
COAST_RE = re.compile(r"^[A-Z]{2}$")
POWER_RE = re.compile(r"^[A-Z][A-Z_]{1,15}$")
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
REL_TYPES = ("both", "army", "fleet")

DEFAULT_COLORS = ["#c8453c", "#33509f", "#4b9be0", "#5e544a", "#3f9a55", "#8b5dc4", "#dfae35",
                  "#e07b39", "#2fa3a0", "#d0607a", "#7a8b2f", "#a0522d"]


class SpecError(Exception):
    pass


@dataclass
class Result:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    map_text: Optional[str] = None
    geometry: Optional[dict] = None
    adjacency: List[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def report(self) -> dict:
        return {"errors": self.errors, "warnings": self.warnings, "adjacency": self.adjacency, "stats": self.stats}


def _hex(c: str) -> Tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


# --------------------------------------------------------------------- spec

def normalize_spec(raw: dict, res: Result) -> dict:
    """Validate the spec's shape; returns a cleaned copy. Problems go to res.errors."""
    if not isinstance(raw, dict):
        raise SpecError("The spec must be a JSON object")
    e = res.errors
    spec = {
        "name": str(raw.get("name") or "").strip()[:60],
        "description": str(raw.get("description") or "").strip()[:1000],
        "start_year": raw.get("start_year", 1901),
        "victory": raw.get("victory"),
        "build_anywhere": bool(raw.get("build_anywhere", False)),
        "rules": str(raw.get("rules") or "").strip()[:4000],
        "color_tolerance": raw.get("color_tolerance", 10),
        "provinces": [],
        "powers": [],
        "adjacency": {"add": [], "remove": []},
    }
    if not spec["name"]:
        e.append("Give the map a name.")
    if not isinstance(spec["start_year"], int) or not (1 <= spec["start_year"] <= 9999):
        e.append("start_year must be a whole number between 1 and 9999.")
        spec["start_year"] = 1901
    if not isinstance(spec["color_tolerance"], int) or not (0 <= spec["color_tolerance"] <= 40):
        e.append("color_tolerance must be a whole number from 0 to 40.")
        spec["color_tolerance"] = 10

    codes, names, colors = set(), set(), {}
    for i, p in enumerate(raw.get("provinces") or []):
        where = f"Province #{i + 1}"
        if not isinstance(p, dict):
            e.append(f"{where} must be an object.")
            continue
        code = str(p.get("code") or "").strip().upper()
        where = f"Province {code or '#' + str(i + 1)}"
        if not CODE_RE.match(code):
            e.append(f"{where}: code must be exactly 3 letters (A–Z).")
        elif code in RESERVED:
            e.append(f"{where}: {code} is reserved, pick another code.")
        elif code in codes:
            e.append(f"{where}: duplicate code.")
        codes.add(code)
        name = str(p.get("name") or "").strip()
        if not name or "=" in name or len(name) > 40:
            e.append(f"{where}: needs a name (max 40 characters, no '=').")
        elif name.lower() in names:
            e.append(f"{where}: another province is already called '{name}'.")
        names.add(name.lower())
        color = str(p.get("color") or "").strip()
        if not HEX_RE.match(color):
            e.append(f"{where}: color must be a hex code like #a1b2c3.")
            color = "#000000"
        color = "#" + color.lstrip("#").lower()
        if color in colors:
            e.append(f"{where}: color {color} is also used by {colors[color]}.")
        colors[color] = code
        ptype = str(p.get("type") or "land").strip().lower()
        if ptype == "water":
            ptype = "sea"
        if ptype not in ("land", "sea", "coast"):
            e.append(f"{where}: type must be 'land' or 'sea'.")
            ptype = "land"
        coasts = []
        for c in p.get("coasts") or []:
            cname = str((c or {}).get("name") or "").strip().upper()
            seas = [str(s).strip().upper() for s in (c or {}).get("seas") or []]
            if not COAST_RE.match(cname):
                e.append(f"{where}: coast names must be 2 letters, like NC or SC.")
            if not seas:
                e.append(f"{where}: coast {cname} must list the seas it touches.")
            coasts.append({"name": cname, "seas": seas})
        if coasts and ptype == "sea":
            e.append(f"{where}: only land provinces can have split coasts.")
        if len(coasts) == 1:
            e.append(f"{where}: a split-coast province needs at least two coasts (or none).")
        spec["provinces"].append({
            "code": code, "name": name, "color": color, "type": ptype,
            "sc": bool(p.get("sc", False)), "impassable": bool(p.get("impassable", False)), "coasts": coasts,
        })
    if len(spec["provinces"]) < 4:
        e.append("A map needs at least 4 provinces.")
    if len(spec["provinces"]) > 400:
        e.append("Maps are limited to 400 provinces.")

    pnames = set()
    for i, pw in enumerate(raw.get("powers") or []):
        if not isinstance(pw, dict):
            e.append(f"Power #{i + 1} must be an object.")
            continue
        name = re.sub(r"\s+", "_", str(pw.get("name") or "").strip().upper())
        where = f"Power {name or '#' + str(i + 1)}"
        if not POWER_RE.match(name) or name in ("UNOWNED", "NEUTRAL", "GLOBAL", "LOBBY"):
            e.append(f"{where}: name must be 2–16 letters (A–Z), e.g. FRANCE.")
        elif len(name.replace("_", "")) == 3:
            e.append(f"{where}: power names can't be exactly 3 letters (they'd look like a province code).")
        elif name in pnames:
            e.append(f"{where}: duplicate power name.")
        elif name in codes:
            e.append(f"{where}: a power can't share a name with a province code.")
        pnames.add(name)
        adj = re.sub(r"[^A-Za-z]", "", str(pw.get("adjective") or name.title())) or name.title()
        color = str(pw.get("color") or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]).strip()
        if not HEX_RE.match(color):
            e.append(f"{where}: color must be a hex code like #c8453c.")
            color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        homes = [str(h).strip().upper() for h in pw.get("homes") or []]
        units = [" ".join(str(u).strip().upper().split()) for u in pw.get("units") or []]
        spec["powers"].append({"name": name, "adjective": adj[:20], "color": "#" + color.lstrip("#").lower(),
                               "homes": homes, "units": units})
    if not (2 <= len(spec["powers"]) <= 20):
        e.append("A map needs between 2 and 20 powers.")

    adj = raw.get("adjacency") or {}
    for item in adj.get("add") or []:
        if not (isinstance(item, list) and len(item) in (2, 3)):
            e.append(f"adjacency.add entries look like [\"AAA\", \"BBB\", \"both\"]; got {json.dumps(item)}.")
            continue
        rel = str(item[2]).lower() if len(item) == 3 else "both"
        if rel not in REL_TYPES:
            e.append(f"adjacency.add: type must be both, army or fleet; got {json.dumps(item)}.")
            continue
        spec["adjacency"]["add"].append([str(item[0]).upper(), str(item[1]).upper(), rel])
    for item in adj.get("remove") or []:
        if not (isinstance(item, list) and len(item) == 2):
            e.append(f"adjacency.remove entries look like [\"AAA\", \"BBB\"]; got {json.dumps(item)}.")
            continue
        spec["adjacency"]["remove"].append([str(item[0]).upper(), str(item[1]).upper()])
    return spec


# --------------------------------------------------------------------- mask

def load_image(data: bytes, what: str) -> np.ndarray:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise SpecError(f"The {what} isn't a readable PNG/JPEG image.")
    w, h = img.size
    if max(w, h) > MAX_SIDE or min(w, h) < MIN_SIDE:
        raise SpecError(f"The {what} must be between {MIN_SIDE} and {MAX_SIDE} pixels on each side (got {w}×{h}).")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        img = Image.alpha_composite(bg, img)
    return np.array(img.convert("RGB"))


def label_mask(rgb: np.ndarray, provinces: List[dict], tol: int, res: Result) -> np.ndarray:
    h, w, _ = rgb.shape
    labels = np.zeros((h, w), dtype=np.int32)
    px = rgb.astype(np.int32)
    cols = [_hex(p["color"]) for p in provinces]
    for i, a in enumerate(cols):
        for j in range(i + 1, len(cols)):
            b = cols[j]
            if max(abs(a[k] - b[k]) for k in range(3)) <= 2 * tol:
                res.errors.append(
                    f"Colors of {provinces[i]['code']} and {provinces[j]['code']} are too similar to tell apart "
                    f"(lower color_tolerance or make them more different)."
                )
    for idx, (r, g, b) in enumerate(cols, start=1):
        hit = (np.abs(px[..., 0] - r) <= tol) & (np.abs(px[..., 1] - g) <= tol) & (np.abs(px[..., 2] - b) <= tol)
        labels[hit & (labels == 0)] = idx
    return labels


def grow(labels: np.ndarray, steps: int) -> np.ndarray:
    """Let provinces spread into unassigned pixels (border lines, anti-aliasing) a few pixels deep."""
    out = labels.copy()
    for _ in range(steps):
        empty = out == 0
        if not empty.any():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            shifted = np.zeros_like(out)
            ys = slice(max(dy, 0), out.shape[0] + min(dy, 0))
            yd = slice(max(-dy, 0), out.shape[0] + min(-dy, 0))
            xs = slice(max(dx, 0), out.shape[1] + min(dx, 0))
            xd = slice(max(-dx, 0), out.shape[1] + min(-dx, 0))
            shifted[yd, xd] = out[ys, xs]
            fill = empty & (shifted > 0)
            out[fill] = shifted[fill]
            empty = out == 0
    return out


def borders(labels: np.ndarray) -> Dict[Tuple[int, int], np.ndarray]:
    """Map (a, b) label pairs (a < b) to an array of (y, x) pixels on their shared edge."""
    pairs: Dict[Tuple[int, int], list] = {}
    for a_sl, b_sl in (
        ((slice(None), slice(0, -1)), (slice(None), slice(1, None))),
        ((slice(0, -1), slice(None)), (slice(1, None), slice(None))),
    ):
        a = labels[a_sl]
        b = labels[b_sl]
        diff = (a != b) & (a > 0) & (b > 0)
        ys, xs = np.nonzero(diff)
        lo = np.minimum(a[diff], b[diff])
        hi = np.maximum(a[diff], b[diff])
        keys = lo.astype(np.int64) * 100000 + hi
        order = np.argsort(keys, kind="stable")
        keys, ys, xs = keys[order], ys[order], xs[order]
        uniq, starts = np.unique(keys, return_index=True)
        ends = list(starts[1:]) + [len(keys)]
        for k, s, t in zip(uniq, starts, ends):
            key = (int(k // 100000), int(k % 100000))
            pairs.setdefault(key, []).append(np.stack([ys[s:t], xs[s:t]], axis=1))
    return {k: np.concatenate(v) for k, v in pairs.items()}


def interior_points(mask: np.ndarray, n: int, min_gap: float) -> List[Tuple[float, float, float]]:
    """Up to n well-separated points deep inside a binary mask: (x, y, inradius)."""
    m = np.pad(mask.astype(np.uint8), 1)
    dist = cv2.distanceTransform(m, cv2.DIST_L2, 5)[1:-1, 1:-1]
    pts = []
    work = dist.copy()
    for _ in range(n):
        idx = int(np.argmax(work))
        y, x = divmod(idx, work.shape[1])
        r = float(work[y, x])
        if r <= 0:
            break
        pts.append((float(x), float(y), float(dist[y, x])))
        yy, xx = np.ogrid[: work.shape[0], : work.shape[1]]
        work[(yy - y) ** 2 + (xx - x) ** 2 <= min_gap ** 2] = 0
    return pts


def contour_path(mask: np.ndarray, ox: int, oy: int) -> str:
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    parts = []
    for c in cnts:
        if cv2.contourArea(c) < 4:
            continue
        c = cv2.approxPolyDP(c, 0.8, True)
        pts = c.reshape(-1, 2)
        if len(pts) < 3:
            continue
        parts.append("M" + " L".join(f"{x + ox} {y + oy}" for x, y in pts) + " Z")
    return " ".join(parts)


# ---------------------------------------------------------------- the build

def build(spec_raw: dict, mask_png: bytes, has_display: bool = False) -> Result:
    res = Result()
    try:
        spec = normalize_spec(spec_raw, res)
    except SpecError as exc:
        res.errors.append(str(exc))
        return res
    if res.errors:
        return res
    provs = spec["provinces"]
    by_code = {p["code"]: p for p in provs}
    idx_of = {p["code"]: i + 1 for i, p in enumerate(provs)}

    try:
        rgb = load_image(mask_png, "province mask")
    except SpecError as exc:
        res.errors.append(str(exc))
        return res
    h, w, _ = rgb.shape
    raw_labels = label_mask(rgb, provs, spec["color_tolerance"], res)
    counts = np.bincount(raw_labels.ravel(), minlength=len(provs) + 1)
    for p in provs:
        if counts[idx_of[p["code"]]] < MIN_PIXELS:
            res.errors.append(f"Province {p['code']} ({p['color']}) wasn't found in the mask image.")
    if res.errors:
        return res
    labels = grow(raw_labels, GROW_PX)
    unassigned = float((labels == 0).mean())
    if unassigned > 0.5:
        res.warnings.append(f"{unassigned:.0%} of the mask isn't any province's color — is that intended (e.g. background)?")

    # ---- adjacency from shared edges
    edge = borders(labels)
    seas = {p["code"] for p in provs if p["type"] == "sea"}
    sea_ids = np.array([idx_of[c] for c in seas] or [-1])
    near_sea = cv2.dilate(np.isin(labels, sea_ids).astype(np.uint8), np.ones((2 * GROW_PX + 3,) * 2, np.uint8)) > 0
    R = GROW_PX + 2

    def seas_touching(pixels: np.ndarray) -> set:
        """Sea codes within R px of any of these edge pixels."""
        cand = pixels[near_sea[pixels[:, 0], pixels[:, 1]]]
        if len(cand) > 300:
            cand = cand[np.linspace(0, len(cand) - 1, 300).astype(int)]
        found = set()
        for y, x in cand:
            win = labels[max(0, y - R): y + R + 1, max(0, x - R): x + R + 1]
            for v in np.unique(win):
                if v > 0 and provs[v - 1]["code"] in seas:
                    found.add(provs[v - 1]["code"])
        return found

    neighbours: Dict[str, set] = {p["code"]: set() for p in provs}
    raw_edges = {}
    for (a, b), pix in edge.items():
        if len(pix) < MIN_BORDER:
            continue
        ca, cb = provs[a - 1]["code"], provs[b - 1]["code"]
        neighbours[ca].add(cb)
        neighbours[cb].add(ca)
        raw_edges[(ca, cb)] = pix

    # derive coast vs land
    for p in provs:
        if p["type"] == "sea":
            continue
        touches_sea = any(n in seas for n in neighbours[p["code"]])
        if p["type"] == "coast" and not touches_sea:
            res.warnings.append(f"{p['code']} is marked coast but touches no sea; fleets can't use it.")
        p["type"] = "coast" if touches_sea or p["type"] == "coast" else "land"
        if p["coasts"] and not touches_sea:
            res.errors.append(f"{p['code']} has split coasts but touches no sea.")

    # relations: key frozenset({x, y}) where x/y may be "ABC/NC"
    rel: Dict[Tuple[str, str], str] = {}

    def put(x: str, y: str, kind: str):
        rel[tuple(sorted((x, y)))] = kind

    coast_of_sea: Dict[str, Dict[str, str]] = {}  # province -> sea -> coast loc
    for p in provs:
        for c in p["coasts"]:
            for s in c["seas"]:
                if s not in seas:
                    res.errors.append(f"{p['code']} coast {c['name']}: {s} isn't a sea province.")
                elif s not in neighbours[p["code"]]:
                    res.warnings.append(f"{p['code']} coast {c['name']}: {s} doesn't border {p['code']} in the mask.")
                coast_of_sea.setdefault(p["code"], {})[s] = f"{p['code']}/{c['name']}"
    for code, mapping in coast_of_sea.items():
        for s in neighbours[code] & seas:
            if s not in mapping:
                res.warnings.append(f"{code} borders {s} but none of its coasts list it, so fleets can't move between them.")

    for (ca, cb), pix in raw_edges.items():
        ta, tb = by_code[ca]["type"], by_code[cb]["type"]
        if ta == "sea" and tb == "sea":
            put(ca, cb, "fleet")
        elif "sea" in (ta, tb):
            sea, land = (ca, cb) if ta == "sea" else (cb, ca)
            if land in coast_of_sea:
                loc = coast_of_sea[land].get(sea)
                if loc:
                    put(sea, loc, "fleet")
            else:
                put(sea, land, "fleet")
        elif ta == "coast" and tb == "coast":
            shared = seas_touching(pix) & neighbours[ca] & neighbours[cb]
            put(ca, cb, "army")
            if shared:
                la = {coast_of_sea[ca][s] for s in shared if s in coast_of_sea.get(ca, {})} if ca in coast_of_sea else {ca}
                lb = {coast_of_sea[cb][s] for s in shared if s in coast_of_sea.get(cb, {})} if cb in coast_of_sea else {cb}
                if ca not in coast_of_sea and cb not in coast_of_sea:
                    put(ca, cb, "both")
                else:
                    for x in la:
                        for y in lb:
                            put(x, y, "fleet")
        else:
            put(ca, cb, "army")

    # ---- overrides
    def valid_loc(loc: str) -> bool:
        base = loc.split("/")[0]
        if base not in by_code:
            return False
        if "/" in loc:
            return loc in {f"{base}/{c['name']}" for c in by_code[base]["coasts"]}
        return True

    for a, b in spec["adjacency"]["remove"]:
        if not (valid_loc(a) and valid_loc(b)):
            res.errors.append(f"adjacency.remove: unknown province in [{a}, {b}].")
            continue
        hit = [k for k in rel if {k[0].split("/")[0], k[1].split("/")[0]} == {a.split("/")[0], b.split("/")[0]}
               and (("/" not in a or a in k) and ("/" not in b or b in k))]
        if not hit:
            res.warnings.append(f"adjacency.remove: {a} and {b} weren't adjacent anyway.")
        for k in hit:
            del rel[k]
    for a, b, kind in spec["adjacency"]["add"]:
        if not (valid_loc(a) and valid_loc(b)):
            res.errors.append(f"adjacency.add: unknown province in [{a}, {b}].")
            continue
        if a.split("/")[0] == b.split("/")[0]:
            res.errors.append(f"adjacency.add: a province can't border itself ({a}, {b}).")
            continue
        for x in (a, b):
            if by_code[x.split("/")[0]]["coasts"] and "/" not in x and kind != "army":
                res.errors.append(f"adjacency.add: {x} has split coasts — say which coast, e.g. {x}/{by_code[x]['coasts'][0]['name']}.")
        ta, tb = by_code[a.split("/")[0]]["type"], by_code[b.split("/")[0]]["type"]
        if kind != "fleet" and "sea" in (ta, tb):
            kind = "fleet"
        if kind in ("fleet", "both") and "land" in (ta, tb):
            res.errors.append(f"adjacency.add: fleets can't reach landlocked {a if ta == 'land' else b}; use 'army'.")
            continue
        put(a, b, kind)

    # merge a both + fleet pair stored separately on coasts etc.
    if res.errors:
        return res

    # ---- powers, homes, units
    scs = [p["code"] for p in provs if p["sc"]]
    homes_owner: Dict[str, str] = {}
    occupied = set()
    for pw in spec["powers"]:
        if not pw["homes"]:
            res.errors.append(f"{pw['name']} needs at least one home supply center.")
        for hcode in pw["homes"]:
            if hcode not in by_code:
                res.errors.append(f"{pw['name']}: home {hcode} isn't a province.")
            elif not by_code[hcode]["sc"]:
                res.errors.append(f"{pw['name']}: home {hcode} must be a supply center (set \"sc\": true).")
            elif hcode in homes_owner:
                res.errors.append(f"{hcode} is a home center of both {homes_owner[hcode]} and {pw['name']}.")
            else:
                homes_owner[hcode] = pw["name"]
        if not pw["units"]:
            res.errors.append(f"{pw['name']} needs at least one starting unit.")
        for u in pw["units"]:
            m = re.match(r"^([AF]) ([A-Z]{3})(?:/([A-Z]{2}))?$", u)
            if not m:
                res.errors.append(f"{pw['name']}: unit '{u}' should look like 'A ABC', 'F ABC' or 'F ABC/NC'.")
                continue
            t, base, coast = m.groups()
            p = by_code.get(base)
            if not p:
                res.errors.append(f"{pw['name']}: unit {u} is in an unknown province.")
                continue
            if base in occupied:
                res.errors.append(f"Two starting units in {base}.")
            occupied.add(base)
            if p["impassable"]:
                res.errors.append(f"{pw['name']}: {base} is impassable.")
            if t == "A" and p["type"] == "sea":
                res.errors.append(f"{pw['name']}: an army can't start at sea ({u}).")
            if t == "F" and p["type"] == "land":
                res.errors.append(f"{pw['name']}: a fleet can't start in landlocked {base}.")
            if t == "F" and p["coasts"] and not coast:
                res.errors.append(f"{pw['name']}: say which coast the fleet in {base} is on, e.g. F {base}/{p['coasts'][0]['name']}.")
            if coast and coast not in {c["name"] for c in p["coasts"]}:
                res.errors.append(f"{pw['name']}: {base} has no coast {coast}.")
            if t == "A" and coast:
                res.errors.append(f"{pw['name']}: armies don't take a coast ({u}).")
    for p in provs:
        if p["sc"] and p["type"] == "sea":
            res.errors.append(f"{p['code']}: supply centers must be on land.")
        if p["sc"] and p["impassable"]:
            res.errors.append(f"{p['code']}: an impassable province can't be a supply center.")
    victory = spec["victory"] if spec["victory"] is not None else len(scs) // 2 + 1
    if not isinstance(victory, int) or not (1 <= victory <= len(scs)):
        res.errors.append(f"victory must be between 1 and the number of supply centers ({len(scs)}).")
        victory = len(scs) // 2 + 1
    for p in provs:
        if not p["impassable"] and not any(p["code"] in (k[0].split("/")[0], k[1].split("/")[0]) for k in rel):
            res.errors.append(f"{p['code']} has no neighbours — check the mask or add adjacencies.")
    if res.errors:
        return res

    # ---- engine .map text
    def entry(owner: str, x: str, kind: str) -> str:
        # DPjudge convention: UPPER = armies and fleets, lower = armies only, Title = fleets only.
        # Rows of seas / split coasts, and links to them, are always UPPER (armies can't be there anyway).
        if "/" in owner or "/" in x or by_code[owner.split("/")[0]]["type"] == "sea" or by_code[x.split("/")[0]]["type"] == "sea":
            return x.upper()
        if kind == "army":
            return x.lower()
        if kind == "fleet":
            return x[0].upper() + x[1:].lower()
        return x.upper()

    rows: Dict[str, List[str]] = {}
    for (x, y), kind in rel.items():
        rows.setdefault(x, []).append(entry(x, y, kind))
        rows.setdefault(y, []).append(entry(y, x, kind))
        for a, b in ((x, y), (y, x)):
            if "/" in a:
                base = a.split("/")[0]
                if by_code[b.split("/")[0]]["type"] == "sea":
                    rows.setdefault(base, []).append(b.upper())  # convoy routes start from the base province
                elif kind != "fleet":
                    rows.setdefault(base, []).append(entry(base, b, kind))

    lines = ["# Generated by Entente from an uploaded map. Do not edit by hand.", f"VICTORY {victory}"]
    if spec["build_anywhere"]:
        lines.append("RULE BUILD_ANY")
    lines += ["", f"BEGIN SPRING {spec['start_year']} MOVEMENT", ""]
    for pw in spec["powers"]:
        lines.append(f"{pw['name']} ({pw['adjective'].upper()}) {' '.join(pw['homes'])}")
        lines += pw["units"]
        lines.append("")
    neutrals = [c for c in scs if c not in homes_owner]
    lines.append(f"UNOWNED {' '.join(neutrals)}")
    lines.append("")
    for p in provs:
        lines.append(f"{p['name']} = {p['code'].lower()}")
        for c in p["coasts"]:
            lines.append(f"{p['name']} ({c['name']}) = {p['code'].lower()}/{c['name'].lower()}")
    lines.append("")
    for p in provs:
        kind = "SHUT" if p["impassable"] else {"sea": "WATER", "coast": "COAST", "land": "LAND"}[p["type"]]
        base_key = p["code"].lower() if p["coasts"] else p["code"]
        lines.append(f"{kind:<6} {base_key} ABUTS {' '.join(sorted(set(rows.get(p['code'], []))))}")
        for c in p["coasts"]:
            loc = f"{p['code']}/{c['name']}"
            lines.append(f"COAST  {loc} ABUTS {' '.join(sorted(set(rows.get(loc, []))))}")
    res.map_text = "\n".join(lines) + "\n"

    # ---- report adjacency list + geometry
    inner = {}
    for p in provs:
        mask = labels == idx_of[p["code"]]
        inner[p["code"]] = mask
    land_r = [interior_points(inner[p["code"]], 1, 1)[0][2] for p in provs if p["type"] != "sea"]
    med = float(np.median(land_r)) if land_r else 30.0
    scale = max(0.25, min(1.2, med / 48.0))
    unit_r = 27 * scale

    geo_provs, coasts_geo, labels_geo, decor = {}, {}, [], []
    for p in provs:
        mask = inner[p["code"]]
        ys, xs = np.nonzero(mask)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        sub = mask[y0:y1, x0:x1]
        d = contour_path(sub, int(x0), int(y0))
        pts = interior_points(sub, 3, unit_r * 2.0)
        ux, uy, _ = pts[0]
        unit = [round(ux + x0, 1), round(uy + y0, 1)]
        entry_g = {
            "name": p["name"], "type": p["type"], "sc": p["sc"], "d": d, "unit": unit,
            "disl": [round(unit[0] + unit_r * 0.75, 1), round(unit[1] - unit_r * 0.75, 1)],
        }
        if p["sc"]:
            sp = pts[1] if len(pts) > 1 else (ux + unit_r * 1.2, uy + unit_r * 0.6, 0)
            entry_g["scpos"] = [round(sp[0] + x0, 1), round(sp[1] + y0, 1)]
        lp = pts[2] if len(pts) > 2 else (pts[1] if len(pts) > 1 and not p["sc"] else (ux - unit_r, uy + unit_r * 1.6, 0))
        labels_geo.append({"t": p["code"], "x": round(lp[0] + x0 - 16 * scale, 1), "y": round(lp[1] + y0 + 6 * scale, 1),
                           "r": 0, "s": False, "w": p["type"] == "sea"})
        if p["impassable"]:
            decor.append({"kind": "impassable", "d": d, "id": p["code"]})
        else:
            geo_provs[p["code"]] = entry_g
        for c in p["coasts"]:
            sea_mask = np.isin(labels[y0:y1, x0:x1], [idx_of[s] for s in c["seas"] if s in idx_of])
            near = cv2.dilate(sea_mask.astype(np.uint8), np.ones((int(unit_r * 4) | 1,) * 2, np.uint8)) > 0
            cpts = interior_points(sub & near, 1, 1)
            cx, cy = (cpts[0][0], cpts[0][1]) if cpts else (ux, uy)
            cu = [round(cx + x0, 1), round(cy + y0, 1)]
            coasts_geo[f"{p['code']}/{c['name']}"] = {"unit": cu, "disl": [round(cu[0] + unit_r * 0.75, 1), round(cu[1] - unit_r * 0.75, 1)]}

    def centre(loc: str):
        if loc in coasts_geo:
            return coasts_geo[loc]["unit"]
        g = geo_provs.get(loc.split("/")[0])
        return g["unit"] if g else None

    for (x, y), kind in sorted(rel.items()):
        a, b = centre(x), centre(y)
        if a and b:
            res.adjacency.append({"a": x, "b": y, "type": kind})

    res.geometry = {
        "width": w, "height": h, "offset": [0, 0], "scale": round(scale, 3),
        "style": "image" if has_display else "flat",
        "provinces": geo_provs, "coasts": coasts_geo, "decor": decor, "labels": labels_geo,
        "powers": [{"name": pw["name"], "adjective": pw["adjective"], "color": pw["color"]} for pw in spec["powers"]],
    }
    res.stats = {
        "provinces": len(provs), "land": sum(p["type"] == "land" for p in provs),
        "coast": sum(p["type"] == "coast" for p in provs), "sea": len(seas), "supply_centers": len(scs),
        "neutral_centers": len(neutrals), "powers": len(spec["powers"]), "victory": victory,
        "adjacencies": len(rel), "width": w, "height": h,
    }
    return res


def engine_check(map_path: str, res: Result) -> None:
    """Load the generated map in the real adjudicator and play one turn of holds."""
    from diplomacy import Game
    from diplomacy.engine.map import Map

    try:
        m = Map(map_path)
        if m.error:
            res.errors += [f"Engine: {e}" for e in m.error]
            return
        g = Game(map_name=map_path, rules=["NO_DEADLINE", "ALWAYS_WAIT", "IGNORE_ERRORS"])
        po = g.get_all_possible_orders()
        for p in g.powers:
            locs = g.get_orderable_locations(p)
            if not locs or not any(po.get(l) for l in locs):
                res.errors.append(f"Engine: {p} has no legal orders at the start.")
        moves = sum(1 for l in po for o in po[l] if " - " in o)
        if moves == 0:
            res.errors.append("Engine: no unit can move anywhere — check adjacencies.")
        g.process()
        res.stats["engine_first_phase"] = g.get_current_phase()
    except Exception as exc:  # engine raises a variety of things on malformed maps
        res.errors.append(f"Engine couldn't load the map: {exc}")


def merge_spec_changes(spec: dict, changes: List[dict]) -> dict:
    """Apply accepted AI/editor changes to a raw spec dict (returns a new dict)."""
    spec = json.loads(json.dumps(spec))
    adj = spec.setdefault("adjacency", {})
    add, remove = adj.setdefault("add", []), adj.setdefault("remove", [])
    provs = {str(p.get("code", "")).upper(): p for p in spec.get("provinces", [])}
    for ch in changes:
        op = ch.get("op")
        a, b = str(ch.get("a", "")).upper(), str(ch.get("b", "")).upper()
        if op in ("add_adjacency", "set_adjacency"):
            add[:] = [x for x in add if {x[0].upper(), x[1].upper()} != {a, b}]
            remove[:] = [x for x in remove if {x[0].upper(), x[1].upper()} != {a, b}]
            if op == "add_adjacency" or ch.get("type") != "none":
                add.append([a, b, ch.get("type", "both")])
            else:
                remove.append([a, b])
        elif op == "remove_adjacency":
            add[:] = [x for x in add if {x[0].upper(), x[1].upper()} != {a, b}]
            if [a, b] not in remove:
                remove.append([a, b])
        elif op == "set_impassable" and ch.get("code", "").upper() in provs:
            provs[ch["code"].upper()]["impassable"] = bool(ch.get("value"))
        elif op == "set_supply_center" and ch.get("code", "").upper() in provs:
            provs[ch["code"].upper()]["sc"] = bool(ch.get("value"))
        elif op == "set_build_anywhere":
            spec["build_anywhere"] = bool(ch.get("value"))
        elif op == "set_victory" and isinstance(ch.get("value"), int):
            spec["victory"] = ch["value"]
    return spec
