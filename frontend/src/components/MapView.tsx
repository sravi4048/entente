import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import { MapModel, mix, parseOrder, powerColor, prov } from "../orders";
import type { BoardState } from "../types";

const LAND = "#ece3cc";
const WATER = "#a9cbdf";
const BORDER = "#6f6552";

export interface DrawnOrder {
  raw: string;
  power: string;
  failed?: boolean;
  pending?: boolean;
}

export interface AdjacencyLine {
  a: string;
  b: string;
  type: "both" | "army" | "fleet";
}

interface Props {
  map: MapModel;
  board?: BoardState | null;
  orders?: DrawnOrder[];
  highlights?: Set<string>;
  selected?: string | null;
  onProvinceClick?: (province: string) => void;
  interactive?: boolean;
  compact?: boolean;
  adjacency?: AdjacencyLine[];
  showLabels?: boolean;
}

type View = { x: number; y: number; w: number; h: number };

function Icon({ type }: { type: string }) {
  if (type === "F")
    return (
      <g fill="#fff">
        <path d="M-11 2 H11 L7.5 8 H-7.5 Z" />
        <rect x="-1" y="-11" width="2.2" height="13" />
        <path d="M2 -10 L9.5 0 H2 Z" />
        <path d="M-1.5 -8 L-8.5 0 H-1.5 Z" opacity="0.85" />
      </g>
    );
  return (
    <g fill="#fff">
      <path d="M-10 -1.5 L7 -8.5 L9 -4 L-8 3 Z" />
      <circle cx="-3" cy="4.5" r="5" fill="none" stroke="#fff" strokeWidth="2.6" />
      <circle cx="-3" cy="4.5" r="1.4" />
      <rect x="-12" y="7.5" width="18" height="2.4" rx="1" />
    </g>
  );
}

function UnitToken({ x, y, type, power, k, dislodged, ghost }: { x: number; y: number; type: string; power: string; k: number; dislodged?: boolean; ghost?: boolean }) {
  const r = dislodged ? 20 : 27;
  return (
    <g transform={`translate(${x} ${y}) scale(${k})`} opacity={ghost ? 0.6 : 1}>
      <circle r={r + 1.5} cy={2.5} fill="#000" opacity={0.28} />
      <circle r={r} fill={powerColor(power)} stroke={dislodged ? "#e5322d" : "#fff"} strokeWidth={dislodged ? 3.5 : 2.6} strokeDasharray={ghost ? "5 4" : undefined} />
      <g transform={dislodged ? "scale(1.15)" : "scale(1.55)"}>
        <Icon type={type} />
      </g>
    </g>
  );
}

function shorten(a: [number, number], b: [number, number], startCut: number, endCut: number) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  return { x1: a[0] + ux * startCut, y1: a[1] + uy * startCut, x2: b[0] - ux * endCut, y2: b[1] - uy * endCut };
}

function curve(a: [number, number], b: [number, number], bend = 0.12) {
  const mx = (a[0] + b[0]) / 2;
  const my = (a[1] + b[1]) / 2;
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  return `M${a[0]} ${a[1]} Q${mx - dy * bend} ${my + dx * bend} ${b[0]} ${b[1]}`;
}

function Octagon({ x, y, r, color, k, dashed }: { x: number; y: number; r: number; color: string; k: number; dashed?: boolean }) {
  const pts = Array.from({ length: 8 }, (_, i) => {
    const a = (Math.PI / 8) * (2 * i + 1);
    return `${x + r * k * Math.cos(a)},${y + r * k * Math.sin(a)}`;
  }).join(" ");
  return (
    <g>
      <polygon points={pts} fill="none" stroke="#000" strokeOpacity={0.35} strokeWidth={9 * k} />
      <polygon points={pts} fill="none" stroke={color} strokeWidth={5 * k} strokeDasharray={dashed ? `${7 * k} ${6 * k}` : undefined} />
    </g>
  );
}

function FailMark({ at, k }: { at: [number, number]; k: number }) {
  const [x, y] = at;
  const s = 9 * k;
  return (
    <g stroke="#d7261e" strokeWidth={5 * k} strokeLinecap="round">
      <line x1={x - s} y1={y - s} x2={x + s} y2={y + s} />
      <line x1={x + s} y1={y - s} x2={x - s} y2={y + s} />
    </g>
  );
}

