import { useEffect, useState } from "react";
import { api } from "../api";
import type { UserBrief } from "../types";
import { Logo } from "./Lobby";

export default function AuthPage({ onAuthed, note }: { onAuthed: (u: UserBrief) => void; note?: string }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  useEffect(() => {
    api.get<{ signup_code_required: boolean }>("/config").then((c) => setNeedsCode(c.signup_code_required)).catch(() => {});
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const u =
        mode === "login"
          ? await api.post<UserBrief>("/auth/login", { username, password })
          : await api.post<UserBrief>("/auth/register", { username, password, display_name: displayName || undefined, invite_code: inviteCode || undefined });
      onAuthed(u);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <div className="auth-art" aria-hidden>
        <div className="auth-brand">
          <Logo /> Entente
        </div>
        <h1>Diplomacy with your friends.</h1>
        <p>Seven powers. One continent. Negotiate in private, write your orders, and find out who meant it.</p>
      </div>
      <form
        className="card auth-card"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <h2>{mode === "login" ? "Sign in" : "Create an account"}</h2>
        {note && <p className="muted small">{note}</p>}
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoCapitalize="none" autoComplete="username" required />
        </label>
        {mode === "register" && needsCode && (
          <label>
            Sign-up code <small className="muted">(from whoever invited you)</small>
            <input value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} autoCapitalize="none" required />
          </label>
        )}
        {mode === "register" && (
          <label>
            Display name <small className="muted">(optional)</small>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={64} />
          </label>
        )}
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={mode === "register" ? 8 : undefined}
            required
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="btn primary big" disabled={busy}>
          {mode === "login" ? "Sign in" : "Create account"}
        </button>
        <p className="muted small center">
          {mode === "login" ? "New here? " : "Already have an account? "}
          <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Create an account" : "Sign in"}
          </button>
        </p>
      </form>
    </div>
  );
}
