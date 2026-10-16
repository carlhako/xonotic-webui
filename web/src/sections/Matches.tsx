import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { MatchSummary } from "../api/client";
import { useMatches } from "../api/useMatches";
import { useResource } from "../api/useResource";
import { ColoredText } from "../components/ColoredText";
import { MatchDialog } from "../components/MatchDialog";
import { Outcome, Players, VsBots, Winner } from "../components/matchParts";
import { PlayerDialog } from "../components/PlayerDialog";
import { formatDuration, formatEpoch } from "../lib/time";

const PAGE_SIZE = 50;
const UNKNOWN = "unknown";

type Dialog =
  | { kind: "match"; id: number; opener: HTMLElement | null }
  | { kind: "player"; id: number; name: string; opener: HTMLElement | null };

/** The name of the player the list is filtered to, as a removable chip. */
function PlayerChip({ id, onRemove }: { id: number; onRemove: () => void }) {
  const { data } = useResource(() => api.player(id), [id]);
  return (
    <span className="chip">
      <span>Player: </span>
      {data ? (
        <span className="xon-text">
          <ColoredText text={data.name} />
        </span>
      ) : (
        <span>#{id}</span>
      )}
      <button
        className="chip-remove"
        aria-label="Remove the player filter"
        onClick={onRemove}
      >
        ×
      </button>
    </span>
  );
}

export function Matches() {
  const [params, setParams] = useSearchParams();
  const map = params.get("map") ?? "";
  const gametype = params.get("gametype") ?? "";
  const playerParam = Number.parseInt(params.get("player") ?? "", 10);
  const player = Number.isFinite(playerParam) && playerParam > 0 ? playerParam : null;
  const vsBots = params.get("vs_bots") !== "0";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);

  // The view lives in the URL, so a reload, a shared link or the player dialog's link
  // restores it.
  function update(changes: Record<string, string | null>) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  }

  const { data, error, loading } = useMatches({
    map,
    gametype,
    player,
    vsBots,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });
  const unavailable =
    error !== null && !data && /not being recorded|unavailable/i.test(error);

  // The filter choices are the installed maps and the gametypes the server knows; a value
  // already in the URL is kept as a choice even when it is not installed any more.
  const maps = useResource(() => api.maps(), []);
  const gametypes = useResource(() => api.gametypes(), []);
  const mapNames = new Set(maps.data?.maps.map((m) => m.name) ?? []);
  if (map) mapNames.add(map);
  const gametypeIds = new Set(gametypes.data?.gametypes.map((g) => g.id) ?? []);
  gametypeIds.add(UNKNOWN);
  if (gametype) gametypeIds.add(gametype);

  const [dialog, setDialog] = useState<Dialog | null>(null);

  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(total, page * PAGE_SIZE);
  const filtered = map !== "" || gametype !== "" || player !== null || !vsBots;

  function openMatch(m: MatchSummary, row: HTMLElement) {
    setDialog({
      kind: "match",
      id: m.id,
      opener: row.querySelector<HTMLElement>("button") ?? row,
    });
  }

  return (
    <section>
      <h1>Matches</h1>
      <div className="controls-row players-controls">
        <label className="field-inline">
          <span className="muted">Map</span>
          <select
            aria-label="Map"
            value={map}
            onChange={(e) => update({ map: e.target.value || null, page: null })}
          >
            <option value="">All maps</option>
            {[...mapNames].sort().map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="field-inline">
          <span className="muted">Gametype</span>
          <select
            aria-label="Gametype"
            value={gametype}
            onChange={(e) => update({ gametype: e.target.value || null, page: null })}
          >
            <option value="">All gametypes</option>
            {[...gametypeIds].map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={!vsBots}
            onChange={(e) =>
              update({ vs_bots: e.target.checked ? "0" : null, page: null })
            }
          />
          Hide vs bots
        </label>
        {player !== null && (
          <PlayerChip id={player} onRemove={() => update({ player: null, page: null })} />
        )}
      </div>

      {error && !unavailable && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {unavailable && (
        <p className="muted players-empty">Player history is not being recorded.</p>
      )}
      {!data && !error && loading && <p className="muted">Loading…</p>}

      {data && total === 0 && (
        <p className="muted players-empty">
          {filtered
            ? "No matches match these filters."
            : "No matches have been recorded yet. They appear here once a match with a player in it has been played."}
        </p>
      )}

      {data && total > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table matches-table" aria-label="Matches">
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Map</th>
                  <th scope="col">Gametype</th>
                  <th scope="col" className="num">
                    Duration
                  </th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Players</th>
                  <th scope="col">Winner</th>
                </tr>
              </thead>
              <tbody>
                {data.matches.map((m) => (
                  <tr
                    key={m.id}
                    className="player-row"
                    onClick={(e) => openMatch(m, e.currentTarget)}
                  >
                    <td>
                      <button className="link-button">{formatEpoch(m.started_at)}</button>
                    </td>
                    <td>{m.map}</td>
                    <td>{m.gametype}</td>
                    <td className="num">
                      {m.duration === null ? "–" : formatDuration(m.duration)}
                    </td>
                    <td>
                      <Outcome outcome={m.outcome} />
                    </td>
                    <td>
                      <Players match={m} /> <VsBots match={m} />
                    </td>
                    <td>
                      <Winner winner={m.winner} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="controls-row pager">
            <button
              className="btn"
              disabled={page <= 1}
              onClick={() => update({ page: page - 1 <= 1 ? null : String(page - 1) })}
            >
              Previous
            </button>
            <span className="muted" aria-live="polite">
              {from}–{to} of {total}
            </span>
            <button
              className="btn"
              disabled={page >= lastPage}
              onClick={() => update({ page: String(page + 1) })}
            >
              Next
            </button>
          </div>
        </>
      )}

      {dialog?.kind === "match" && (
        <MatchDialog
          id={dialog.id}
          returnFocusTo={dialog.opener}
          onClose={() => setDialog(null)}
          onOpenPlayer={(id, name, opener) =>
            setDialog({ kind: "player", id, name, opener: dialog.opener ?? opener })
          }
        />
      )}
      {dialog?.kind === "player" && (
        <PlayerDialog
          id={dialog.id}
          name={dialog.name}
          returnFocusTo={dialog.opener}
          onClose={() => setDialog(null)}
        />
      )}
    </section>
  );
}
