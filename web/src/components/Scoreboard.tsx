import type { Match, MatchColumn, MatchPlayer, MatchTeam } from "../api/client";
import { formatDuration } from "../lib/time";
import { ColoredText } from "./ColoredText";

type Board = Match["scoreboard"];

// Values are shown as whole numbers: the game's damage columns are fractional.
function show(value: number | undefined): string {
  if (value === undefined) return "0";
  return String(Math.round(value));
}

const TEAM_NAMES: Record<string, string> = {
  red: "Red",
  blue: "Blue",
  yellow: "Yellow",
  pink: "Pink",
};

function PlayerRow({
  rank,
  player,
  columns,
}: {
  rank: number;
  player: MatchPlayer;
  columns: MatchColumn[];
}) {
  return (
    <tr>
      <td className="num">{rank}</td>
      <td>
        <span className="xon-text" title={player.plain_name}>
          <ColoredText text={player.name} />
        </span>
        {player.bot && <span className="badge badge-bot">bot</span>}
      </td>
      {columns.map((c) => (
        <td key={c.key} className="num">
          {show(player.values[c.key])}
        </td>
      ))}
      <td className="num">{player.ping ?? "—"}</td>
      <td className="num">{formatDuration(player.time_s)}</td>
    </tr>
  );
}

function TeamRow({
  team,
  columns,
  members,
}: {
  team: MatchTeam | null;
  columns: MatchColumn[];
  members: number;
}) {
  const color = team?.color ?? "none";
  const label = team ? (TEAM_NAMES[color] ?? `Team ${team.team}`) : "No team";
  return (
    <tr className={`team-row team-${color}`}>
      <th scope="row" colSpan={2}>
        {label} <span className="muted">· {members}</span>
      </th>
      {columns.map((c) => (
        <td key={c.key} className="num">
          {team && c.key in team.values ? show(team.values[c.key]) : ""}
        </td>
      ))}
      <td />
      <td />
    </tr>
  );
}

/** The live scoreboard: the game's own columns and order, with team totals above each
 *  team's players in a team game and the spectators on a muted line underneath. */
export function Scoreboard({ board, stale }: { board: Board; stale: boolean }) {
  const { columns, players, spectators, teams } = board;

  // In a team game the players are grouped under their team's totals; a player the game
  // does not place on a listed team goes in a last, unnamed group.
  const groups: { team: MatchTeam | null; players: MatchPlayer[] }[] = [];
  if (teams.length > 0) {
    for (const team of teams) {
      groups.push({ team, players: players.filter((p) => p.team === team.team) });
    }
    const known = new Set(teams.map((t) => t.team));
    const rest = players.filter((p) => p.team === null || !known.has(p.team));
    if (rest.length > 0) groups.push({ team: null, players: rest });
  }

  return (
    <div className={`panel scoreboard${stale ? " is-stale" : ""}`}>
      <h2>Scoreboard</h2>
      {players.length === 0 && spectators.length === 0 ? (
        <p className="muted">No one is connected.</p>
      ) : (
        <div className="table-scroll">
          <table className="data-table" aria-label="Scoreboard">
            <thead>
              <tr>
                <th scope="col" className="num">
                  #
                </th>
                <th scope="col">Player</th>
                {columns.map((c) => (
                  <th key={c.key} scope="col" className="num" title={c.label}>
                    {c.label}
                  </th>
                ))}
                <th scope="col" className="num">
                  Ping
                </th>
                <th scope="col" className="num">
                  Time
                </th>
              </tr>
            </thead>
            {teams.length > 0 ? (
              groups.map((g) => (
                <tbody key={g.team?.team ?? "none"}>
                  <TeamRow team={g.team} columns={columns} members={g.players.length} />
                  {g.players.map((p, i) => (
                    <PlayerRow
                      key={`${p.ent}-${p.plain_name}`}
                      rank={i + 1}
                      player={p}
                      columns={columns}
                    />
                  ))}
                </tbody>
              ))
            ) : (
              <tbody>
                {players.map((p, i) => (
                  <PlayerRow
                    key={`${p.ent}-${p.plain_name}`}
                    rank={i + 1}
                    player={p}
                    columns={columns}
                  />
                ))}
              </tbody>
            )}
          </table>
        </div>
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
