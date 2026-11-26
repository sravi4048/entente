# Entente — Diplomacy with friends

A self-hosted, real-time Diplomacy site in the spirit of Backstabbr: a big clickable map, a sidebar for orders, private press, players and history, and a lobby where you add friends and invite them to games.

- **Real rules.** Orders are adjudicated by the open-source [`diplomacy`](https://github.com/diplomacy/diplomacy) engine, which passes the DATC test suite. It handles convoys, coasts, retreats, builds and civil disorder.
- **Click-to-order map.** Tap a unit and the legal destinations light up. Tap one to move, or tap the unit again to hold. Support and Convoy are one button away. When a fleet could land on either coast, you get asked which one.
- **Friends and invites.** Add friends by username and invite them from the game room, or share a link that anyone can use to join.
- **Press.** A global channel plus a private channel with each power. You can choose full press, public-only or gunboat. All press is revealed when the game ends.
- **Deadlines.** Phases last from 10 minutes to 72 hours, or have no clock. A phase resolves as soon as everyone marks ready. Players who miss a deadline hold, and the engine handles disbands.
- **Live updates** over WebSockets: new phases, messages and ready status appear without a refresh.
- **History** lets you step through every past phase and see each order on the map, with failed orders marked.
- **Draws** happen when every surviving player votes for one. A solo win takes 18 centers.
- Games work with 1–7 players. Any power nobody takes sits in civil disorder and always holds.
- **Two panes: Classic and Variants.** Variants ships with Ancient Mediterranean (5 players) and Modern (10).
- **Custom maps.** Anyone signed in can upload a map: an SVG, or a picture plus a province mask, along with a short spec file. The site works out adjacencies, unit positions and the engine map, checks everything, then shows a preview with every border drawn. You approve maps before they go live. See [MAP_SPEC.md](MAP_SPEC.md).
- **AI rule interpreter (optional).** A map's plain-English special rules ("a canal lets fleets sail between X and Y") are turned into proposed adjacency changes at review time, for you to accept or reject. Nothing AI-driven happens during play.
- **Loose sign-up gate.** Set `SIGNUP_CODE`, and new accounts must enter that code.

## Stack

| Layer | What |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, `diplomacy` 1.2 (adjudicator) |
| Database | SQLite by default; Postgres via `DATABASE_URL` |
| Realtime | Native WebSockets, in-process fan-out |
| Frontend | React 19 + TypeScript + Vite, hand-drawn SVG map (no UI framework) |
| Deploy | One Docker image that serves the API, the websocket and the built SPA |

```
backend/
  app/main.py       FastAPI app, /ws endpoint, deadline scheduler, serves the SPA
  app/api.py        REST routes: auth, friends, games, orders, ready, draw, press, history
  app/service.py    game lifecycle: start, adjudicate, deadlines, draws, press visibility
  app/engine.py     the only module that touches the rules engine
  app/db.py         SQLAlchemy models (incl. uploaded Variant maps)
  app/mapbuild.py   uploaded map → engine .map + render geometry + validation report
  app/variants/     registry (built-in + uploaded), SVG→mask, AI rule interpreter
  app/variants_api.py  upload / review / AI / map-file endpoints
  app/maps/         render data for the built-in variants
  app/examples/     the "Toy Islands" example map (served as upload templates)
  scripts/build_builtin_maps.py  regenerates app/maps/ from the engine's SVGs
  scripts/make_example_map.py    regenerates app/examples/toy-islands/
  tests/            end-to-end API tests: a full game, uploads, review, variants
frontend/src/
  components/MapView.tsx   SVG map for any variant: territories, units, order arrows, adjacency overlay, pan/zoom/pinch
  pages/GamePage.tsx       order-entry state machine + sidebar tabs
  pages/Lobby.tsx          Classic / Variants / Review panes, friends, create game
  pages/MapPages.tsx       map upload + preview, map detail/review, map-making guide
```

## Run it locally

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev            # http://localhost:5173 (proxies /api and /ws to :8000)
```

To try the production setup, run `npm run build` in `frontend/`. FastAPI then serves `frontend/dist` at http://localhost:8000.

Tests: `cd backend && pytest -q`

## Deploy

**Important: run exactly one instance (one uvicorn worker).** WebSocket fan-out and the deadline scheduler run in-process. If the host sleeps idle apps, deadlines stall until the next request wakes it, so keep at least one machine always on.

### Fly.io (SQLite on a volume — cheapest)
```bash
fly launch --no-deploy --copy-config   # pick a unique app name
fly volumes create entente_data --size 1
fly secrets set SIGNUP_CODE=pick-a-phrase ADMIN_USERNAMES=yourusername
fly secrets set ANTHROPIC_API_KEY=sk-ant-...   # optional: AI rule interpreter
fly deploy
```
Register with the username you put in `ADMIN_USERNAMES`; that account gets the Review queue. If you leave `ADMIN_USERNAMES` unset, the first account created becomes the admin.

### Render (Docker + managed Postgres)
Push this repo to GitHub, then in Render choose **New → Blueprint** and select the repo. `render.yaml` creates the web service and the database. Use a paid instance, because free ones sleep.

### Any VPS with Docker
```bash
docker compose up -d --build      # app + Postgres on :8000
```
Put HTTPS in front of it with Caddy or Cloudflare Tunnel, then set `COOKIE_SECURE=1`.

### Environment variables

| Var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | SQLite in `$DATA_DIR` | `postgres://…` URLs are accepted as-is |
| `DATA_DIR` | `backend/data` (`/data` in Docker) | Where the SQLite file lives |
| `COOKIE_SECURE` | `0` | **Set to `1` behind HTTPS** |
| `SESSION_DAYS` | `30` | Login lifetime |
| `SCHEDULER_INTERVAL_SECONDS` | `15` | How often deadlines are checked |
| `SOURCE_URL` | empty | Shown in the footer (see License) |
| `SIGNUP_CODE` | empty | If set, new accounts must enter it (case-insensitive). Comma-separate several codes to accept any of them |
| `ADMIN_USERNAMES` | empty | Comma-separated admins who approve maps. Empty = the first account |
| `ANTHROPIC_API_KEY` | empty | Turns on the AI rule interpreter at review time |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Model the interpreter uses |
| `MAX_UPLOAD_MB` | `12` | Per-file upload limit |

Tables are created automatically on startup. For future schema changes, add Alembic.

### Backups

```bash
scripts/backup.sh            # -> backups/entente-<UTC timestamp>.db (gitignored)
```

Takes a consistent snapshot with SQLite's online backup API on the Fly machine (safe while games are running), downloads it, removes the server-side temp file and runs an integrity check. Restore steps are in the script's header. Fly also keeps daily volume snapshots for 5 days.

## How order entry works

1. Tap a unit. Its legal moves are highlighted, and an action bar shows **Move / Hold / Support / Convoy**.
2. **Move:** tap a highlighted territory. **Hold:** tap the unit again or press **H**.
3. **Support:** tap Support (or press S), then the unit you're helping, then its destination. Tap the helped unit itself to support its hold.
4. **Convoy:** tap Convoy (or press C), then the army, then the destination. Then order the army to move there. It's flagged "by convoy" automatically.
5. **Retreats:** tap a dislodged unit, then a highlighted territory, or tap Disband.
6. **Builds:** tap a highlighted home center and pick Army or Fleet (and a coast if needed). Use "Waive a build" to skip one. **Disbands:** tap the units to remove.

Orders save as you go and stay private until the phase resolves. The legal options come from the engine itself (`possible_orders`), and the server checks every order again before saving it.

## Known gaps / next steps

- No email or push notifications yet. A small mailer called from `service.process_if_ready` would be the natural hook.
- No password reset. There's also no rate limiting on login, so put the app behind Cloudflare or add `slowapi` if it's public.
- Uploaded maps support the standard rules plus "build anywhere". Fancier variants (neutral armies, special unit types, timed events) can't be enforced by the engine. The AI interpreter flags them as honor-system rules.
- Running more than one instance would need Redis pub/sub in `hub.py` and a DB-level lock or job queue for the scheduler.

## License

The rules engine (`diplomacy`) is **AGPL-3.0**, and the map geometry comes from jDip's GPL SVG, so treat this project as **AGPL-3.0**. For a private site for your friends, that changes nothing. If you run it publicly, you must offer users the source of the version you run. Put your repo URL in `SOURCE_URL` and it shows in the footer.

"Diplomacy" is a trademark of Hasbro. This project isn't affiliated with Hasbro or Backstabbr.
