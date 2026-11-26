"""Draw the 'Toy Islands' example map in all three upload formats.

    python scripts/make_example_map.py          # writes app/examples/toy-islands/

Writes map.png (display art), mask.png (flat province colors), map.svg
(shapes with province ids) and spec.yaml. Doubles as a test fixture.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 900, 600

# code: (name, type, polygon, mask color, art color)
PROVINCES = {
    "WES": ("West Sea", "sea", [(0, 0), (150, 0), (150, 600), (0, 600)], "#1f4e9a", "#9cc3dc"),
    "NOR": ("Northern Sea", "sea", [(150, 0), (900, 0), (900, 120), (150, 120)], "#2a6fd6", "#9cc3dc"),
    "SOU": ("Southern Bay", "sea", [(450, 600), (450, 480), (650, 430), (800, 480), (800, 600)], "#34a0e0", "#9cc3dc"),
    "AAA": ("Avalon", "land", [(150, 120), (400, 120), (380, 300), (150, 320)], "#c0392b", "#efe3c8"),
    "BBB": ("Bastion", "land", [(400, 120), (650, 120), (620, 280), (380, 300)], "#8e44ad", "#efe3c8"),
    "CCC": ("Corsa", "land", [(650, 120), (900, 120), (900, 330), (620, 280)], "#27ae60", "#efe3c8"),
    "MTN": ("High Peaks", "land", [(380, 300), (620, 280), (600, 380), (420, 400)], "#7f8c8d", "#b9b2a0"),
    "DDD": ("Dunmore", "land", [(150, 320), (380, 300), (420, 400), (450, 480), (450, 600), (150, 600)], "#d35400", "#efe3c8"),
    "FFF": ("Fenwick", "land", [(420, 400), (600, 380), (650, 430), (450, 480)], "#f1c40f", "#efe3c8"),
    "EEE": ("Eastmarch", "land", [(620, 280), (900, 330), (900, 600), (800, 600), (800, 480), (650, 430), (600, 380)], "#16a085", "#efe3c8"),
}

SPEC = """\
# Toy Islands — a tiny example map for Entente.
# Upload this file with map.png + mask.png (or with map.svg alone).
name: Toy Islands
description: Three kingdoms, three neutral centers and a mountain range nobody can cross.
start_year: 1901
victory: 4                 # supply centers needed to win (default: more than half)
build_anywhere: false      # true = build in any owned center, not just home centers
color_tolerance: 10        # how far a mask pixel may drift from the listed color (0-40)

powers:
  - name: SCARLET
    adjective: Scarlet
    color: "#c8453c"
    homes: [AAA]
    units: ["F AAA"]
  - name: AZURE
    adjective: Azure
    color: "#33509f"
    homes: [BBB]
    units: ["A BBB"]
  - name: VERDANT
    adjective: Verdant
    color: "#3f9a55"
    homes: [CCC]
    units: ["F CCC"]

provinces:
  # code: exactly 3 letters. color: the province's flat color in mask.png (ignored for SVG uploads).
  - {code: WES, name: West Sea,     type: sea,  color: "#1f4e9a"}
  - {code: NOR, name: Northern Sea, type: sea,  color: "#2a6fd6"}
  - {code: SOU, name: Southern Bay, type: sea,  color: "#34a0e0"}
  - {code: AAA, name: Avalon,       type: land, color: "#c0392b", sc: true}
  - {code: BBB, name: Bastion,      type: land, color: "#8e44ad", sc: true}
  - {code: CCC, name: Corsa,        type: land, color: "#27ae60", sc: true}
  - {code: EEE, name: Eastmarch,    type: land, color: "#16a085", sc: true}
  - {code: FFF, name: Fenwick,      type: land, color: "#f1c40f", sc: true}
  - {code: MTN, name: High Peaks,   type: land, color: "#7f8c8d", impassable: true}
  - code: DDD
    name: Dunmore
    type: land
    color: "#d35400"
    sc: true
    coasts:                # split coasts: fleets must say which side they're on
      - {name: WC, seas: [WES]}
      - {name: SC, seas: [SOU]}

# Adjacencies are worked out from the mask. Use these lists to fix exceptions.
adjacency:
  add: []                  # e.g. ["AAA", "CCC", "fleet"]  (types: both | army | fleet)
  remove: []               # e.g. ["AAA", "BBB"]

rules: |
  Optional plain-text rules. The reviewer can have an AI turn them into
  adjacency changes, e.g. "A canal lets fleets sail between Avalon and Corsa."
"""


def draw(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    art = Image.new("RGB", (W, H), "#9cc3dc")
    mask = Image.new("RGB", (W, H), "#000000")
    da, dm = ImageDraw.Draw(art), ImageDraw.Draw(mask)
    for code, (name, kind, poly, mcol, acol) in PROVINCES.items():
        da.polygon(poly, fill=acol)
        dm.polygon(poly, fill=mcol)
    for code, (name, kind, poly, mcol, acol) in PROVINCES.items():
        da.line(poly + [poly[0]], fill="#5b5040", width=3)
        dm.line(poly + [poly[0]], fill="#000000", width=3)  # borders: unassigned pixels, like hand-drawn masks
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:
        font = ImageFont.load_default()
    for code, (name, kind, poly, *_rest) in PROVINCES.items():
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        da.text((cx, cy + 26), name, fill="#2f5e7b" if kind == "sea" else "#3a3326", font=font, anchor="mm")
    art.save(os.path.join(out_dir, "map.png"))
    mask.save(os.path.join(out_dir, "mask.png"))

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             '<rect width="100%" height="100%" fill="#9cc3dc"/>']
    for code, (name, kind, poly, mcol, acol) in PROVINCES.items():
        pts = " ".join(f"{x},{y}" for x, y in poly)
        parts.append(f'<polygon id="{code}" points="{pts}" fill="{acol}" stroke="#5b5040" stroke-width="3"><title>{name}</title></polygon>')
    parts.append("</svg>")
    with open(os.path.join(out_dir, "map.svg"), "w") as f:
        f.write("\n".join(parts) + "\n")
    with open(os.path.join(out_dir, "spec.yaml"), "w") as f:
        f.write(SPEC)
    print(f"wrote example map to {out_dir}")


if __name__ == "__main__":
    draw(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "app", "examples", "toy-islands"))
