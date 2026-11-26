import { useEffect, useState } from "react";
import { api } from "./api";

// ------------------------------------------------------------ map geometry

export interface ProvinceInfo {
  name: string;
  type: "land" | "coast" | "water" | "sea" | "shut";
  sc: boolean;
  d: string;
  unit: [number, number];
  disl: [number, number];
  scpos?: [number, number];
}

export interface PowerMeta {
  name: string;
  adjective: string;
  color: string;
}

export interface MapData {
  width: number;
  height: number;
  offset?: [number, number];
  scale?: number;
  style?: "flat" | "image";
  image?: string;
  provinces: Record<string, ProvinceInfo>;
  coasts: Record<string, { unit: [number, number]; disl: [number, number] }>;
  decor: { kind?: string; d: string; id?: string; fill?: string }[];
  labels: { t: string; x: number; y: number; r: number; s: boolean; w: boolean }[];
  powers: PowerMeta[];
}

// ------------------------------------------------------- power colors/names

const FALLBACK = ["#c8453c", "#33509f", "#4b9be0", "#5e544a", "#3f9a55", "#8b5dc4", "#dfae35", "#e07b39", "#2fa3a0", "#d0607a"];
const powerMeta: Record<string, PowerMeta> = {
  AUSTRIA: { name: "AUSTRIA", adjective: "Austrian", color: "#c8453c" },
  ENGLAND: { name: "ENGLAND", adjective: "English", color: "#33509f" },
  FRANCE: { name: "FRANCE", adjective: "French", color: "#4b9be0" },
  GERMANY: { name: "GERMANY", adjective: "German", color: "#5e544a" },
  ITALY: { name: "ITALY", adjective: "Italian", color: "#3f9a55" },
  RUSSIA: { name: "RUSSIA", adjective: "Russian", color: "#8b5dc4" },
  TURKEY: { name: "TURKEY", adjective: "Turkish", color: "#dfae35" },
};

/** Remember the colors of powers we've seen (variants reuse names like FRANCE with other colors). */
export function registerPowers(list: PowerMeta[] | undefined, override = true) {
  for (const p of list ?? []) if (override || !powerMeta[p.name]) powerMeta[p.name] = p;
}

export function powerColor(p: string): string {
  if (powerMeta[p]) return powerMeta[p].color;
  let h = 0;
  for (const ch of p) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return FALLBACK[h % FALLBACK.length];
}

export const titleCase = (s: string) =>
  s
    .toLowerCase()
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

export const powerAdj = (p: string) => powerMeta[p]?.adjective ?? titleCase(p);

// ----------------------------------------------------------- a loaded map

export class MapModel {
  geo: MapData;
  k: number;
  constructor(geo: MapData) {
    this.geo = geo;
    this.k = geo.scale ?? 1;
    registerPowers(geo.powers);
  }
  prov = (loc: string) => loc.split("/")[0].toUpperCase();
  locName = (loc: string): string => {
    const [p, coast] = loc.split("/");
    const name = this.geo.provinces[p.toUpperCase()]?.name ?? p;
    if (!coast) return name;
    const c = coast.toLowerCase();
    const word = c === "nc" ? "north" : c === "sc" ? "south" : c === "ec" ? "east" : c === "wc" ? "west" : c.toUpperCase();
    return `${name} (${word} coast)`;
  };
  posOf = (loc: string, dislodged = false): [number, number] => {
    const key = loc.toUpperCase();
    const c = this.geo.coasts[key];
    if (c) return dislodged ? c.disl : c.unit;
    const p = this.geo.provinces[this.prov(key)];
    if (!p) return [0, 0];
    return dislodged ? p.disl : p.unit;
  };
  unitLabel = (unit: string): string => {
    const [t, loc] = unit.replace("*", "").split(" ");
    return `${t === "F" ? "Fleet" : "Army"} ${this.locName(loc)}`;
  };
  describe = (raw: string): string => describeOrder(raw, this.locName);
}

const mapCache = new Map<string, Promise<MapModel>>();

export function loadMap(url: string): Promise<MapModel> {
  if (!mapCache.has(url)) {
    const p = api.get<MapData>(url).then((g) => new MapModel(g));
    p.catch(() => mapCache.delete(url));
    mapCache.set(url, p);
  }
  return mapCache.get(url)!;
}

export function useMap(url: string | null): MapModel | null {
  const [m, setM] = useState<MapModel | null>(null);
  useEffect(() => {
    let live = true;
    setM(null);
    if (url) loadMap(url).then((x) => live && setM(x)).catch(() => {});
    return () => {
      live = false;
    };
  }, [url]);
  return m;
}

export const prov = (loc: string) => loc.split("/")[0].toUpperCase();

// ----------------------------------------------------------------- orders

export type OrderKind = "H" | "M" | "S" | "C" | "R" | "D" | "B" | "WAIVE";

export interface ParsedOrder {
  raw: string;
  kind: OrderKind;
  utype?: "A" | "F";
  loc?: string;
  unit?: string;
  target?: string;
  targetLoc?: string;
  dest?: string;
  via?: boolean;
}

export function parseOrder(raw: string): ParsedOrder {
  const t = raw.trim().toUpperCase().split(/\s+/);
  if (t[0] === "WAIVE") return { raw, kind: "WAIVE" };
  const base = { raw, utype: t[0] as "A" | "F", loc: t[1], unit: `${t[0]} ${t[1]}` };
  switch (t[2]) {
    case "H":
      return { ...base, kind: "H" };
    case "-":
      return { ...base, kind: "M", dest: t[3], via: t[4] === "VIA" };
    case "S":
      return { ...base, kind: "S", target: `${t[3]} ${t[4]}`, targetLoc: t[4], dest: t[5] === "-" ? t[6] : undefined };
    case "C":
      return { ...base, kind: "C", target: `${t[3]} ${t[4]}`, targetLoc: t[4], dest: t[6] };
    case "R":
      return { ...base, kind: "R", dest: t[3] };
    case "D":
      return { ...base, kind: "D" };
    case "B":
      return { ...base, kind: "B" };
    default:
      return { ...base, kind: "H" };
  }
}

export function describeOrder(raw: string, locName: (l: string) => string = (l) => l): string {
  const o = parseOrder(raw);
  const at = o.loc ? locName(o.loc) : "";
  const unitWord = o.utype === "F" ? "fleet" : "army";
  switch (o.kind) {
    case "WAIVE":
      return "Waive a build";
    case "H":
      return `${at} holds`;
    case "M":
      return `${at} → ${locName(o.dest!)}${o.via ? " (by convoy)" : ""}`;
    case "S":
      return o.dest ? `${at} supports ${locName(o.targetLoc!)} → ${locName(o.dest)}` : `${at} supports ${locName(o.targetLoc!)} to hold`;
    case "C":
      return `${at} convoys ${locName(o.targetLoc!)} → ${locName(o.dest!)}`;
    case "R":
      return `${at} retreats → ${locName(o.dest!)}`;
    case "D":
      return `Disband ${unitWord} in ${at}`;
    case "B":
      return `Build ${unitWord} in ${at}`;
  }
}

export function mix(hex: string, base: string, amount: number): string {
  const h = (s: string) => [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16));
  const a = h(hex);
  const b = h(base);
  const c = a.map((v, i) => Math.round(v * amount + b[i] * (1 - amount)));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

export function deadlineLabel(minutes: number | null): string {
  if (!minutes) return "No deadline";
  if (minutes < 60) return `${minutes} min phases`;
  if (minutes < 1440) return `${minutes / 60} hr phases`;
  return `${minutes / 1440} day phases`;
}
