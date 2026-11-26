import { useEffect, useState } from "react";
import { powerColor, titleCase } from "../orders";

export function PowerChip({ power, label }: { power: string; label?: string }) {
  return (
    <span className="chip">
      <span className="dot" style={{ background: powerColor(power) }} />
      {label ?? titleCase(power)}
    </span>
  );
}

export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function formatRemaining(ms: number): string {
  if (ms <= 0) return "processing…";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec.toString().padStart(2, "0")}s`;
  return `${sec}s`;
}

export function Countdown({ deadline, skew = 0 }: { deadline: string | null; skew?: number }) {
  const now = useNow();
  if (!deadline) return <span className="countdown muted">No deadline · advances when all are ready</span>;
  const ms = new Date(deadline).getTime() - (now + skew);
  return <span className={`countdown${ms < 5 * 60000 ? " urgent" : ""}`}>⏱ {formatRemaining(ms)}</span>;
}

export function Toast({ text, onClose }: { text: string | null; onClose: () => void }) {
  useEffect(() => {
    if (!text) return;
    const t = window.setTimeout(onClose, 4500);
    return () => window.clearTimeout(t);
  }, [text, onClose]);
  if (!text) return null;
  return (
    <div className="toast" role="alert" onClick={onClose}>
      {text}
    </div>
  );
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}
