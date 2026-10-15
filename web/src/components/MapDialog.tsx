import { ApiCallError, api } from "../api/client";
import type { MapInfo, MapStats } from "../api/client";
import { useResource } from "../api/useResource";
import { formatTotal } from "../lib/mapTotals";
import { formatEpoch } from "../lib/time";
import { ColoredText } from "./ColoredText";
import { Dialog } from "./Dialog";

const UNAVAILABLE = "unavailable";

function Details({
  stats,
  onOpenPlayer,
}: {
  stats: MapStats;
  onOpenPlayer: (id: number, name: string) => void;
}) {
  if (stats.played === 0 && stats.cut_short === 0 && stats.frags === 0) {
    return <p className="muted">This map has not been played yet.</p>;
  }
  return (
    <>
      <dl className="detail-grid">
        <dt>Matches played</dt>
        <dd>{formatTotal(stats.played)}</dd>
        <dt>Cut short</dt>
        <dd>{formatTotal(stats.cut_short)}</dd>
        <dt>Frags</dt>
        <dd>{formatTotal(stats.frags)}</dd>
        <dt>First played</dt>
        <dd>{stats.first_played === null ? "–" : formatEpoch(stats.first_played)}</dd>
        <dt>Last played</dt>
        <dd>{stats.last_played === null ? "–" : formatEpoch(stats.last_played)}</dd>
      </dl>

      {stats.gametypes.length > 0 && (
        <>
          <h3>By gametype</h3>
          <div className="table-scroll">
            <table className="data-table compact" aria-label="Matches per gametype">
              <thead>
                <tr>
                  <th scope="col">Gametype</th>
                  <th scope="col" className="num">
                    Matches
                  </th>
                </tr>
              </thead>
              <tbody>
                {stats.gametypes.map((g) => (
                  <tr key={g.gametype}>
                    <td>{g.gametype}</td>
                    <td className="num">{formatTotal(g.played)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {stats.top_fraggers.length > 0 && (
        <>
          <h3>Top fraggers</h3>
          <div className="table-scroll">
            <table className="data-table compact" aria-label="Top fraggers">
              <thead>
                <tr>
                  <th scope="col">Player</th>
                  <th scope="col" className="num">
                    Frags
                  </th>
                </tr>
              </thead>
              <tbody>
                {stats.top_fraggers.map((f) => (
                  <tr key={f.player_id}>
                    <td>
                      <button
                        className="link-button"
                        onClick={() => onOpenPlayer(f.player_id, f.name)}
                      >
                        <span className="xon-text">
                          <ColoredText text={f.name} />
                        </span>
                      </button>
                      {f.is_bot && (
                        <span className="badge badge-bot" title="a bot">
                          bot
                        </span>
                      )}
                    </td>
                    <td className="num">{formatTotal(f.frags)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

/** How one map has been played, in a dialog; a top fragger opens that player. */
export function MapDialog({
  map,
  returnFocusTo,
  onClose,
  onOpenPlayer,
}: {
  map: MapInfo;
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
  onOpenPlayer: (id: number, name: string) => void;
}) {
  const { data, error, loading } = useResource<MapStats | typeof UNAVAILABLE>(
    () =>
      api.mapStats(map.name).catch((e: unknown) => {
        if (e instanceof ApiCallError && e.code === "players_unavailable") {
          return UNAVAILABLE;
        }
        throw e;
      }),
    [map.name],
  );
  return (
    <Dialog title={map.title} returnFocusTo={returnFocusTo} onClose={onClose}>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!data && !error && loading && <p className="muted">Loading…</p>}
      {data === UNAVAILABLE && (
        <p className="muted">Player history is not being recorded.</p>
      )}
      {data && data !== UNAVAILABLE && (
        <Details stats={data} onOpenPlayer={onOpenPlayer} />
      )}
    </Dialog>
  );
}
