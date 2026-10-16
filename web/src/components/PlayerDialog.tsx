import { api } from "../api/client";
import type { PlayerDetail } from "../api/client";
import { useResource } from "../api/useResource";
import { formatDuration, formatEpoch } from "../lib/time";
import { ColoredText } from "./ColoredText";
import { Dialog } from "./Dialog";
import { MatchesLink } from "./MatchDialog";

const percent = (value: number | null) =>
  value === null ? "–" : `${(value * 100).toFixed(1)}%`;
const number = (value: number) =>
  Number.isInteger(value) ? String(value) : value.toFixed(1);

function Details({ player, onClose }: { player: PlayerDetail; onClose: () => void }) {
  const aliases = player.aliases.filter((a) => a.name !== player.name);
  return (
    <>
      <dl className="detail-grid">
        <dt>Names used</dt>
        <dd>
          <span className="xon-text">
            <ColoredText text={player.name} />
          </span>
          {aliases.map((a) => (
            <span key={a.name} className="xon-text alias">
              <ColoredText text={a.name} />
            </span>
          ))}
        </dd>
        <dt>Key</dt>
        <dd className="mono">
          {player.key_prefix ? `${player.key_prefix}…` : "none (by name)"}
        </dd>
        <dt>First seen</dt>
        <dd>{formatEpoch(player.first_seen)}</dd>
        <dt>Last seen</dt>
        <dd>{formatEpoch(player.last_seen)}</dd>
        <dt>Sessions</dt>
        <dd>{player.sessions}</dd>
        <dt>Time on server</dt>
        <dd>{formatDuration(player.time_on_server)}</dd>
        <dt>Time playing</dt>
        <dd>{formatDuration(player.time_playing)}</dd>
        <dt>Frags</dt>
        <dd>{player.frags}</dd>
        <dt>Deaths</dt>
        <dd>{player.deaths}</dd>
        <dt>K/D</dt>
        <dd>{player.kd.toFixed(2)}</dd>
        <dt>Suicides</dt>
        <dd>{player.suicides}</dd>
        <dt>Team kills</dt>
        <dd>{player.teamkills}</dd>
        <dt>Score</dt>
        <dd>{number(player.score)}</dd>
        <dt>Matches played</dt>
        <dd>{player.matches}</dd>
        <dt>Wins</dt>
        <dd>{player.wins}</dd>
        <dt>Accuracy</dt>
        <dd>{percent(player.accuracy)}</dd>
        <dt>Damage dealt</dt>
        <dd>{Math.round(player.damage_dealt)}</dd>
        <dt>Damage taken</dt>
        <dd>{Math.round(player.damage_taken)}</dd>
        <dt>Average ping</dt>
        <dd>
          {player.avg_latency === null ? "–" : `${Math.round(player.avg_latency)} ms`}
        </dd>
      </dl>

      <p className="dialog-actions">
        <MatchesLink playerId={player.id} onClick={onClose} />
      </p>

      {!player.has_match_stats && (
        <p className="muted">
          No match statistics recorded yet. Time on server and the live counts above are
          kept; weapons, damage and accuracy appear after a match this player took part in
          ends.
        </p>
      )}

      {player.weapons.length > 0 && (
        <>
          <h3>Weapons</h3>
          <div className="table-scroll">
            <table className="data-table compact" aria-label="Weapons">
              <thead>
                <tr>
                  <th scope="col">Weapon</th>
                  <th scope="col" className="num">
                    Frags
                  </th>
                  <th scope="col" className="num">
                    Accuracy
                  </th>
                </tr>
              </thead>
              <tbody>
                {player.weapons.map((w) => (
                  <tr key={w.weapon}>
                    <td>{w.weapon}</td>
                    <td className="num">{number(w.frags)}</td>
                    <td className="num">{percent(w.accuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {player.achievements.length > 0 && (
        <>
          <h3>Achievements</h3>
          <ul className="badge-list">
            {player.achievements.map((a) => (
              <li key={a.name} className="badge">
                {a.name} ×{a.count}
              </li>
            ))}
          </ul>
        </>
      )}

      {player.extra.length > 0 && (
        <>
          <h3>Gametype statistics</h3>
          <dl className="detail-grid">
            {player.extra.map((e) => (
              <div className="detail-pair" key={e.name}>
                <dt>{e.name}</dt>
                <dd>{number(e.value)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </>
  );
}

/** Everything held for one player, in a dialog that closes with its button, Escape or a
 *  click on the backdrop. */
export function PlayerDialog({
  id,
  name,
  returnFocusTo,
  onClose,
}: {
  id: number;
  name: string;
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
}) {
  const { data, error, loading } = useResource(() => api.player(id), [id]);
  return (
    <Dialog
      title={
        <span className="xon-text">
          <ColoredText text={data?.name ?? name} />
        </span>
      }
      returnFocusTo={returnFocusTo}
      onClose={onClose}
    >
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!data && !error && loading && <p className="muted">Loading…</p>}
      {data && <Details player={data} onClose={onClose} />}
    </Dialog>
  );
}
