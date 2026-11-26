"""In-process WebSocket fan-out.

Sync request handlers run in a threadpool, so `publish` hands work to the
event loop thread-safely. This keeps everything in one process; to run more
than one instance you would swap this for Redis pub/sub.
"""
import asyncio
import json
from collections import defaultdict
from typing import Dict, Iterable, Optional, Set

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self.sockets: Dict[int, Set[WebSocket]] = defaultdict(set)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        self.sockets[user_id].add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        self.sockets[user_id].discard(ws)
        if not self.sockets[user_id]:
            self.sockets.pop(user_id, None)

    def online(self, user_id: int) -> bool:
        return bool(self.sockets.get(user_id))

    async def _send(self, user_ids: Iterable[int], payload: str) -> None:
        for uid in set(user_ids):
            for ws in list(self.sockets.get(uid, ())):
                try:
                    await ws.send_text(payload)
                except Exception:
                    self.disconnect(uid, ws)

    def publish(self, user_ids: Iterable[int], event: dict) -> None:
        if not self.loop:
            return
        payload = json.dumps(event, default=str)
        ids = list(user_ids)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(self._send(ids, payload))
        else:
            asyncio.run_coroutine_threadsafe(self._send(ids, payload), self.loop)


hub = Hub()