function OrderGlyph({ o, unitPos, map }: { o: DrawnOrder; unitPos: Map<string, [number, number]>; map: MapModel }) {
  const p = parseOrder(o.raw);
  const k = map.k;
  if (p.kind === "WAIVE" || !p.loc) return null;
  const color = powerColor(o.power);
  const here = unitPos.get(prov(p.loc)) ?? map.posOf(p.loc);
  const marker = `url(#arrow-${o.power})`;
  let body: ReactNode = null;

  if (p.kind === "M" || p.kind === "R") {
    const to = map.posOf(p.dest!);
    const l = shorten(here, to, 0, 16 * k);
    const d = curve([l.x1, l.y1], [l.x2, l.y2], 0.08);
    return (
      <g opacity={o.failed ? 0.5 : 1}>
        <path d={d} fill="none" stroke="#000" strokeOpacity={0.35} strokeWidth={10 * k} strokeLinecap="round" />
        <path d={d} fill="none" stroke={color} strokeWidth={6 * k} strokeLinecap="round" markerEnd={marker} strokeDasharray={p.kind === "R" ? `${12 * k} ${7 * k}` : undefined} />
        {o.failed && <FailMark at={[l.x2, l.y2]} k={k} />}
      </g>
    );
  }
  if (p.kind === "H") {
    return (
      <g opacity={o.failed ? 0.5 : 1}>
        <Octagon x={here[0]} y={here[1]} r={35} color={color} k={k} />
      </g>
    );
  }
  if (p.kind === "S" || p.kind === "C") {
    const tpos = unitPos.get(prov(p.targetLoc!)) ?? map.posOf(p.targetLoc!);
    if (!p.dest) {
      const l = shorten(here, tpos, 14 * k, 34 * k);
      body = (
        <>
          <line {...l} stroke="#000" strokeOpacity={0.3} strokeWidth={8 * k} />
          <line {...l} stroke={color} strokeWidth={5 * k} strokeDasharray={`${9 * k} ${7 * k}`} />
          <Octagon x={tpos[0]} y={tpos[1]} r={38} color={color} k={k} dashed />
        </>
      );
    } else {
      const dpos = map.posOf(p.dest);
      const tip: [number, number] = [tpos[0] + (dpos[0] - tpos[0]) * 0.6, tpos[1] + (dpos[1] - tpos[1]) * 0.6];
      const l = shorten(here, tip, 14 * k, 6 * k);
      const d = curve([l.x1, l.y1], [l.x2, l.y2], 0.18);
      body = (
        <>
          <path d={d} fill="none" stroke="#000" strokeOpacity={0.3} strokeWidth={8 * k} />
          <path d={d} fill="none" stroke={color} strokeWidth={5 * k} strokeDasharray={p.kind === "C" ? `${2 * k} ${8 * k}` : `${9 * k} ${7 * k}`} strokeLinecap="round" />
          {p.kind === "C" ? (
            <path d={`M${tip[0]} ${tip[1] - 11 * k} L${tip[0] + 10 * k} ${tip[1] + 7 * k} L${tip[0] - 10 * k} ${tip[1] + 7 * k} Z`} fill={color} stroke="#fff" strokeWidth={2 * k} />
          ) : (
            <circle cx={tip[0]} cy={tip[1]} r={7 * k} fill={color} stroke="#fff" strokeWidth={2 * k} />
          )}
        </>
      );
    }
    return (
      <g opacity={o.failed ? 0.5 : 1}>
        {body}
        {o.failed && <FailMark at={here} k={k} />}
      </g>
    );
  }
  if (p.kind === "D") {
    const [x, y] = here;
    const s = 20 * k;
    return (
      <g stroke="#e5322d" strokeWidth={6 * k} strokeLinecap="round">
        <line x1={x - s} y1={y - s} x2={x + s} y2={y + s} />
        <line x1={x + s} y1={y - s} x2={x - s} y2={y + s} />
      </g>
    );
  }
  if (p.kind === "B") {
    const at = map.posOf(p.loc);
    return <UnitToken x={at[0]} y={at[1]} type={p.utype!} power={o.power} k={k} ghost />;
  }
  return null;
}

