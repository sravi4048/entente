# Entente — notes for Claude Code

Self-hosted Diplomacy site for a friend group (Backstabbr-style UI), deployed on Fly.io.
Owner: Shravan (admin account; approves uploaded maps).

## Layout
- `backend/` — FastAPI + SQLAlchemy 2 + the `diplomacy` adjudicator (AGPL). Python 3.12.
  - `app/engine.py` — the ONLY module that talks to the rules engine.
  - `app/service.py` — game lifecycle (start, adjudicate, deadlines, draws, press visibility).
  - `app/api.py` — auth, friends, games, orders, press. `app/variants_api.py` — map upload/review/AI.
  - `app/mapbuild.py` — uploaded map (mask PNG + spec) → engine `.map` text + render geometry + report.
  - `app/variants/` — `registry.py` (built-in + uploaded variants), `mapgeom.py` (SVG → mask), `ai_rules.py`.
  - `app/maps/` — render JSON for built-in variants (classic, ancmed, modern). Regenerate with `scripts/build_builtin_maps.py`.
  - `app/examples/toy-islands/` — example upload (regenerate with `scripts/make_example_map.py`).
- `frontend/` — React 19 + TS + Vite, no UI framework, hand-rolled CSS in `src/styles.css`.
  - `src/orders.ts` — `MapModel` (per-variant geometry helpers), power colors, order parsing.
  - `src/components/MapView.tsx` — renders any variant; `src/pages/GamePage.tsx` — click-to-order state machine.
  - `src/pages/Lobby.tsx` (Classic / Variants / Review panes), `src/pages/MapPages.tsx` (upload, review, guide).

## Commands
```bash
cd backend && pip install -r requirements-dev.txt && pytest -q          # 11 end-to-end API tests
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev                               # :5173, proxies /api and /ws
cd frontend && npx tsc -b && npm run build                              # FastAPI serves frontend/dist
fly deploy                                                              # see README for secrets
```
Always run `pytest -q` and `npx tsc -b` before deploying.

## Design decisions to keep
- **Single instance only.** WebSocket fan-out (`hub.py`) and the deadline scheduler run in-process. Fly machine must stay always-on (`auto_stop_machines = "off"`).
- **No AI during play.** `ai_rules.py` only proposes map changes at review time; a human applies them. Adjudication stays deterministic.
- **Games snapshot custom maps** (`games.map_text`, `games.geometry_json`) at start, so editing/unpublishing a variant never breaks a running game. Generated `.map` files are content-addressed under `DATA_DIR/maps/`.
- Orders are private until the phase resolves; press is revealed to everyone when a game ends.
- Auth is deliberately light: username/password + optional `SIGNUP_CODE`. Admin = `ADMIN_USERNAMES` or the first account.
- Schema changes: there's no Alembic yet; `db._add_missing_columns()` does tiny forward-only ALTERs. Add new columns there.

## Engine gotchas
- Province codes must be exactly 3 letters (engine slices `[:3]`). Power names must NOT be 1 or 3 letters.
- `.map` adjacency case: `UPPER` = armies+fleets, `lower` = armies only, `Title` = fleets only. Split-coast parent rows use a lowercase code (`COAST spa ABUTS …`).
- `game.victory[0]` is the solo threshold (defaults to >50% of centers).
- Built-in variant geometry uses the jDip SVG coordinate space; `scale` in render JSON sizes tokens (1.0 = classic).

## User context
- Shravan is a software engineer (Go/Postgres background); fine with technical detail, prefers concise updates.
- Next likely work: deploy to Fly, gather friends' feedback, iterate (notifications, password reset, UX polish).
