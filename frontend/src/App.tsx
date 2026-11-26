import { useEffect, useState } from "react";
import { api } from "./api";
import { Toast } from "./components/bits";
import { startLive, stopLive } from "./live";
import AuthPage from "./pages/AuthPage";
import GamePage from "./pages/GamePage";
import Lobby from "./pages/Lobby";
import { MapDetail, MapGuide, MapUpload } from "./pages/MapPages";
import type { UserBrief } from "./types";

function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const f = () => setHash(location.hash);
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return hash;
}

function JoinPage({ code }: { code: string }) {
  const [info, setInfo] = useState<{ id: number; name: string; status: string; player_count: number; is_member: boolean; creator: UserBrief } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .get<typeof info>(`/games/code/${code}`)
      .then((i) => {
        if (i?.is_member) location.hash = `#/game/${i.id}`;
        else setInfo(i);
      })
      .catch((e) => setError(e.message));
  }, [code]);
  const join = async () => {
    try {
      const g = await api.post<{ id: number }>(`/games/code/${code}/join`);
      location.hash = `#/game/${g.id}`;
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="center-page">
      <div className="card narrow">
        {!info && !error && <p className="muted">Looking up game…</p>}
        {error && !info && (
          <>
            <h2>Can't join</h2>
            <p className="muted">{error}</p>
            <a className="btn" href="#/">
              Back to lobby
            </a>
          </>
        )}
        {info && (
          <>
            <p className="muted small">{info.creator.display_name} invited you to</p>
            <h2>{info.name}</h2>
            <p className="muted">{info.status === "forming" ? `${info.player_count} of 7 players have joined.` : "This game has already started."}</p>
            <div className="row gap">
              <a className="btn ghost" href="#/">
                Not now
              </a>
              {info.status === "forming" && (
                <button className="btn primary" onClick={join}>
                  Join game
                </button>
              )}
            </div>
          </>
        )}
      </div>
      <Toast text={error && info ? error : null} onClose={() => setError(null)} />
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState<UserBrief | null | undefined>(undefined);
  const hash = useHash();

  useEffect(() => {
    api
      .get<UserBrief>("/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  useEffect(() => {
    if (me) startLive();
    else stopLive();
  }, [me]);

  if (me === undefined) return <div className="center-page muted">Loading…</div>;

  const join = hash.match(/^#\/join\/([A-Za-z0-9]+)/);
  if (!me) return <AuthPage onAuthed={setMe} note={join ? "Sign in or create an account to join the game you were invited to." : undefined} />;

  const logout = async () => {
    await api.post("/auth/logout").catch(() => {});
    setMe(null);
    location.hash = "#/";
  };

  const game = hash.match(/^#\/game\/(\d+)/);
  if (game) return <GamePage key={game[1]} gameId={Number(game[1])} me={me} />;
  if (join) return <JoinPage code={join[1]} />;
  if (hash.startsWith("#/maps/new")) return <MapUpload />;
  if (hash.startsWith("#/maps/guide")) return <MapGuide />;
  const edit = hash.match(/^#\/maps\/([a-z0-9-]+)\/edit/);
  if (edit) return <MapUpload key={edit[1]} replace={edit[1]} />;
  const mapPage = hash.match(/^#\/maps\/([a-z0-9-]+)/);
  if (mapPage) return <MapDetail key={mapPage[1]} slug={mapPage[1]} me={me} />;
  const pane = hash.startsWith("#/variants") ? "variants" : hash.startsWith("#/review") && me.is_admin ? "review" : "classic";
  return <Lobby me={me} onLogout={logout} pane={pane} />;
}
