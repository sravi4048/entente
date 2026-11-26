import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import service
from .api import router
from .variants_api import router as variants_router
from .auth import COOKIE_NAME, user_from_token
from .config import SCHEDULER_INTERVAL_SECONDS, STATIC_DIR
from .db import SessionLocal, init_db
from .hub import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("entente")


async def deadline_loop() -> None:
    while True:
        try:
            for gid in await run_in_threadpool(service.due_game_ids):
                log.info("deadline reached for game %s", gid)
                await run_in_threadpool(service.process_if_ready, gid, True)
        except Exception:
            log.exception("deadline loop error")
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    hub.bind(asyncio.get_running_loop())
    task = asyncio.create_task(deadline_loop())
    yield
    task.cancel()


app = FastAPI(title="Entente", lifespan=lifespan)
app.include_router(router)
app.include_router(variants_router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    token = ws.cookies.get(COOKIE_NAME)

    def lookup():
        db = SessionLocal()
        try:
            u = user_from_token(db, token)
            return u.id if u else None
        finally:
            db.close()

    uid = await run_in_threadpool(lookup)
    if not uid:
        await ws.close(code=4401)
        return
    await ws.accept()
    await hub.connect(uid, ws)
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(uid, ws)


# ---- serve the built React app (single-page app with client-side routing)
if STATIC_DIR.exists():
    assets = STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = (STATIC_DIR / path).resolve()
        if path and f.is_file() and STATIC_DIR.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
else:
    log.warning("No frontend build found at %s — API only", STATIC_DIR)
