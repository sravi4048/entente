"""Build render geometry for the built-in variants from the engine's bundled SVGs.

Writes backend/app/maps/<slug>.json for: classic, ancmed, modern.

Usage:  python scripts/build_builtin_maps.py
"""
import json
import os
import re
import xml.etree.ElementTree as ET

import diplomacy
from diplomacy.engine.map import Map

SVG_DIR = os.path.join(os.path.dirname(diplomacy.__file__), "maps", "svg")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "maps")
J = "{svg.dtd}"
UNIT_BOX = 40  # jDip unit symbol box; coordinates are its top-left corner

VARIANTS = {
    "classic": {
        "map": "standard",
        "name": "Classic",
        "description": "The original 1901 Europe. Seven Great Powers, 34 supply centers, 18 to win.",
        "colors": {
            "AUSTRIA": "#c8453c", "ENGLAND": "#33509f", "FRANCE": "#4b9be0", "GERMANY": "#5e544a",
            "ITALY": "#3f9a55", "RUSSIA": "#8b5dc4", "TURKEY": "#dfae35",
        },
    },
    "ancmed": {
        "map": "ancmed",
        "name": "Ancient Mediterranean",
        "description": "Five empires around the Mediterranean, 34 supply centers. Tight, aggressive, great for smaller groups.",
        "colors": {
            "CARTHAGE": "#3f9a55", "EGYPT": "#dfae35", "GREECE": "#4b9be0", "PERSIA": "#8b5dc4", "ROME": "#c8453c",
        },
    },
    "modern": {
        "map": "modern",
        "name": "Modern",
        "land_rects": True,
        # Gaps between sea polygons that the source SVG leaves unfilled (no rect behind them).
        "islands": ["M147 370 L154 366 L156 370 L150 371 Z"],  # Mallorca, between GOL and WME
        "description": "Ten powers on a modern Europe and Middle East, 64 supply centers. Builds allowed in any owned center.",
        "colors": {
            "BRITAIN": "#33509f", "EGYPT": "#b8862b", "FRANCE": "#4b9be0", "GERMANY": "#5e544a", "ITALY": "#3f9a55",
            "POLAND": "#d0607a", "RUSSIA": "#8b5dc4", "SPAIN": "#e07b39", "TURKEY": "#dfc235", "UKRAINE": "#2fa3a0",
        },
    },
}


def parse_translate(tf):
    m = re.search(r"translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)", tf or "")
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def shape_d(el, rects=False):
    tag = el.tag.split("}")[-1]
    if tag == "path" and el.get("d"):
        return " ".join(el.get("d").split())
    if tag in ("polygon", "polyline") and el.get("points"):
        nums = re.findall(r"[-\d.]+", el.get("points"))
        pts = [f"{nums[i]} {nums[i + 1]}" for i in range(0, len(nums) - 1, 2)]
        return "M" + " L".join(pts) + " Z"
    if rects and tag == "rect" and el.get("width") and el.get("height"):
        # Modern draws a land-colored rect behind the central Med; the gaps between sea
        # polygons there (Sardinia, Sicily, ...) are meant to show it.
        x, y = float(el.get("x", 0)), float(el.get("y", 0))
        w, h = float(el.get("width")), float(el.get("height"))
        return f"M{x:g} {y:g} L{x + w:g} {y:g} L{x + w:g} {y + h:g} L{x:g} {y + h:g} Z"
    return None


