"""SVG uploads: paint each province shape (matched by element id = province code)
in its mask color, producing the same province-mask PNG a PNG upload provides.
Everything downstream (adjacency, positions, engine map) then runs through
`app.mapbuild` unchanged.
"""
from __future__ import annotations

import io
import math
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image, ImageDraw

MAX_RASTER = 2000  # longest side of the generated mask


def norm_code(raw: str) -> str:
    return (raw or "").strip().lstrip("_").upper()


def _points(path, step: float) -> List[List[Tuple[float, float]]]:
    from svgelements import Path

    out = []
    for sub in path.as_subpaths():
        sp = Path(sub)
        try:
            length = sp.length(error=1e-3) or 0
        except Exception:
            length = 0
        if not length:
            continue
        n = max(8, min(6000, int(length / step)))
        arr = np.asarray(sp.npoint(np.linspace(0, 1, n)), dtype=float).reshape(-1, 2)
        pts = [(float(x), float(y)) for x, y in arr if np.isfinite(x) and np.isfinite(y)]
        if len(pts) >= 3:
            out.append(pts)
    return out


def svg_to_mask(data: bytes, colors: Dict[str, str]) -> Tuple[bytes, Tuple[int, int], List[str], List[str]]:
    """Returns (mask_png, (width, height), codes_found, warnings)."""
    from svgelements import SVG, Path, Shape

    try:
        svg = SVG.parse(io.BytesIO(data), reify=True)
    except Exception as exc:
        raise ValueError(f"Couldn't read the SVG: {exc}")
    width = float(svg.width or 0) or 1000.0
    height = float(svg.height or 0) or 1000.0
    scale = MAX_RASTER / max(width, height)
    W, H = int(math.ceil(width * scale)), int(math.ceil(height * scale))
    if min(W, H) < 200:
        raise ValueError("The SVG is too narrow — make both sides at least 1/10 of the longest side.")

    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    found, warnings = set(), []
    for el in svg.elements():
        if not isinstance(el, Shape):
            continue
        code = norm_code(el.id or "")
        if code not in colors:
            continue
        c = colors[code].lstrip("#")
        rgb = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
        for pts in _points(Path(el), step=1.0 / scale):
            draw.polygon([(x * scale, y * scale) for x, y in pts], fill=rgb)
        found.add(code)
    missing = sorted(set(colors) - found)
    if missing:
        warnings.append(f"No SVG shape has the id of: {', '.join(missing[:20])}{'…' if len(missing) > 20 else ''}.")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), (W, H), sorted(found), warnings


AUTO_COLORS_SEED = 7


def auto_colors(codes: List[str]) -> Dict[str, str]:
    """Distinct, non-black mask colors for SVG uploads that don't specify any."""
    rng = np.random.default_rng(AUTO_COLORS_SEED)
    used: List[Tuple[int, int, int]] = []
    out = {}
    for code in codes:
        for _ in range(5000):
            rgb = tuple(int(v) for v in rng.integers(40, 256, size=3))
            if all(max(abs(rgb[i] - u[i]) for i in range(3)) > 26 for u in used):
                break
        used.append(rgb)
        out[code] = "#%02x%02x%02x" % rgb
    return out
