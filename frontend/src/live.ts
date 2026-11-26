import { useEffect } from "react";

/** One websocket per tab; components subscribe to the events they care about. */
export type LiveEvent =
  | { type: "game"; game_id: number; event: string }
  | { type: "message"; game_id: number; message: import("./types").Message }
  | { type: "friends" }
  | { type: "invite"; game_id: number }
  | { type: "lobby" }
  | { type: "variants"; slug?: string }
  | { type: "reconnected" };

type Handler = (e: LiveEvent) => void;
const handlers = new Set<Handler>();
let socket: WebSocket | null = null;
let retry = 0;
let stopped = true;
let pinger: number | undefined;

function emit(e: LiveEvent) {
  handlers.forEach((h) => h(e));
}

function open() {
  if (stopped) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  socket = ws;
  ws.onopen = () => {
    if (retry > 0) emit({ type: "reconnected" });
    retry = 0;
    window.clearInterval(pinger);
    pinger = window.setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
  };
  ws.onmessage = (m) => {
    try {
      const data = JSON.parse(m.data);
      if (data.type !== "pong") emit(data);
    } catch {
      /* ignore */
    }
  };
  ws.onclose = () => {
    window.clearInterval(pinger);
    if (stopped) return;
    retry = Math.min(retry + 1, 6);
    window.setTimeout(open, 500 * 2 ** retry);
  };
}

export function startLive() {
  if (!stopped) return;
  stopped = false;
  open();
}

export function stopLive() {
  stopped = true;
  socket?.close();
  socket = null;
}

export function useLive(handler: Handler, deps: unknown[]) {
  useEffect(() => {
    handlers.add(handler);
    return () => {
      handlers.delete(handler);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