const ADJ_STYLE: Record<string, { color: string; dash?: string }> = {
  both: { color: "#1d2230" },
  army: { color: "#8a5a16", dash: "6 5" },
  fleet: { color: "#1559b8", dash: "2 5" },
};

export default function MapView({ map, board, orders = [], highlights, selected, onProvinceClick, interactive = true, compact, adjacency, showLabels }: Props) {
  const geo = map.geo;
  const W = geo.width;
  const H = geo.height;
  const [OX, OY] = geo.offset ?? [0, 0];
  const k = map.k;
  const image = geo.style === "image" && geo.image;
  const FULL = useMemo<View>(() => ({ x: 0, y: 0, w: W, h: H }), [W, H]);
  const minW = Math.min(W, Math.max(W * 0.18, 320 * k));

  const svgRef = useRef<SVGSVGElement>(null);
  const [view, setView] = useState<View>(FULL);
  useEffect(() => setView(FULL), [FULL]);
  const drag = useRef<{ id: number; x: number; y: number; view: View; moved: boolean } | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number; view: View; mid: { x: number; y: number } } | null>(null);
  const movedRecently = useRef(false);

  const owner = useMemo(() => {
    const m: Record<string, string> = {};
    for (const [p, provs] of Object.entries(board?.influence ?? {})) for (const x of provs) m[prov(x)] = p;
    return m;
  }, [board]);

  const scOwner = useMemo(() => {
    const m: Record<string, string> = {};
    for (const [p, provs] of Object.entries(board?.centers ?? {})) for (const x of provs) m[prov(x)] = p;
    return m;
  }, [board]);

  const units = useMemo(() => {
    const out: { power: string; type: string; loc: string; dislodged: boolean }[] = [];
    for (const [power, list] of Object.entries(board?.units ?? {}))
      for (const u of list) {
        const dislodged = u.startsWith("*");
        const [type, loc] = u.replace("*", "").split(" ");
        out.push({ power, type, loc, dislodged });
      }
    return out;
  }, [board]);

  const unitPos = useMemo(() => {
    const m = new Map<string, [number, number]>();
    for (const u of units) if (!u.dislodged) m.set(prov(u.loc), map.posOf(u.loc));
    for (const u of units) if (u.dislodged) m.set(`*${prov(u.loc)}`, map.posOf(u.loc, true));
    return m;
  }, [units, map]);

  const orderPos = useMemo(() => {
    const m = new Map(unitPos);
    if (board?.phase?.endsWith("R")) for (const [key, v] of unitPos) if (key.startsWith("*")) m.set(key.slice(1), v);
    return m;
  }, [unitPos, board?.phase]);

  const toSvg = useCallback((cx: number, cy: number) => {
    const svg = svgRef.current!;
    const pt = svg.createSVGPoint();
    pt.x = cx;
    pt.y = cy;
    const r = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return { x: r.x, y: r.y };
  }, []);

  const clampView = useCallback(
    (v: View): View => {
      const w = Math.min(Math.max(v.w, minW), W);
      const h = (w / W) * H;
      const pad = W * 0.02;
      const x = Math.min(Math.max(v.x, -pad), W - w + pad);
      const y = Math.min(Math.max(v.y, -pad), H - h + pad);
      return { x, y, w, h };
    },
    [W, H, minW],
  );

  const zoomAt = useCallback(
    (factor: number, at?: { x: number; y: number }) => {
      setView((v) => {
        const c = at ?? { x: v.x + v.w / 2, y: v.y + v.h / 2 };
        const w = Math.min(Math.max(v.w * factor, minW), W);
        const s = w / v.w;
        return clampView({ x: c.x - (c.x - v.x) * s, y: c.y - (c.y - v.y) * s, w, h: v.h * s });
      });
    },
    [W, minW, clampView],
  );

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !interactive) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomAt(e.deltaY > 0 ? 1.15 : 1 / 1.15, toSvg(e.clientX, e.clientY));
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [interactive, toSvg, zoomAt]);

  const scaleNow = () => {
    const r = svgRef.current!.getBoundingClientRect();
    return Math.max(view.w / r.width, view.h / r.height);
  };

  const onPointerDown = (e: RPointerEvent) => {
    if (!interactive) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = { dist: Math.hypot(a.x - b.x, a.y - b.y), view, mid: toSvg((a.x + b.x) / 2, (a.y + b.y) / 2) };
      drag.current = null;
    } else {
      drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, view, moved: false };
    }
  };

  const onPointerMove = (e: RPointerEvent) => {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      const pv = pinch.current.view;
      const w = Math.min(Math.max(pv.w * (pinch.current.dist / d), minW), W);
      const s = w / pv.w;
      const c = pinch.current.mid;
      setView(clampView({ x: c.x - (c.x - pv.x) * s, y: c.y - (c.y - pv.y) * s, w, h: pv.h * s }));
      movedRecently.current = true;
      return;
    }
    const dr = drag.current;
    if (!dr || dr.id !== e.pointerId) return;
    const dx = e.clientX - dr.x;
    const dy = e.clientY - dr.y;
    if (!dr.moved && Math.hypot(dx, dy) < 6) return;
    if (!dr.moved) (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    dr.moved = true;
    movedRecently.current = true;
    const s = scaleNow();
    setView(clampView({ ...dr.view, x: dr.view.x - dx * s, y: dr.view.y - dy * s }));
  };

  const onPointerUp = (e: RPointerEvent) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    if (drag.current?.id === e.pointerId) drag.current = null;
    window.setTimeout(() => (movedRecently.current = false), 0);
  };

  const click = (p: string) => {
    if (movedRecently.current) return;
    onProvinceClick?.(p);
  };

  const zoomed = view.w < W - 1;
  const powersInPlay = useMemo(() => {
    const s = new Set<string>(geo.powers.map((p) => p.name));
    for (const p of Object.keys(board?.units ?? {})) s.add(p);
    for (const o of orders) s.add(o.power);
    return [...s];
  }, [geo.powers, board, orders]);
  const labels = showLabels ?? !image;
  const isWater = (t: string) => t === "water" || t === "sea";

  return (
    <div className={`mapwrap${compact ? " compact" : ""}`} style={compact ? { aspectRatio: `${W} / ${H}` } : undefined}>
      <svg
        ref={svgRef}
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        preserveAspectRatio="xMidYMid meet"
        className="map"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        style={{ touchAction: interactive ? "none" : "auto" }}
      >
        <defs>
          {powersInPlay.map((p) => (
            <marker key={p} id={`arrow-${p}`} viewBox="0 0 10 10" refX="5" refY="5" markerWidth="3.4" markerHeight="3.4" orient="auto-start-reverse">
              <path d="M0 0 L10 5 L0 10 Z" fill={powerColor(p)} stroke="#000" strokeOpacity={0.4} strokeWidth={0.8} />
            </marker>
          ))}
          <pattern id="impassable" width={14 * k} height={14 * k} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width={14 * k} height={14 * k} fill="#cfc6b0" fillOpacity={image ? 0.5 : 1} />
            <line x1="0" y1="0" x2="0" y2={14 * k} stroke="#8f846a" strokeOpacity={image ? 0.6 : 0.5} strokeWidth={6 * k} />
          </pattern>
        </defs>

        <rect x={-W} y={-H} width={W * 3} height={H * 3} fill={WATER} />
        {image && <image href={geo.image} x={0} y={0} width={W} height={H} preserveAspectRatio="none" />}
        <g transform={`translate(${OX} ${OY})`}>
          {geo.decor.map((d, i) => (
            <path
              key={i}
              d={d.d}
              fill={d.kind === "impassable" ? "url(#impassable)" : image ? "none" : d.kind === "water" ? WATER : d.fill ?? "#d9d2c0"}
              stroke={image || d.kind === "water" ? "none" : BORDER}
              strokeWidth={1.2 * k}
            />
          ))}
          {Object.entries(geo.provinces).map(([id, p]) => {
            const o = owner[id];
            const water = isWater(p.type);
            if (image)
              return <path key={id} d={p.d} fill={o && !water ? powerColor(o) : "none"} fillOpacity={0.42} stroke="none" />;
            const fill = water ? WATER : o ? mix(powerColor(o), LAND, 0.55) : LAND;
            return <path key={id} d={p.d} fill={fill} stroke={water ? "#7fa9c2" : BORDER} strokeWidth={(water ? 1.2 : 1.6) * k} strokeLinejoin="round" />;
          })}
          {highlights &&
            [...highlights].map((id) => (geo.provinces[id] ? <path key={`hl-${id}`} d={geo.provinces[id].d} className="hl" strokeWidth={4 * k} /> : null))}
          {selected && geo.provinces[selected] && <path d={geo.provinces[selected].d} className="sel" strokeWidth={4 * k} />}
        </g>

        {labels && (
          <g className="labels" pointerEvents="none">
            {geo.labels.map((l, i) => (
              <text
                key={i}
                x={l.x}
                y={l.y}
                transform={l.r ? `rotate(${l.r} ${l.x} ${l.y})` : undefined}
                className={l.w ? "lbl water" : "lbl"}
                fontSize={(l.s ? 15 : 18) * k}
                strokeWidth={3 * k}
              >
                {l.t}
              </text>
            ))}
          </g>
        )}

        <g pointerEvents="none">
          {Object.entries(geo.provinces).map(([id, p]) =>
            p.sc && p.scpos ? (
              <g key={id} transform={`translate(${p.scpos[0]} ${p.scpos[1]}) scale(${k})`}>
                <circle r={9.5} fill={scOwner[id] ? powerColor(scOwner[id]) : "#f6f1e6"} stroke="#2b2620" strokeWidth={2.2} />
                <circle r={4} fill="none" stroke={scOwner[id] ? "#fff" : "#2b2620"} strokeWidth={1.6} />
              </g>
            ) : null,
          )}
        </g>

        {adjacency && (
          <g pointerEvents="none" opacity={0.85}>
            {adjacency.map((a, i) => {
              const [x1, y1] = map.posOf(a.a);
              const [x2, y2] = map.posOf(a.b);
              const st = ADJ_STYLE[a.type] ?? ADJ_STYLE.both;
              return (
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={st.color} strokeWidth={2.4 * k} strokeDasharray={st.dash?.split(" ").map((n) => Number(n) * k).join(" ")} strokeLinecap="round">
                  <title>{`${a.a} — ${a.b}: ${a.type}`}</title>
                </line>
              );
            })}
            {Object.entries(geo.provinces).map(([id, p]) => (
              <circle key={id} cx={p.unit[0]} cy={p.unit[1]} r={5 * k} fill="#fff" stroke="#1d2230" strokeWidth={1.5 * k} />
            ))}
            {Object.entries(geo.coasts).map(([id, c]) => (
              <circle key={id} cx={c.unit[0]} cy={c.unit[1]} r={4 * k} fill="#1559b8" stroke="#fff" strokeWidth={1.2 * k} />
            ))}
          </g>
        )}

        <g pointerEvents="none">
          {orders.map((o, i) => (
            <OrderGlyph key={`${o.raw}-${i}`} o={o} unitPos={orderPos} map={map} />
          ))}
        </g>

        <g pointerEvents="none">
          {selected && orderPos.get(selected) && <circle cx={orderPos.get(selected)![0]} cy={orderPos.get(selected)![1]} r={36 * k} className="selring" strokeWidth={6 * k} />}
          {units
            .filter((u) => !u.dislodged)
            .map((u) => {
              const [x, y] = map.posOf(u.loc);
              return <UnitToken key={`${u.power}-${u.loc}`} x={x} y={y} type={u.type} power={u.power} k={k} />;
            })}
          {units
            .filter((u) => u.dislodged)
            .map((u) => {
              const [x, y] = map.posOf(u.loc, true);
              return <UnitToken key={`d-${u.power}-${u.loc}`} x={x} y={y} type={u.type} power={u.power} k={k} dislodged />;
            })}
        </g>

        {onProvinceClick && (
          <g transform={`translate(${OX} ${OY})`}>
            {Object.entries(geo.provinces).map(([id, p]) => (
              <path key={id} d={p.d} fill="transparent" className="hit" onClick={() => click(id)}>
                <title>{p.name}</title>
              </path>
            ))}
          </g>
        )}
      </svg>
      {interactive && (
        <div className="zoomctl">
          <button onClick={() => zoomAt(1 / 1.3)} aria-label="Zoom in">
            +
          </button>
          <button onClick={() => zoomAt(1.3)} aria-label="Zoom out">
            −
          </button>
          {zoomed && (
            <button onClick={() => setView(FULL)} aria-label="Reset zoom" className="reset">
              ⤢
            </button>
          )}
        </div>
      )}
    </div>
  );
}
