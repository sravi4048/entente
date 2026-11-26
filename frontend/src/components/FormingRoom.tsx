import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useLive } from "../live";
import { deadlineLabel, powerColor, titleCase, useMap } from "../orders";
import type { BoardState, FriendsList, GameDetail, Message } from "../types";
import MapView from "./MapView";
import PressPanel from "./PressPanel";

interface Props {
  game: GameDetail;
  meId: number;
  messages: Message[];
  onChange: (g: GameDetail) => void;
  onSend: (to: string, body: string) => Promise<void>;
  onError: (msg: string) => void;
}

export default function FormingRoom({ game, meId, messages, onChange, onSend, onError }: Props) {
  const [friends, setFriends] = useState<FriendsList | null>(null);
  const [invited, setInvited] = useState<number[]>([]);
  const [copied, setCopied] = useState(false);
  const link = `${location.origin}/#/join/${game.invite_code}`;
  const me = game.players.find((p) => p.user_id === meId);
  const slug = game.variant?.slug ?? "classic";
  const map = useMap(`/variants/${slug}/map`);
  const [startBoard, setStartBoard] = useState<BoardState | null>(null);
  useEffect(() => {
    api.get<BoardState>(`/variants/${slug}/start`).then(setStartBoard).catch(() => {});
  }, [slug]);
  const maxPlayers = game.powers.length;

  const loadSide = useCallback(() => {
    api.get<FriendsList>("/friends").then(setFriends).catch(() => {});
    api.get<number[]>(`/games/${game.id}/invites`).then(setInvited).catch(() => {});
  }, [game.id]);
  useEffect(loadSide, [loadSide]);
  useLive((e) => e.type === "friends" && loadSide(), [loadSide]);

  const act = async <T,>(fn: () => Promise<T>) => {
    try {
      return await fn();
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const pick = (power: string | null) =>
    act(async () => onChange(await api.post<GameDetail>(`/games/${game.id}/power`, { power })));
  const invite = (uid: number) =>
    act(async () => {
      await api.post(`/games/${game.id}/invite`, { user_id: uid });
      setInvited((s) => [...s, uid]);
    });
  const start = () =>
    act(async () => {
      const open = maxPlayers - game.players.length;
      if (open > 0 && !confirm(`${open} power${open > 1 ? "s" : ""} will start in civil disorder (always hold). Start anyway?`)) return;
      onChange(await api.post<GameDetail>(`/games/${game.id}/start`));
    });
  const leave = () =>
    act(async () => {
      if (!confirm(game.is_creator ? "Delete this game for everyone?" : "Leave this game?")) return;
      await api.post(`/games/${game.id}/leave`);
      location.hash = "#/";
    });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      prompt("Copy this link", link);
    }
  };

  const memberIds = new Set(game.players.map((p) => p.user_id));
  const invitable = (friends?.friends ?? []).filter((f) => !memberIds.has(f.user.id));

  return (
    <div className="forming">
      <section className="card forming-main">
        <div className="forming-head">
          <div>
            <h2>{game.name}</h2>
            <p className="muted">
              {game.variant && game.variant.slug !== "classic" && <>{game.variant.name} · </>}Waiting for players · {game.players.length}/{maxPlayers} joined · {deadlineLabel(game.deadline_minutes)} ·{" "}
              {game.assignment === "random" ? "random powers" : "players pick powers"} ·{" "}
              {game.press === "full" ? "full press" : game.press === "public" ? "public press only" : "no press"}
            </p>
          </div>
          <div className="row gap">
            <button className="btn ghost" onClick={leave}>
              {game.is_creator ? "Delete game" : "Leave"}
            </button>
            {game.is_creator && (
              <button className="btn primary" onClick={start}>
                Start game
              </button>
            )}
          </div>
        </div>

        <div className="share">
          <label>Invite link</label>
          <div className="row">
            <input readOnly value={link} onFocus={(e) => e.target.select()} />
            <button className="btn" onClick={copy}>
              {copied ? "Copied ✓" : "Copy"}
            </button>
          </div>
        </div>

        <div className="forming-grid">
          <div>
            <h3>Players</h3>
            <ul className="plist">
              {game.players.map((p) => (
                <li key={p.user_id}>
                  <span className={`presence${p.online ? " on" : ""}`} />
                  <strong>{p.display_name}</strong>
                  <span className="muted"> @{p.username}</span>
                  {p.user_id === game.creator.id && <span className="tag">host</span>}
                  {p.power && (
                    <span className="chip right">
                      <span className="dot" style={{ background: powerColor(p.power) }} />
                      {titleCase(p.power)}
                    </span>
                  )}
                </li>
              ))}
            </ul>

            {game.assignment === "choice" && (
              <>
                <h3>Choose your power</h3>
                <div className="power-grid">
                  {game.powers.map((pw) => {
                    const holder = game.players.find((p) => p.power === pw);
                    const mine = me?.power === pw;
                    return (
                      <button
                        key={pw}
                        className={`power-pick${mine ? " on" : ""}`}
                        disabled={!!holder && !mine}
                        onClick={() => pick(mine ? null : pw)}
                        style={{ borderColor: powerColor(pw) }}
                      >
                        <span className="dot" style={{ background: powerColor(pw) }} />
                        {titleCase(pw)}
                        <small>{holder ? holder.display_name : "open"}</small>
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          <div>
            <h3>Invite friends</h3>
            {!friends && <p className="muted">Loading…</p>}
            {friends && !invitable.length && (
              <p className="muted small">
                {friends.friends.length ? "All your friends are in." : "Add friends from the lobby, or just send them the link above."}
              </p>
            )}
            <ul className="plist">
              {invitable.map((f) => (
                <li key={f.id}>
                  <span className={`presence${f.user.online ? " on" : ""}`} />
                  {f.user.display_name}
                  <span className="muted"> @{f.user.username}</span>
                  <button className="btn small right" disabled={invited.includes(f.user.id)} onClick={() => invite(f.user.id)}>
                    {invited.includes(f.user.id) ? "Invited" : "Invite"}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="preview">
          {map && <MapView map={map} board={startBoard} interactive={false} compact />}
        </div>
      </section>
      <section className="card forming-chat">
        <PressPanel game={game} messages={messages} onSend={onSend} active />
      </section>
    </div>
  );
}
