import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { Countdown, PowerChip, Toast } from "../components/bits";
import FormingRoom from "../components/FormingRoom";
import MapView, { type DrawnOrder } from "../components/MapView";
import PowersPanel from "../components/PowersPanel";
import PressPanel from "../components/PressPanel";
import { useLive } from "../live";
import { describeOrder, parseOrder, powerAdj, prov, titleCase, useMap, type ParsedOrder } from "../orders";
import type { GameDetail, HistoryPhase, Message, UserBrief } from "../types";

type Entry =
  | { mode: "idle" }
  | { mode: "unit"; loc: string }
  | { mode: "support"; loc: string; target?: string }
  | { mode: "convoy"; loc: string; target?: string };

type Chooser = { title: string; options: { label: string; order: string }[] } | null;
type Tab = "orders" | "press" | "powers" | "history";

const coastWord = (loc: string) => {
  const c = loc.split("/")[1];
  return c ? ` (${c === "NC" ? "north" : c === "SC" ? "south" : "east"} coast)` : "";
};

export default function GamePage({ gameId, me }: { gameId: number; me: UserBrief }) {
  const [game, setGame] = useState<GameDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [orders, setOrders] = useState<string[]>([]);
  const [entry, setEntry] = useState<Entry>({ mode: "idle" });
  const [chooser, setChooser] = useState<Chooser>(null);
  const [tab, setTab] = useState<Tab>("orders");
  const [unread, setUnread] = useState(0);
  const [viewPhase, setViewPhase] = useState<string | null>(null);
  const [hist, setHist] = useState<HistoryPhase | null>(null);
  const [saving, setSaving] = useState(false);
  const [skew, setSkew] = useState(0);
  const phaseRef = useRef<string | null>(null);
  const map = useMap(game && game.status !== "forming" ? `/games/${gameId}/map` : null);
  const locName = (l: string) => (map ? map.locName(l) : l);
  const unitLabel = (u: string) => (map ? map.unitLabel(u) : u);
  const describe = (o: string) => describeOrder(o, locName);

  const load = useCallback(async () => {
    try {
      const g = await api.get<GameDetail>(`/games/${gameId}`);
      setSkew(new Date(g.server_time).getTime() - Date.now());
      setGame(g);
      setOrders(g.my_orders ?? []);
      if (phaseRef.current && phaseRef.current !== g.phase) {
        setEntry({ mode: "idle" });
        setChooser(null);
        setViewPhase(null);
      }
      phaseRef.current = g.phase;
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 403 || status === 404) setNotFound(true);
      else setError((e as Error).message);
    }
  }, [gameId]);

  const loadMessages = useCallback(() => {
    api.get<Message[]>(`/games/${gameId}/messages`).then(setMessages).catch(() => {});
  }, [gameId]);

  useEffect(() => {
    load();
    loadMessages();
  }, [load, loadMessages]);

  useLive(
    (e) => {
      if (e.type === "reconnected") {
        load();
        loadMessages();
      }
      if (e.type === "game" && e.game_id === gameId) {
        if (e.event === "deleted") location.hash = "#/";
        else {
          load();
          if (e.event === "started" || e.event === "finished" || e.event === "processed") loadMessages();
        }
      }
      if (e.type === "message" && e.game_id === gameId) setMessages((m) => (m.some((x) => x.id === e.message.id) ? m : [...m, e.message]));
    },
    [gameId, load, loadMessages],
  );

  // ---- history
  useEffect(() => {
    if (!viewPhase) return setHist(null);
    api.get<HistoryPhase>(`/games/${gameId}/history/${viewPhase}`).then(setHist).catch((e) => setError(e.message));
  }, [viewPhase, gameId]);

  const sendMessage = async (to: string, body: string) => {
    try {
      const m = await api.post<Message>(`/games/${gameId}/messages`, { to, body });
      setMessages((list) => (list.some((x) => x.id === m.id) ? list : [...list, m]));
    } catch (e) {
      setError((e as Error).message);
      throw e;
    }
  };

  const board = game?.board;
  const myPower = game?.my_power ?? null;
  const po = game?.possible_orders ?? {};
  const phaseType = board?.phase.slice(-1) ?? "M";
  const active = game?.status === "active";
  const viewingHistory = !!viewPhase;
  const buildCount = myPower && board ? board.builds?.[myPower]?.count ?? 0 : 0;

  const myLocByProv = useMemo(() => {
    const m = new Map<string, string>();
    for (const loc of Object.keys(po)) m.set(prov(loc), loc);
    return m;
  }, [po]);

  const parsedOpts = useCallback((loc: string): ParsedOrder[] => (po[loc] ?? []).map(parseOrder), [po]);

  const orderByProv = useMemo(() => {
    const m = new Map<string, string>();
    for (const o of orders) {
      const p = parseOrder(o);
      if (p.kind !== "WAIVE") m.set(prov(p.loc!), o);
    }
    return m;
  }, [orders]);

  const save = async (next: string[]) => {
    const prev = orders;
    setOrders(next);
    setSaving(true);
    try {
      const r = await api.post<{ orders: string[] }>(`/games/${gameId}/orders`, { orders: next });
      setOrders(r.orders);
    } catch (e) {
      setOrders(prev);
      setError((e as Error).message);
      load();
    } finally {
      setSaving(false);
    }
  };

  const commit = (order: string) => {
    const p = parseOrder(order);
    const key = p.kind === "WAIVE" ? null : prov(p.loc!);
    const next = key ? orders.filter((o) => parseOrder(o).kind === "WAIVE" || prov(parseOrder(o).loc!) !== key) : [...orders];
    next.push(order);
    setEntry({ mode: "idle" });
    setChooser(null);
    save(next);
  };

  const clearOrder = (key: string) => save(orders.filter((o) => (parseOrder(o).kind === "WAIVE" ? key !== "WAIVE" : prov(parseOrder(o).loc!) !== key)));
  const removeOneWaive = () => {
    const i = orders.indexOf("WAIVE");
    if (i >= 0) save(orders.filter((_, j) => j !== i));
  };

  const pickFrom = (cands: ParsedOrder[], title: string) => {
    const direct = cands.filter((c) => !c.via);
    const list = direct.length ? direct : cands;
    const byDest = new Map<string, ParsedOrder>();
    for (const c of list) if (!byDest.has(c.dest ?? c.raw)) byDest.set(c.dest ?? c.raw, c);
    const uniq = [...byDest.values()];
    if (uniq.length === 1) return commit(uniq[0].raw);
    setChooser({ title, options: uniq.map((c) => ({ label: c.dest ? locName(c.dest) : describe(c.raw), order: c.raw })) });
  };

  // ---- the click state machine
  const onProvince = (p: string) => {
    if (!game || !active || viewingHistory || !myPower) return;
    setChooser(null);

    if (phaseType === "A") {
      const loc = myLocByProv.get(p);
      if (!loc) return;
      if (orderByProv.has(p)) return clearOrder(p);
      const opts = parsedOpts(loc).filter((o) => o.kind !== "WAIVE");
      if (buildCount > 0) {
        const builds = orders.filter((o) => parseOrder(o).kind === "B" || o === "WAIVE").length;
        if (builds >= buildCount) return setError(`You can only build ${buildCount} unit${buildCount > 1 ? "s" : ""}. Clear one first.`);
        if (opts.length === 1) return commit(opts[0].raw);
        return setChooser({
          title: `Build in ${locName(p)}`,
          options: opts.map((o) => ({ label: `${o.utype === "F" ? "Fleet" : "Army"}${coastWord(o.loc!)}`, order: o.raw })),
        });
      }
      const d = opts.find((o) => o.kind === "D");
      if (d) commit(d.raw);
      return;
    }

    const sameUnit = entry.mode !== "idle" && prov(entry.loc) === p;
    switch (entry.mode) {
      case "idle": {
        if (myLocByProv.has(p)) setEntry({ mode: "unit", loc: myLocByProv.get(p)! });
        return;
      }
      case "unit": {
        const opts = parsedOpts(entry.loc);
        if (sameUnit) {
          const hold = opts.find((o) => o.kind === "H");
          if (hold) commit(hold.raw);
          else setEntry({ mode: "idle" });
          return;
        }
        const moves = opts.filter((o) => (o.kind === "M" || o.kind === "R") && prov(o.dest!) === p);
        if (moves.length) return pickFrom(moves, `Move to ${locName(p)}`);
        if (myLocByProv.has(p)) return setEntry({ mode: "unit", loc: myLocByProv.get(p)! });
        return setEntry({ mode: "idle" });
      }
      case "support":
      case "convoy": {
        const kind = entry.mode === "support" ? "S" : "C";
        const opts = parsedOpts(entry.loc).filter((o) => o.kind === kind);
        if (!entry.target) {
          const forTarget = opts.filter((o) => prov(o.targetLoc!) === p);
          if (!forTarget.length) {
            if (sameUnit) return setEntry({ mode: "unit", loc: entry.loc });
            return;
          }
          const target = forTarget[0].target!;
          if (forTarget.length === 1 && !forTarget[0].dest) return commit(forTarget[0].raw);
          return setEntry({ ...entry, target });
        }
        const tProv = prov(entry.target.split(" ")[1]);
        const forT = opts.filter((o) => o.target === entry.target);
        if (p === tProv) {
          const hold = forT.find((o) => !o.dest);
          if (hold) return commit(hold.raw);
        }
        const dest = forT.filter((o) => o.dest && prov(o.dest) === p);
        if (dest.length) return commit(dest[0].raw);
        return;
      }
    }
  };

  const highlights = useMemo(() => {
    const s = new Set<string>();
    if (!active || viewingHistory || !myPower) return s;
    if (phaseType === "A") {
      if (buildCount > 0) for (const p of myLocByProv.keys()) if (!orderByProv.has(p)) s.add(p);
      return s;
    }
    if (entry.mode === "unit") {
      for (const o of parsedOpts(entry.loc)) if ((o.kind === "M" || o.kind === "R") && o.dest) s.add(prov(o.dest));
    } else if (entry.mode === "support" || entry.mode === "convoy") {
      const kind = entry.mode === "support" ? "S" : "C";
      const opts = parsedOpts(entry.loc).filter((o) => o.kind === kind);
      if (!entry.target) for (const o of opts) s.add(prov(o.targetLoc!));
      else
        for (const o of opts.filter((x) => x.target === entry.target)) {
          if (o.dest) s.add(prov(o.dest));
          else s.add(prov(o.targetLoc!));
        }
    }
    return s;
  }, [entry, active, viewingHistory, myPower, phaseType, buildCount, myLocByProv, orderByProv, parsedOpts]);

  // Keyboard shortcuts while a unit is selected.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea")) return;
      if (e.key === "Escape") {
        setEntry({ mode: "idle" });
        setChooser(null);
      }
      if (entry.mode === "idle") return;
      const opts = parsedOpts(entry.loc);
      if (e.key === "h") {
        const hold = opts.find((o) => o.kind === "H");
        if (hold) commit(hold.raw);
      }
      if (e.key === "s" && opts.some((o) => o.kind === "S")) setEntry({ mode: "support", loc: entry.loc });
      if (e.key === "c" && opts.some((o) => o.kind === "C")) setEntry({ mode: "convoy", loc: entry.loc });
      if (e.key === "d") {
        const d = opts.find((o) => o.kind === "D");
        if (d) commit(d.raw);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (notFound)
    return (
      <div className="center-page">
        <div className="card narrow">
          <h2>Game not found</h2>
          <p className="muted">It may have been deleted, or you're not a member. Ask for the invite link.</p>
          <a className="btn" href="#/">
            Back to lobby
          </a>
        </div>
      </div>
    );
  if (!game) return <div className="center-page muted">Loading game…</div>;

  if (game.status === "forming")
    return (
      <div className="page">
        <TopBar game={game} skew={skew} />
        <FormingRoom game={game} meId={me.id} messages={messages} onChange={setGame} onSend={sendMessage} onError={setError} />
        <Toast text={error} onClose={() => setError(null)} />
      </div>
    );

  if (!map) return <div className="center-page muted">Loading map…</div>;
  const shownBoard = hist ?? board!;
  const drawn: DrawnOrder[] = hist
    ? Object.entries(hist.orders).flatMap(([power, list]) =>
        (list ?? []).map((raw) => {
          const p = parseOrder(raw);
          const res = p.unit ? hist.results[p.unit] ?? [] : [];
          return { raw, power, failed: res.length > 0 && !(res.length === 1 && res[0] === "") };
        }),
      )
    : myPower
      ? orders.map((raw) => ({ raw, power: myPower, pending: true }))
      : [];

  const selectedProv = entry.mode !== "idle" ? prov(entry.loc) : null;
  const history = game.history ?? [];
  const histIdx = viewPhase ? history.indexOf(viewPhase) : history.length;
  const step = (d: number) => {
    const i = Math.min(Math.max(histIdx + d, 0), history.length);
    setViewPhase(i >= history.length ? null : history[i]);
    setEntry({ mode: "idle" });
  };

  const me_ = game.players.find((p) => p.user_id === me.id);
  const iNeed = !!me_?.needs_orders;
  const waiting = game.players.filter((p) => p.needs_orders && !p.ready && p.user_id !== me.id);

  const toggleReady = async () => {
    try {
      const g = await api.post<GameDetail>(`/games/${gameId}/ready`, { ready: !game.ready });
      setGame(g);
      setOrders(g.my_orders ?? []);
      phaseRef.current = g.phase;
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const toggleDraw = async () => {
    try {
      setGame(await api.post<GameDetail>(`/games/${gameId}/draw`, { vote: !game.draw_vote }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const selOpts = entry.mode !== "idle" ? parsedOpts(entry.loc) : [];
  const hint = (() => {
    if (viewingHistory || !active || !myPower) return null;
    if (phaseType === "A") {
      if (buildCount > 0) return `Tap a highlighted home center to build (${buildCount} available).`;
      if (buildCount < 0) return `Tap ${-buildCount} of your units to disband.`;
      return null;
    }
    if (entry.mode === "unit") return phaseType === "R" ? "Tap a highlighted territory to retreat." : "Tap a highlighted territory to move, or the unit again to hold.";
    if (entry.mode === "support") return entry.target ? `Tap where ${unitLabel(entry.target)} is going — or tap it to support its hold.` : "Tap the unit to support.";
    if (entry.mode === "convoy") return entry.target ? "Tap the army's destination." : "Tap the army to convoy.";
    if (iNeed) return phaseType === "R" ? "Tap a dislodged unit to order its retreat." : "Tap one of your units to give it an order.";
    return null;
  })();

  return (
    <div className="page game">
      <TopBar game={game} skew={skew} />
      {game.result && (
        <div className="banner">
          {game.result.type === "solo" ? (
            <>
              🏆 <strong>{titleCase(game.result.powers[0])}</strong> wins with a solo victory!
            </>
          ) : (
            <>
              🤝 Draw shared by {game.result.powers.map((p) => titleCase(p)).join(", ")}.
            </>
          )}
        </div>
      )}
      <div className="layout">
        <div className="board">
          <div className="board-head">
            <div className="phase-nav">
              <button className="icon" onClick={() => step(-1)} disabled={histIdx <= 0} aria-label="Previous phase">
                ‹
              </button>
              <div className="phase-name">
                {shownBoard.phase_label}
                {viewingHistory && <span className="tag">history</span>}
              </div>
              <button className="icon" onClick={() => step(1)} disabled={!viewingHistory} aria-label="Next phase">
                ›
              </button>
              {viewingHistory && (
                <button className="btn small" onClick={() => setViewPhase(null)}>
                  Back to now
                </button>
              )}
            </div>
            {hint && <div className="hint">{hint}</div>}
          </div>
          <MapView map={map} board={shownBoard} orders={drawn} highlights={highlights} selected={selectedProv} onProvinceClick={onProvince} />
          {entry.mode !== "idle" && !viewingHistory && (
            <div className="actionbar">
              <span className="unit-name">{unitLabel(selOpts[0]?.unit ?? entry.loc)}</span>
              {phaseType === "M" && (
                <>
                  <button className={`btn small${entry.mode === "unit" ? " on" : ""}`} onClick={() => setEntry({ mode: "unit", loc: entry.loc })}>
                    Move
                  </button>
                  <button className="btn small" onClick={() => commit(selOpts.find((o) => o.kind === "H")!.raw)}>
                    Hold
                  </button>
                  {selOpts.some((o) => o.kind === "S") && (
                    <button className={`btn small${entry.mode === "support" ? " on" : ""}`} onClick={() => setEntry({ mode: "support", loc: entry.loc })}>
                      Support
                    </button>
                  )}
                  {selOpts.some((o) => o.kind === "C") && (
                    <button className={`btn small${entry.mode === "convoy" ? " on" : ""}`} onClick={() => setEntry({ mode: "convoy", loc: entry.loc })}>
                      Convoy
                    </button>
                  )}
                </>
              )}
              {phaseType === "R" && selOpts.some((o) => o.kind === "D") && (
                <button className="btn small" onClick={() => commit(selOpts.find((o) => o.kind === "D")!.raw)}>
                  Disband
                </button>
              )}
              <button className="btn small ghost" onClick={() => setEntry({ mode: "idle" })}>
                Cancel
              </button>
            </div>
          )}
          {chooser && (
            <div className="chooser">
              <div className="chooser-title">{chooser.title}</div>
              {chooser.options.map((o) => (
                <button key={o.order} className="btn" onClick={() => commit(o.order)}>
                  {o.label}
                </button>
              ))}
              <button className="btn ghost" onClick={() => setChooser(null)}>
                Cancel
              </button>
            </div>
          )}
        </div>

        <aside className="side">
          <nav className="tabs">
            {(["orders", "press", "powers", "history"] as Tab[]).map((t) => (
              <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {t === "orders" ? "Orders" : t === "press" ? "Press" : t === "powers" ? "Powers" : "History"}
                {t === "press" && unread > 0 && tab !== "press" && <span className="badge">{unread}</span>}
              </button>
            ))}
          </nav>
          <div className="tabbody">
            <div style={{ display: tab === "orders" ? "block" : "none" }}>
              <OrdersTab
                game={game}
                orders={orders}
                po={po}
                buildCount={buildCount}
                phaseType={phaseType}
                saving={saving}
                iNeed={iNeed}
                waiting={waiting.map((w) => w.power!).filter(Boolean)}
                describe={describe}
                unitLabel={unitLabel}
                onSelect={(loc) => {
                  setViewPhase(null);
                  setEntry({ mode: "unit", loc });
                }}
                onClear={clearOrder}
                onWaive={() => commit("WAIVE")}
                onUnwaive={removeOneWaive}
                onReady={toggleReady}
                onDraw={toggleDraw}
              />
            </div>
            <div style={{ display: tab === "press" ? "block" : "none" }} className="fill">
              <PressPanel game={game} messages={messages} onSend={sendMessage} onUnread={setUnread} active={tab === "press"} />
            </div>
            {tab === "powers" && <PowersPanel game={game} board={shownBoard} />}
            {tab === "history" && (
              <div className="histlist">
                {!history.length && <p className="muted">Nothing has happened yet.</p>}
                {[...history].reverse().map((h) => (
                  <button key={h} className={`histitem${viewPhase === h ? " on" : ""}`} onClick={() => setViewPhase(h)}>
                    {h}
                    <span className="muted small">{labelOf(h)}</span>
                  </button>
                ))}
                {hist && <HistoryOrders hist={hist} describe={describe} />}
              </div>
            )}
          </div>
        </aside>
      </div>
      <Toast text={error} onClose={() => setError(null)} />
    </div>
  );
}

const SEASON: Record<string, string> = { S: "Spring", F: "Fall", W: "Winter" };
const PTYPE: Record<string, string> = { M: "Movement", R: "Retreats", A: "Adjustments" };
const labelOf = (h: string) => `${SEASON[h[0]] ?? ""} ${h.slice(1, 5)} ${PTYPE[h[5]] ?? ""}`;

function TopBar({ game, skew }: { game: GameDetail; skew: number }) {
  return (
    <header className="topbar">
      <a href="#/" className="back" aria-label="Back to lobby">
        ‹ Games
      </a>
      <div className="title">
        <strong>{game.name}</strong>
        {game.status === "active" && <span className="muted"> · {game.phase_label}</span>}
      </div>
      <div className="right">
        {game.status === "active" && <Countdown deadline={game.deadline_at} skew={skew} />}
        {game.my_power && <PowerChip power={game.my_power} />}
      </div>
    </header>
  );
}

function HistoryOrders({ hist, describe }: { hist: HistoryPhase; describe: (o: string) => string }) {
  return (
    <div className="historders">
      {Object.entries(hist.orders)
        .filter(([, l]) => l && l.length)
        .map(([power, list]) => (
          <div key={power} className="hgroup">
            <PowerChip power={power} />
            <ul>
              {list.map((o) => {
                const p = parseOrder(o);
                const res = p.unit ? hist.results[p.unit] ?? [] : [];
                return (
                  <li key={o} className={res.length ? "failed" : ""}>
                    {describe(o)}
                    {res.length > 0 && <span className="result">{res.join(", ")}</span>}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
    </div>
  );
}

interface OrdersTabProps {
  game: GameDetail;
  describe: (o: string) => string;
  unitLabel: (u: string) => string;
  orders: string[];
  po: Record<string, string[]>;
  buildCount: number;
  phaseType: string;
  saving: boolean;
  iNeed: boolean;
  waiting: string[];
  onSelect: (loc: string) => void;
  onClear: (key: string) => void;
  onWaive: () => void;
  onUnwaive: () => void;
  onReady: () => void;
  onDraw: () => void;
}

function OrdersTab(props: OrdersTabProps) {
  const { game, orders, po, buildCount, phaseType, saving, iNeed, waiting, describe, unitLabel } = props;
  const me = game.my_power;
  if (game.status === "finished")
    return <p className="muted">The game is over. Use History to replay every phase, and Press to read everyone's messages.</p>;
  if (!me) return <p className="muted">You're watching this game.</p>;

  const byProv = new Map<string, string>();
  for (const o of orders) {
    const p = parseOrder(o);
    if (p.kind !== "WAIVE") byProv.set(prov(p.loc!), o);
  }
  const waives = orders.filter((o) => o === "WAIVE").length;
  const locs = Object.keys(po).sort();

  return (
    <div className="orders">
      <div className="orders-head">
        <PowerChip power={me} label={`${powerAdj(me)} orders`} />
        <span className="muted small">{saving ? "Saving…" : orders.length ? "Saved" : ""}</span>
      </div>

      {!iNeed && <p className="muted">You have nothing to order this phase{waiting.length ? " — waiting on the others." : "."}</p>}

      {iNeed && phaseType !== "A" && (
        <ul className="olist">
          {locs.map((loc) => {
            const o = byProv.get(prov(loc));
            const unit = (po[loc][0] ?? "").split(" ").slice(0, 2).join(" ");
            return (
              <li key={loc} className={o ? "" : "unset"}>
                <button className="olink" onClick={() => props.onSelect(loc)}>
                  {o ? describe(o) : `${unitLabel(unit)} — ${phaseType === "R" ? "disbands if not ordered" : "holds (no order)"}`}
                </button>
                {o && (
                  <button className="x" onClick={() => props.onClear(prov(loc))} aria-label="Clear order">
                    ×
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {iNeed && phaseType === "A" && (
        <div>
          <p>
            {buildCount > 0
              ? `You may build ${buildCount} unit${buildCount > 1 ? "s" : ""} in your vacant home centers.`
              : `You must disband ${-buildCount} unit${buildCount < -1 ? "s" : ""}. If you don't choose, the engine picks for you.`}
          </p>
          <ul className="olist">
            {orders
              .filter((o) => o !== "WAIVE")
              .map((o) => (
                <li key={o}>
                  <span className="olink">{describe(o)}</span>
                  <button className="x" onClick={() => props.onClear(prov(parseOrder(o).loc!))} aria-label="Clear order">
                    ×
                  </button>
                </li>
              ))}
            {Array.from({ length: waives }, (_, i) => (
              <li key={`w${i}`}>
                <span className="olink">Waived build</span>
                <button className="x" onClick={props.onUnwaive} aria-label="Undo waive">
                  ×
                </button>
              </li>
            ))}
          </ul>
          {buildCount > 0 && orders.length < buildCount && (
            <button className="btn small" onClick={props.onWaive}>
              Waive a build
            </button>
          )}
        </div>
      )}

      {iNeed && (
        <button className={`btn big ${game.ready ? "ready" : "primary"}`} onClick={props.onReady}>
          {game.ready ? "✓ Ready — tap to keep editing" : "I'm done — mark ready"}
        </button>
      )}
      <p className="muted small">
        {waiting.length
          ? `Waiting on ${waiting.map((w) => titleCase(w)).join(", ")}.`
          : game.ready || !iNeed
            ? "Everyone else is ready."
            : ""}{" "}
        The phase resolves when everyone is ready{game.deadline_at ? " or the clock runs out" : ""}.
      </p>

      <div className="draw">
        <button className={`btn small ${game.draw_vote ? "on" : "ghost"}`} onClick={props.onDraw}>
          {game.draw_vote ? "Withdraw draw vote" : "Vote for a draw"}
        </button>
        <span className="muted small">{game.players.filter((p) => p.draw_vote).length} voted</span>
      </div>

      <details className="help">
        <summary>How to give orders</summary>
        <ul>
          <li>Tap a unit, then a highlighted territory to <b>move</b>. Tap the unit again to <b>hold</b>.</li>
          <li><b>Support</b>: tap your unit → Support → the unit you're helping → where it's going (or the unit itself to support its hold).</li>
          <li><b>Convoy</b>: tap your fleet → Convoy → the army → its destination. Then order the army to move there.</li>
          <li>Keyboard: H hold · S support · C convoy · Esc cancel.</li>
        </ul>
      </details>
    </div>
  );
}
