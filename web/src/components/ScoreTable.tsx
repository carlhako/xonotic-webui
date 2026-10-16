import type { MatchColumn, MatchTeam } from "../api/client";
import { formatDuration } from "../lib/time";
import { ColoredText } from "./ColoredText";

/** What the table needs of a player, whether the live board or a past match gave it. */
export interface ScoreTablePlayer {
  name: string;
  plain_name: string;
  bot: boolean;
  ping: number | null;
  time_s: number | null;
  team: number | null;
  values: Record<string, number>;
  /** `false` marks a player who was not playing when the match ended (past matches). */
  at_end?: boolean | null;
}

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

function PlayerRow<P extends ScoreTablePlayer>({
  rank,
  player,
  columns,
  onPlayer,
}: {
  rank: number;
  player: P;
  columns: MatchColumn[];
  onPlayer?: (player: P, opener: HTMLElement) => void;
}) {
  const name = (
    <span className="xon-text" title={player.plain_name}>
      <ColoredText text={player.name} />
    </span>
  );
  return (
    <tr className={player.at_end === false ? "not-at-end" : undefined}>
      <td className="num">{rank}</td>
      <td>
        {onPlayer ? (
          <button
            className="link-button"
            onClick={(e) => onPlayer(player, e.currentTarget)}
          >
            {name}
          </button>
        ) : (
          name
        )}
        {player.bot && <span className="badge badge-bot">bot</span>}
        {player.at_end === false && (
          <span className="badge badge-away" title="Not playing when the match ended">
            not at end
          </span>
        )}
      </td>
      {columns.map((c) => (
        <td key={c.key} className="num">
          {show(player.values[c.key])}
        </td>
      ))}
      <td className="num">{player.ping ?? "—"}</td>
      <td className="num">
        {player.time_s === null ? "—" : formatDuration(player.time_s)}
      </td>
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

/** The scoreboard table: the game's own columns and order, with team totals above each
 *  team's players in a team game. The live dashboard and a past match's dialog share it.
 *
 *  `onPlayer` turns each name into a button (the history dialog opens the player), and a
 *  player with `at_end === false` is marked "not at end". */
export function ScoreTable<P extends ScoreTablePlayer>({
  columns,
  players,
  teams,
  rowKey,
  onPlayer,
  label = "Scoreboard",
}: {
  columns: MatchColumn[];
  players: P[];
  teams: MatchTeam[];
  rowKey: (player: P, index: number) => string;
  onPlayer?: (player: P, opener: HTMLElement) => void;
  label?: string;
}) {
  // In a team game the players are grouped under their team's totals; a player the game
  // does not place on a listed team goes in a last, unnamed group.
  const groups: { team: MatchTeam | null; players: P[] }[] = [];
  if (teams.length > 0) {
    for (const team of teams) {
      groups.push({ team, players: players.filter((p) => p.team === team.team) });
    }
    const known = new Set(teams.map((t) => t.team));
    const rest = players.filter((p) => p.team === null || !known.has(p.team));
    if (rest.length > 0) groups.push({ team: null, players: rest });
  }

  const row = (p: P, i: number) => (
    <PlayerRow
      key={rowKey(p, i)}
      rank={i + 1}
      player={p}
      columns={columns}
      onPlayer={onPlayer}
    />
  );

  return (
    <div className="table-scroll">
      <table className="data-table" aria-label={label}>
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
              {g.players.map(row)}
            </tbody>
          ))
        ) : (
          <tbody>{players.map(row)}</tbody>
        )}
      </table>
    </div>
  );
}