def build(slug, cfg):
    m = Map(cfg["map"])
    root = ET.parse(os.path.join(SVG_DIR, cfg["map"] + ".svg")).getroot()
    vb = [float(x) for x in root.get("viewBox").split()]
    width, height = vb[2], vb[3]
    layers = {e.get("id"): e for e in root if e.get("id")}
    box = UNIT_BOX
    for sz in root.iter(f"{J}SYMBOLSIZE"):
        if sz.get("name") == "Army":
            box = float(sz.get("width"))
    locs = {l.upper() for l in m.locs}
    aliases = getattr(m, "aliases", {})
    names = {abbr.upper(): name.title() for name, abbr in m.loc_name.items()}

    def code(raw):
        p = raw.lstrip("_").upper().replace("-", "/")
        return p if p in locs else aliases.get(p, p).upper()

    ml = layers["MapLayer"]
    offset = parse_translate(ml.get("transform"))
    provinces, decor = {}, []
    for path in ml:
        raw, cls = path.get("id"), path.get("class")
        if path.tag.endswith("}g"):
            # A province drawn as several shapes. For a land province the class="water"
            # pieces are canals/lakes drawn on top; for a sea province they ARE the sea and
            # the unclassed pieces are islands inside it (e.g. Corsica in the Ligurian Sea).
            parts = [c for c in path if shape_d(c)]
            is_sea = bool(raw and raw.startswith("_")) and m.area_type(code(raw)) == "WATER"
            body = [c for c in parts if (c.get("class") == "water") == is_sea]
            extra = [c for c in parts if (c.get("class") == "water") != is_sea]
            d = " ".join(shape_d(c) for c in body)
            for c in extra:
                decor.append({"kind": "land_top" if is_sea else "water_top", "d": shape_d(c)})
        else:
            d = shape_d(path, rects=cfg.get("land_rects", False))
        if not d:
            continue
        if not raw or not raw.startswith("_"):
            decor.append({"kind": "water" if cls == "water" else "land", "d": d})
            continue
        p = code(raw)
        kind = m.area_type(p)
        if kind == "SHUT":
            decor.append({"kind": "impassable", "d": d, "id": p})
            continue
        provinces[p] = {"name": names.get(p, p), "type": kind.lower(), "sc": p in m.scs, "d": d}

    for d in cfg.get("islands", []):
        decor.append({"kind": "land", "d": d})

    coasts = {}
    for prov in root.find(f"{J}PROVINCE_DATA").findall(f"{J}PROVINCE"):
        p = code(prov.get("name"))
        entry = {}
        for tag, key in (("UNIT", "unit"), ("DISLODGED_UNIT", "disl")):
            el = prov.find(f"{J}{tag}")
            if el is not None:
                entry[key] = [round(float(el.get("x")) + box / 2, 1), round(float(el.get("y")) + box / 2, 1)]
        if "/" in p:
            coasts[p] = entry
        elif p in provinces:
            provinces[p].update(entry)

    for use in layers.get("SupplyCenterLayer", []):
        sid = (use.get("id") or "").replace("sc_", "")
        p = code(sid) if sid else None
        if p in provinces:
            w = float(use.get("width") or 20)
            provinces[p]["scpos"] = [round(float(use.get("x")) + w / 2, 1), round(float(use.get("y")) + w / 2, 1)]

    scale = round(box / UNIT_BOX, 3)
    labels = []
    for t in layers.get("BriefLabelLayer", []):
        if not t.tag.endswith("text"):
            continue
        text = (t.text or "").strip()
        x, y = float(t.get("x", 0)), float(t.get("y", 0))
        tx, ty = parse_translate(t.get("transform"))
        r = re.search(r"rotate\(([-\d.]+)", t.get("transform") or "")
        p = code(text) if text else ""
        labels.append({
            "t": p if p in provinces else text.upper(),
            "x": x + tx, "y": y + ty, "r": float(r.group(1)) if r else 0.0,
            "s": t.get("class") == "labeltext18",
            "w": p in provinces and provinces[p]["type"] == "water",
        })
    if not labels:  # e.g. Pure ships without labels
        for p, v in provinces.items():
            labels.append({"t": p, "x": v["unit"][0] - 22 * scale, "y": v["unit"][1] + 52 * scale, "r": 0, "s": False, "w": False})

    for p, v in provinces.items():
        v.setdefault("disl", [v["unit"][0] + 12 * scale, v["unit"][1] - 12 * scale])
    missing = [p for p, v in provinces.items() if "unit" not in v]
    assert not missing, (slug, missing)

    return {
        "slug": slug,
        "width": width,
        "height": height,
        "offset": list(offset),
        "scale": scale,
        "style": "flat",
        "provinces": provinces,
        "coasts": coasts,
        "decor": decor,
        "labels": labels,
        "powers": [{"name": p, "adjective": m.own_word.get(p, p).title(), "color": cfg["colors"][p]} for p in sorted(m.powers)],
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    meta = {}
    for slug, cfg in VARIANTS.items():
        geo = build(slug, cfg)
        with open(os.path.join(OUT_DIR, f"{slug}.json"), "w") as f:
            json.dump(geo, f, separators=(",", ":"))
        meta[slug] = {"map": cfg["map"], "name": cfg["name"], "description": cfg["description"]}
        print(f"{slug}: {len(geo['provinces'])} provinces, {len(geo['coasts'])} coasts, scale {geo['scale']}")
    with open(os.path.join(OUT_DIR, "builtin.json"), "w") as f:
        json.dump(meta, f, indent=2)


if __name__ == "__main__":
    main()
