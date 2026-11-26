import type { BoardState, GameDetail } from "../types";
import { PowerChip } from "./bits";

export default function PowersPanel({ game, board }: { game: GameDetail; board: BoardState }) {
  const rows = game.powers.map((p) => {
    const player = game.players.find((x) => x.power === p);
    const centers = board.centers[p]?.length ?? 0;
    const units = board.units[p]?.length ?? 0;
    const out = board.eliminated?.includes(p) ?? (centers === 0 && units === 0);
    const delta = board.phase.endsWith("A") ? board.builds?.[p]?.count ?? 0 : 0;
    let status = "—";
    if (out) status = "Eliminated";
    else if (!player) status = "Civil disorder";
    else if (game.status !== "active") status = "";
    else if (!player.needs_orders) status = "Nothing to do";
    else if (player.ready) status = "✓ Ready";
    else if (player.has_orders) status = "Orders in";
    else status = "Thinking…";
    return { p, player, centers, units, out, delta, status };
  }).sort((a, b) => b.centers - a.centers || a.p.localeCompare(b.p));

  return (
    <div className="powers">
      <table>
        <thead>
          <tr>
            <th>Power</th>
            <th>Player</th>
            <th title="Supply centers">SC</th>
            <th>Units</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.p} className={r.out ? "out" : r.p === game.my_power ? "me" : ""}>
              <td>
                <PowerChip power={r.p} />
              </td>
              <td>
                {r.player ? (
                  <>
                    <span className={`presence${r.player.online ? " on" : ""}`} />
                    {r.player.display_name}
                    {r.player.draw_vote && game.status === "active" && <span className="tag">draw</span>}
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="num">
                {r.centers}
                {r.delta !== 0 && <span className={r.delta > 0 ? "plus" : "minus"}>{r.delta > 0 ? `+${r.delta}` : r.delta}</span>}
              </td>
              <td className="num">{r.units}</td>
              <td className={`status ${r.status.startsWith("✓") ? "ok" : ""}`}>{r.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">{board.victory ?? game.variant?.victory ?? 18} supply centers wins. A draw ends the game when every surviving player votes for it.</p>
    </div>
  );
}
