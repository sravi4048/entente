import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Countdown, PowerChip, Toast } from "../components/bits";
import MapView from "../components/MapView";
import { useLive } from "../live";
import { deadlineLabel, registerPowers, titleCase, useMap } from "../orders";
import type { BoardState, FriendsList, GameDetail, GameSummary, Invite, UserBrief, VariantInfo } from "../types";

const DEADLINES: { label: string; value: number | null }[] = [
  { label: "No clock — resolve when everyone's ready", value: null },
  { label: "10 minutes (live game)", value: 10 },
  { label: "30 minutes", value: 30 },
  { label: "1 hour", value: 60 },
  { label: "6 hours", value: 360 },
  { label: "12 hours", value: 720 },
  { label: "24 hours", value: 1440 },
  { label: "48 hours", value: 2880 },
  { label: "72 hours", value: 4320 },
];

export interface VariantLists {
  builtin: VariantInfo[];
  approved: VariantInfo[];
  mine: VariantInfo[];
  queue: VariantInfo[];
}

type Pane = "classic" | "variants" | "review";

export default function Lobby({ me, onLogout, pane }: { me: UserBrief; onLogout: () => void; pane: Pane }) {
  const [games, setGames] = useState<GameSummary[] | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [friends, setFriends] = useState<FriendsList | null>(null);
  const [variants, setVariants] = useState<VariantLists | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const [friendName, setFriendName] = useState("");
  const [code, setCode] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");

  useEffect(() => {
    api.get<{ source_url: string }>("/config").then((c) => setSourceUrl(c.source_url)).catch(() => {});
  }, []);

  const loadGames = useCallback(() => {
    api
      .get<{ games: GameSummary[]; invites: Invite[] }>("/games")
      .then((r) => {
        setGames(r.games);
        setInvites(r.invites);
      })
      .catch((e) => setError(e.message));
  }, []);
  const loadFriends = useCallback(() => {
    api.get<FriendsList>("/friends").then(setFriends).catch((e) => setError(e.message));
  }, []);
  const loadVariants = useCallback(() => {
    api
      .get<VariantLists>("/variants")
      .then((v) => {
        for (const list of [v.builtin, v.approved, v.mine, v.queue]) for (const x of list) registerPowers(x.powers, false);
        registerPowers(v.builtin.find((b) => b.slug === "classic")?.powers);
        setVariants(v);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadVariants();
    loadGames();
    loadFriends();
  }, [loadGames, loadFriends, loadVariants]);

  useLive(
    (e) => {
      if (e.type === "friends") loadFriends();
      if (e.type === "invite" || e.type === "game" || e.type === "lobby" || e.type === "reconnected") loadGames();
      if (e.type === "variants" || e.type === "reconnected") loadVariants();
      if (e.type === "reconnected") loadFriends();
    },
    [loadGames, loadFriends, loadVariants],
  );

  useEffect(() => {
    const n = games?.filter((g) => g.needs_orders).length ?? 0;
    document.title = n ? `(${n}) Entente` : "Entente";
  }, [games]);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const addFriend = () =>
    act(async () => {
      const name = friendName.trim().replace(/^@/, "");
      if (!name) return;
      const r = await api.post<{ status: string }>("/friends/request", { username: name });
      setFriendName("");
      setError(r.status === "accepted" ? `You and ${name} are now friends` : `Friend request sent to ${name}`);
      loadFriends();
    });

  const joinCode = () => {
    const m = code.trim().match(/([A-Za-z0-9]{6,16})\/?$/);
    if (m) location.hash = `#/join/${m[1]}`;
  };

  const isClassic = (g: GameSummary) => !g.variant || g.variant.slug === "classic";
  const mineHere = (games ?? []).filter((g) => (pane === "classic" ? isClassic(g) : !isClassic(g)));
  const active = mineHere.filter((g) => g.status === "active").sort((a, b) => Number(b.needs_orders) - Number(a.needs_orders));
  const forming = mineHere.filter((g) => g.status === "forming");
  const finished = mineHere.filter((g) => g.status === "finished");
  const playable = [...(variants?.builtin ?? []).filter((v) => v.slug !== "classic"), ...(variants?.approved ?? [])];
  const allVariants = [...(variants?.builtin ?? []), ...(variants?.approved ?? []), ...(variants?.mine ?? []).filter((v) => v.status === "pending")];
  const queueCount = variants?.queue.length ?? 0;
  const otherNeeds = (games ?? []).filter((g) => g.needs_orders && (pane === "classic" ? !isClassic(g) : isClassic(g))).length;

  return (
    <div className="page lobby">
      <header className="topbar">
        <div className="brand">
          <Logo /> Entente
        </div>
        <div className="right">
          <span className="muted">
            {me.display_name} <span className="small">@{me.username}</span>
          </span>
          <button className="btn small ghost" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      <nav className="panes">
        <a href="#/" className={pane === "classic" ? "on" : ""}>
          Classic Diplomacy
          {pane !== "classic" && otherNeeds > 0 && <span className="badge">{otherNeeds}</span>}
        </a>
        <a href="#/variants" className={pane === "variants" ? "on" : ""}>
          Variants &amp; custom maps
          {pane !== "variants" && otherNeeds > 0 && <span className="badge">{otherNeeds}</span>}
        </a>
        {me.is_admin && (
          <a href="#/review" className={pane === "review" ? "on" : ""}>
            Review queue
            {queueCount > 0 && <span className="badge">{queueCount}</span>}
          </a>
        )}
      </nav>

      <main className="lobby-grid">
        <section>
          {pane === "review" ? (
            <ReviewQueue variants={variants} />
          ) : (
            <>
              <div className="section-head">
                <h2>{pane === "classic" ? "Classic games" : "Variant games"}</h2>
                <button className="btn primary" onClick={() => setCreating(pane === "classic" ? "classic" : playable[0]?.slug ?? "ancmed")}>
                  + New game
                </button>
              </div>

              {invites.length > 0 && (
                <div className="card invites">
                  <h3>Invitations</h3>
                  {invites.map((i) => (
                    <div key={i.id} className="invite">
                      <div>
                        <strong>{i.game.name}</strong>
                        <div className="muted small">
                          from {i.inviter.display_name} · {i.game.variant?.name ?? "Classic"} · {i.game.player_count}/{i.game.variant?.players ?? 7} players ·{" "}
                          {deadlineLabel(i.game.deadline_minutes)}
                        </div>
                      </div>
                      <div className="row gap">
                        <button className="btn small ghost" onClick={() => act(async () => (await api.post(`/games/${i.game.id}/decline`), loadGames()))}>
                          Decline
                        </button>
                        <button
                          className="btn small primary"
                          onClick={() =>
                            act(async () => {
                              await api.post(`/games/${i.game.id}/join`);
                              location.hash = `#/game/${i.game.id}`;
                            })
                          }
                        >
                          Join
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {pane === "variants" && (
                <div className="variants-block">
                  <div className="section-head small-head">
                    <h3>Maps</h3>
                    <div className="row gap">
                      <a className="btn small ghost" href="#/maps/guide">
                        How to make a map
                      </a>
                      <a className="btn small" href="#/maps/new">
                        ⬆ Upload a map
                      </a>
                    </div>
                  </div>
                  <div className="vgrid">
                    {playable.map((v) => (
                      <VariantCard key={v.slug} v={v} onPlay={() => setCreating(v.slug)} />
                    ))}
                  </div>
                  {variants && variants.mine.length > 0 && (
                    <div className="glist">
                      <h3>Your submissions</h3>
                      {variants.mine.map((v) => (
                        <a key={v.slug} className="gcard" href={`#/maps/${v.slug}`}>
                          <div className="gmain">
                            <strong>{v.name}</strong>
                            <div className="muted small">
                              {v.players} powers · {v.supply_centers} centers{v.review_note ? ` · “${v.review_note}”` : ""}
                            </div>
                          </div>
                          <span className={`tag status-${v.status}`}>{v.status === "pending" ? "awaiting review" : v.status}</span>
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {games === null && <p className="muted">Loading…</p>}
              {games && !mineHere.length && pane === "classic" && (
                <div className="card empty-state">
                  <h3>No classic games yet</h3>
                  <p className="muted">
                    Start a game, then send the invite link to your group — or add friends and invite them directly. Seven players is the
                    classic game; with fewer, the empty powers sit in civil disorder.
                  </p>
                  <button className="btn primary" onClick={() => setCreating("classic")}>
                    Create a classic game
                  </button>
                </div>
              )}
              {games && !mineHere.length && pane === "variants" && <p className="muted small">You're not in any variant games yet — pick a map above.</p>}

              {active.length > 0 && <GameList title="In progress" games={active} showVariant={pane !== "classic"} />}
              {forming.length > 0 && <GameList title="Waiting for players" games={forming} showVariant={pane !== "classic"} />}
              {finished.length > 0 && <GameList title="Finished" games={finished} showVariant={pane !== "classic"} />}
            </>
          )}
        </section>

        <aside>
          <div className="card">
            <h3>Join with a link</h3>
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                joinCode();
              }}
            >
              <input placeholder="Paste invite link or code" value={code} onChange={(e) => setCode(e.target.value)} />
              <button className="btn">Go</button>
            </form>
          </div>

          <div className="card friends">
            <h3>Friends</h3>
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                addFriend();
              }}
            >
              <input placeholder="Add by username" value={friendName} onChange={(e) => setFriendName(e.target.value)} autoCapitalize="none" />
              <button className="btn">Add</button>
            </form>
            <p className="muted small">
              Your username is <b>@{me.username}</b> — share it so friends can add you.
            </p>

            {friends && friends.incoming.length > 0 && (
              <>
                <h4>Requests</h4>
                <ul className="plist">
                  {friends.incoming.map((f) => (
                    <li key={f.id}>
                      {f.user.display_name} <span className="muted">@{f.user.username}</span>
                      <span className="right row gap">
                        <button className="btn small ghost" onClick={() => act(async () => (await api.del(`/friends/${f.id}`), loadFriends()))}>
                          Ignore
                        </button>
                        <button className="btn small primary" onClick={() => act(async () => (await api.post(`/friends/${f.id}/accept`), loadFriends()))}>
                          Accept
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {friends && (
              <ul className="plist">
                {friends.friends.map((f) => (
                  <li key={f.id}>
                    <span className={`presence${f.user.online ? " on" : ""}`} title={f.user.online ? "Online" : "Offline"} />
                    {f.user.display_name} <span className="muted">@{f.user.username}</span>
                    <button
                      className="x right"
                      title="Remove friend"
                      onClick={() => confirm(`Remove ${f.user.display_name} from friends?`) && act(async () => (await api.del(`/friends/${f.id}`), loadFriends()))}
                    >
                      ×
                    </button>
                  </li>
                ))}
                {friends.outgoing.map((f) => (
                  <li key={f.id} className="muted">
                    {f.user.display_name} @{f.user.username} <span className="tag">pending</span>
                  </li>
                ))}
                {!friends.friends.length && !friends.outgoing.length && <li className="muted small">No friends added yet.</li>}
              </ul>
            )}
          </div>
        </aside>
      </main>

      <footer className="foot muted small">
        Rules adjudicated by the open-source <a href="https://github.com/diplomacy/diplomacy">diplomacy</a> engine (AGPL-3.0).
        {sourceUrl && (
          <>
            {" "}
            · <a href={sourceUrl}>Source code</a>
          </>
        )}
      </footer>
      {creating && <CreateGame initial={creating} variants={allVariants} onClose={() => setCreating(null)} onError={setError} />}
      <Toast text={error} onClose={() => setError(null)} />
    </div>
  );
}

function VariantCard({ v, onPlay }: { v: VariantInfo; onPlay: () => void }) {
  const map = useMap(`/variants/${v.slug}/map`);
  const [start, setStart] = useState<BoardState | null>(null);
  useEffect(() => {
    api.get<BoardState>(`/variants/${v.slug}/start`).then(setStart).catch(() => {});
  }, [v.slug]);
  return (
    <div className="vcard card">
      <a className="vthumb" href={v.builtin ? undefined : `#/maps/${v.slug}`}>
        {map ? <MapView map={map} board={start} interactive={false} compact /> : <div className="thumb-ph" />}
      </a>
      <div className="vbody">
        <div className="row">
          <strong>{v.name}</strong>
          {!v.builtin && <span className="tag">community</span>}
        </div>
        <div className="muted small">
          {v.players} players · {v.supply_centers} centers · {v.victory} to win
          {v.author && ` · by ${v.author.display_name}`}
        </div>
        <p className="small vdesc">{v.description}</p>
        <div className="row gap">
          <button className="btn small primary" onClick={onPlay}>
            New game
          </button>
          {!v.builtin && (
            <a className="btn small ghost" href={`#/maps/${v.slug}`}>
              Details
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function ReviewQueue({ variants }: { variants: VariantLists | null }) {
  if (!variants) return <p className="muted">Loading…</p>;
  return (
    <div>
      <div className="section-head">
        <h2>Maps awaiting review</h2>
      </div>
      {!variants.queue.length && (
        <div className="card empty-state">
          <h3>Nothing to review</h3>
          <p className="muted">When someone uploads a map, it shows up here. Approved maps appear in everyone's Variants pane.</p>
        </div>
      )}
      <div className="glist">
        {variants.queue.map((v) => (
          <a key={v.slug} className="gcard needs" href={`#/maps/${v.slug}`}>
            <div className="gmain">
              <strong>{v.name}</strong>
              <div className="muted small">
                by {v.author?.display_name} · {v.players} powers · {v.supply_centers} centers
                {v.rules_text ? " · has special rules" : ""}
              </div>
            </div>
            <span className="tag hot">Review</span>
          </a>
        ))}
      </div>
      {variants.approved.length > 0 && (
        <div className="glist">
          <h3>Live community maps</h3>
          {variants.approved.map((v) => (
            <a key={v.slug} className="gcard" href={`#/maps/${v.slug}`}>
              <div className="gmain">
                <strong>{v.name}</strong>
                <div className="muted small">by {v.author?.display_name}</div>
              </div>
              <span className="tag status-approved">live</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function GameList({ title, games, showVariant }: { title: string; games: GameSummary[]; showVariant?: boolean }) {
  return (
    <div className="glist">
      <h3>{title}</h3>
      {games.map((g) => (
        <a key={g.id} className={`gcard${g.needs_orders ? " needs" : ""}`} href={`#/game/${g.id}`}>
          <div className="gmain">
            <strong>{g.name}</strong>
            <div className="muted small">
              {showVariant && g.variant && <>{g.variant.name} · </>}
              {g.status === "forming"
                ? `${g.player_count}/${g.variant?.players ?? 7} joined · hosted by ${g.creator.display_name}`
                : g.status === "finished"
                  ? g.result?.type === "solo"
                    ? `${titleCase(g.result.powers[0])} won`
                    : `Draw · ${g.result?.powers.map(titleCase).join(", ")}`
                  : `${g.phase_label}${g.my_centers !== null ? ` · ${g.my_centers} centers` : ""}`}
            </div>
          </div>
          <div className="gside">
            {g.my_power && <PowerChip power={g.my_power} />}
            {g.status === "active" && (g.needs_orders ? <span className="tag hot">Orders needed</span> : <Countdown deadline={g.deadline_at} />)}
          </div>
        </a>
      ))}
    </div>
  );
}

function CreateGame({ initial, variants, onClose, onError }: { initial: string; variants: VariantInfo[]; onClose: () => void; onError: (m: string) => void }) {
  const [name, setName] = useState("");
  const [variant, setVariant] = useState(initial);
  const [deadline, setDeadline] = useState<number | null>(1440);
  const [assignment, setAssignment] = useState<"random" | "choice">("random");
  const [press, setPress] = useState<"full" | "public" | "none">("full");
  const [busy, setBusy] = useState(false);
  const chosen = variants.find((v) => v.slug === variant);

  const submit = async () => {
    setBusy(true);
    try {
      const g = await api.post<GameDetail>("/games", {
        name: name.trim() || "Untitled game",
        variant,
        deadline_minutes: deadline,
        assignment,
        press,
      });
      location.hash = `#/game/${g.id}`;
    } catch (e) {
      onError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <form
        className="modal card"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <h2>New game</h2>
        <label>
          Name
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Friday night backstabbing" maxLength={80} />
        </label>
        <label>
          Map
          <select value={variant} onChange={(e) => setVariant(e.target.value)}>
            {variants.map((v) => (
              <option key={v.slug} value={v.slug}>
                {v.name} — {v.players} players{v.status === "pending" ? " (playtest, not yet approved)" : ""}
              </option>
            ))}
          </select>
          {chosen && <small className="muted">{chosen.description}</small>}
        </label>
        <label>
          Phase length
          <select value={deadline ?? ""} onChange={(e) => setDeadline(e.target.value ? Number(e.target.value) : null)}>
            {DEADLINES.map((d) => (
              <option key={d.label} value={d.value ?? ""}>
                {d.label}
              </option>
            ))}
          </select>
          <small className="muted">A phase resolves early as soon as everyone marks ready.</small>
        </label>
        <label>
          Powers
          <select value={assignment} onChange={(e) => setAssignment(e.target.value as "random" | "choice")}>
            <option value="random">Assigned at random</option>
            <option value="choice">Players choose</option>
          </select>
        </label>
        <label>
          Press
          <select value={press} onChange={(e) => setPress(e.target.value as "full" | "public" | "none")}>
            <option value="full">Full press (private messages)</option>
            <option value="public">Public press only</option>
            <option value="none">No press (gunboat)</option>
          </select>
        </label>
        <div className="row gap end">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy}>
            Create game
          </button>
        </div>
      </form>
    </div>
  );
}

export function Logo() {
  return (
    <svg viewBox="0 0 64 64" width="26" height="26" aria-hidden>
      <path d="M32 6 L54 18 V35 C54 47 44 54 32 58 C20 54 10 47 10 35 V18 Z" fill="#c9a24a" />
      <path d="M32 16 L45 23 V34 C45 41 39 46 32 49 C25 46 19 41 19 34 V23 Z" fill="#1b2230" />
      <path d="M26 30 L32 26 L38 30 L32 40 Z" fill="#c9a24a" />
    </svg>
  );
}
