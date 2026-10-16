import type { Match } from "../api/client";
import { ColoredText } from "./ColoredText";
import { ScoreTable } from "./ScoreTable";

type Board = Match["scoreboard"];

/** The live scoreboard: the game's own columns and order, with team totals above each
 *  team's players in a team game and the spectators on a muted line underneath. */
export function Scoreboard({ board, stale }: { board: Board; stale: boolean }) {
  const { columns, players, spectators, teams } = board;

  return (
    <div className={`panel scoreboard${stale ? " is-stale" : ""}`}>
      <h2>Scoreboard</h2>
      {players.length === 0 && spectators.length === 0 ? (
        <p className="muted">No one is connected.</p>
      ) : (
        <ScoreTable
          columns={columns}
          players={players}
          teams={teams}
          rowKey={(p) => `${p.ent}-${p.plain_name}`}
        />
      )}
      {spectators.length > 0 && (
        <p className="muted scoreboard-spectators">
          Spectators:{" "}
          {spectators.map((s, i) => (
            <span key={`${s.ent}-${s.plain_name}`}>
              {i > 0 && ", "}
              <span className="xon-text" title={s.plain_name}>
                <ColoredText text={s.name} />
              </span>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
