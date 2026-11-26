import { useEffect, useMemo, useRef, useState } from "react";
import { powerColor, titleCase } from "../orders";
import type { GameDetail, Message } from "../types";
import { timeAgo } from "./bits";

const channelOf = (m: Message) => (m.recipient === "GLOBAL" ? "GLOBAL" : [m.sender, m.recipient].sort().join("|"));

interface Props {
  game: GameDetail;
  messages: Message[];
  onSend: (to: string, body: string) => Promise<void>;
  onUnread?: (n: number) => void;
  active: boolean;
}

export default function PressPanel({ game, messages, onSend, onUnread, active }: Props) {
  const me = game.my_power;
  const storeKey = `entente-read-${game.id}`;
  const [lastRead, setLastRead] = useState<Record<string, number>>(() => {
    try {
      return JSON.parse(localStorage.getItem(storeKey) || "{}");
    } catch {
      return {};
    }
  });
  const [channel, setChannel] = useState("GLOBAL");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const forming = game.status === "forming";
  const finished = game.status === "finished";
  const canPrivate = !forming && game.press === "full" && !!me && !finished;

  const channels = useMemo(() => {
    const list = ["GLOBAL"];
    if (forming) return list;
    if (me && game.press === "full") for (const p of game.powers) if (p !== me) list.push([me, p].sort().join("|"));
    for (const m of messages) {
      const c = channelOf(m);
      if (!list.includes(c)) list.push(c);
    }
    return list;
  }, [messages, me, forming, game.press, game.powers]);

  const byChannel = useMemo(() => {
    const out: Record<string, Message[]> = {};
    for (const m of messages) (out[channelOf(m)] ||= []).push(m);
    return out;
  }, [messages]);

  const unread = (c: string) => (byChannel[c] ?? []).filter((m) => m.id > (lastRead[c] ?? 0) && m.sender !== me).length;
  const totalUnread = channels.reduce((n, c) => n + (active && c === channel ? 0 : unread(c)), 0);

  useEffect(() => onUnread?.(totalUnread), [totalUnread, onUnread]);

  const thread = byChannel[channel] ?? [];
  useEffect(() => {
    if (!active) return;
    const max = thread.length ? thread[thread.length - 1].id : 0;
    if (max > (lastRead[channel] ?? 0)) {
      const next = { ...lastRead, [channel]: max };
      setLastRead(next);
      try {
        localStorage.setItem(storeKey, JSON.stringify(next));
      } catch {
        /* storage may be unavailable */
      }
    }
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [thread.length, channel, active]); // eslint-disable-line react-hooks/exhaustive-deps

  const label = (c: string) => {
    if (c === "GLOBAL") return forming ? "Lobby chat" : "Global";
    const [a, b] = c.split("|");
    if (me && (a === me || b === me)) return titleCase(a === me ? b : a);
    return `${titleCase(a)} ↔ ${titleCase(b)}`;
  };
  const playerName = (power: string) => game.players.find((p) => p.power === power)?.display_name;
  const recipient = channel === "GLOBAL" ? "GLOBAL" : channel.split("|").find((p) => p !== me)!;
  const writable =
    forming || (!finished && !!me && game.press !== "none" && (channel === "GLOBAL" || (canPrivate && channel.includes(me))));

  const send = async () => {
    const body = draft.trim();
    if (!body) return;
    setSending(true);
    try {
      await onSend(recipient, body);
      setDraft("");
    } finally {
      setSending(false);
    }
  };

  if (game.press === "none" && !forming && !messages.length)
    return <div className="empty">This is a no-press game — let your orders do the talking.</div>;

  return (
    <div className="press">
      <div className="channels">
        {channels.map((c) => {
          const n = unread(c);
          const other = c === "GLOBAL" ? null : c.split("|").find((p) => p !== me) ?? c.split("|")[0];
          return (
            <button key={c} className={`chan${c === channel ? " on" : ""}`} onClick={() => setChannel(c)}>
              {other ? <span className="dot" style={{ background: powerColor(other) }} /> : <span className="dot globe">◎</span>}
              <span className="chan-name">
                {label(c)}
                {other && playerName(other) && <small>{playerName(other)}</small>}
              </span>
              {n > 0 && c !== channel && <span className="badge">{n}</span>}
            </button>
          );
        })}
      </div>
      <div className="thread">
        <div className="msgs" ref={listRef}>
          {!thread.length && <div className="empty small">No messages yet.{channel !== "GLOBAL" && " Only the two of you can read this."}</div>}
          {thread.map((m, i) => {
            const mine = m.sender === me && !forming;
            const showPhase = i === 0 || thread[i - 1].phase !== m.phase;
            return (
              <div key={m.id}>
                {showPhase && m.phase && <div className="phase-sep">{m.phase}</div>}
                <div className={`bubble${mine ? " mine" : ""}`}>
                  {m.sender !== "LOBBY" && !mine && (
                    <div className="who" style={{ color: powerColor(m.sender) }}>
                      {titleCase(m.sender)}
                      {finished && m.recipient !== "GLOBAL" && <span className="muted"> → {titleCase(m.recipient)}</span>}
                    </div>
                  )}
                  <div className="text">{m.body}</div>
                  <div className="when">{timeAgo(m.created_at)}</div>
                </div>
              </div>
            );
          })}
        </div>
        {writable ? (
          <form
            className="compose"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <textarea
              value={draft}
              placeholder={channel === "GLOBAL" ? "Message everyone…" : `Message ${label(channel)}…`}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={2}
              maxLength={2000}
            />
            <button className="btn primary" disabled={sending || !draft.trim()}>
              Send
            </button>
          </form>
        ) : (
          <div className="compose muted small">{finished ? "The game is over — all press is now revealed." : "You can't post here."}</div>
        )}
      </div>
    </div>
  );
}
