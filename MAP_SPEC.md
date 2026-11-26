# Entente map specification

A custom map is **a picture + a spec file**. The site derives adjacencies, unit positions and the engine map from them, validates everything, and shows a preview with every border drawn. An admin approves maps before they appear in the Variants pane. Authors can playtest their own map while it's waiting for review.

The example map *Toy Islands* lives in [`backend/app/examples/toy-islands/`](backend/app/examples/toy-islands/) and can be downloaded from the upload page.

## 1. The picture (pick one)

| Route | Upload | Notes |
|---|---|---|
| **SVG** | `map.svg` | Every province shape gets `id="ABC"` (its code). Paths, polygons and rects all work, and groups and transforms are fine. Other shapes are kept as decoration. No mask needed. |
| **PNG/JPEG + mask** | `map.png` + `mask.png` | The picture is shown as-is. The mask is a same-shaped PNG with every province painted one flat color (the `color` in the spec). Thin borders between provinces are fine. Always save the mask as PNG. |
| **Mask only** | `mask.png` | The site draws a plain map from the mask. |

Images are limited to 200–4096 px per side and 12 MB.

## 2. The spec (YAML or JSON)

```yaml
name: Toy Islands
description: Three kingdoms, three neutral centers and a mountain range nobody can cross.
start_year: 1901          # default 1901
victory: 4                # centers needed to win; default = more than half
build_anywhere: false     # true = build in any owned center
color_tolerance: 10       # PNG masks: allowed color drift (0–40)

powers:
  - name: SCARLET         # one word, 2–16 letters, NOT exactly 3 letters
    adjective: Scarlet
    color: "#c8453c"
    homes: [AAA]          # home supply centers
    units: ["F AAA"]      # A = army, F = fleet; fleets on split coasts: "F DDD/WC"

provinces:
  - {code: WES, name: West Sea, type: sea, color: "#1f4e9a"}
  - {code: AAA, name: Avalon,   type: land, color: "#c0392b", sc: true}
  - {code: MTN, name: High Peaks, type: land, color: "#7f8c8d", impassable: true}
  - code: DDD
    name: Dunmore
    type: land
    color: "#d35400"
    sc: true
    coasts:               # only for provinces with two separate coastlines
      - {name: WC, seas: [WES]}
      - {name: SC, seas: [SOU]}

adjacency:
  add:    [["AAA", "CCC", "fleet"]]   # both | army | fleet
  remove: [["AAA", "BBB"]]

rules: |
  Plain-English special rules (optional).
```

### Field reference

- **Province `code`**: exactly 3 letters, unique, and not `VIA`/`ALL`/`UNO`.
- **`type`**: `land` or `sea`. Land provinces touching a sea are marked as coasts automatically.
- **`sc`**: supply center. Every supply center that isn't a power's home is neutral.
- **`impassable`**: no unit may ever enter.
- **`coasts`**: 2-letter names (NC, SC, EC, WC…), each listing the seas it touches. Fleets in that province must name a coast.
- **Powers**: each needs at least one home center and one starting unit. Armies can't start at sea, and fleets can't start in landlocked provinces.

## 3. How adjacency is derived

1. Two provinces border each other if their areas touch along an edge. Borders a few pixels wide are fine; a single corner doesn't count.
2. Sea–sea and sea–coast borders carry **fleets**. Land borders carry **armies**.
3. Two coastal provinces also carry **fleets** when their shared border reaches the sea.
4. Split-coast provinces connect fleets through the coast that lists the sea in question.
5. `adjacency.remove` is applied, then `adjacency.add`. Canals, straits, bridges and tunnels go in `add`.

Check the adjacency lines in the preview before submitting.

## 4. Special rules and the AI interpreter

If the server has `ANTHROPIC_API_KEY` set, the map's `rules` text is read once, at review time. It's translated into proposed changes using the same operations as above (connect/disconnect, impassable, supply center, build anywhere, victory). The reviewer ticks the proposals they agree with, the map is rebuilt and re-checked, and only then approved.

Rules that can't be expressed as map data are listed separately so players can follow them on the honor system: extra unit strength, neutral armies, timed events, turn order and the like. The AI never rules on anything during play.

## 5. What the checks catch

- Unknown or duplicate codes, names and colors, and colors too similar to tell apart.
- Provinces missing from the picture, or with no neighbors.
- Home centers that aren't supply centers or are shared, and units on illegal terrain.
- A victory count above the number of supply centers.
- Split coasts touching seas they don't border.
- Anything the real adjudicator rejects. Every map is loaded by the engine, and a test turn is played before it can be submitted.
