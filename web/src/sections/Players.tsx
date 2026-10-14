import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { PlayerRow, PlayerSort } from "../api/client";
import { usePlayers } from "../api/usePlayers";
import { ColoredText } from "../components/ColoredText";
import { PlayerDialog } from "../components/PlayerDialog";
import { formatDuration, formatEpoch, formatRelative } from "../lib/time";

const PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 250;

interface Column {
  sort: PlayerSort;
  label: string;
  numeric: boolean;
  /** The order a first click gives: text A-Z, figures highest first. */
  first: "asc" | "desc";
}

const COLUMNS: Column[] = [
  { sort: "name", label: "Name", numeric: false, first: "asc" },
  { sort: "frags", label: "Frags", numeric: true, first: "desc" },
  { sort: "deaths", label: "Deaths", numeric: true, first: "desc" },
  { sort: "kd", label: "K/D", numeric: true, first: "desc" },
  { sort: "score", label: "Score", numeric: true, first: "desc" },
  { sort: "wins", label: "Wins", numeric: true, first: "desc" },
  { sort: "matches", label: "Matches", numeric: true, first: "desc" },
  { sort: "time_playing", label: "Time playing", numeric: true, first: "desc" },
  { sort: "time_on_server", label: "Time on server", numeric: true, first: "desc" },
  { sort: "accuracy", label: "Accuracy", numeric: true, first: "desc" },
  { sort: "last_seen", label: "Last seen", numeric: true, first: "desc" },
];

const SORTS = new Set<string>(COLUMNS.map((c) => c.sort));
const DEFAULT_SORT: PlayerSort = "frags";

function parseSort(value: string | null): PlayerSort {
  return value !== null && SORTS.has(value) ? (value as PlayerSort) : DEFAULT_SORT;
}

function defaultOrder(sort: PlayerSort): "asc" | "desc" {
  return COLUMNS.find((c) => c.sort === sort)?.first ?? "desc";
}

function ariaSort(active: boolean, order: "asc" | "desc") {
  if (!active) return "none" as const;
  return order === "asc" ? ("ascending" as const) : ("descending" as const);
}

function cell(player: PlayerRow, sort: PlayerSort) {
  switch (sort) {
    case "frags":
      return player.frags;
    case "deaths":
      return player.deaths;
    case "kd":
      return player.kd.toFixed(2);
    case "score":
      return Number.isInteger(player.score) ? player.score : player.score.toFixed(1);
    case "wins":
      return player.wins;
    case "matches":
      return player.matches;
    case "time_playing":
      return formatDuration(player.time_playing);
    case "time_on_server":
      return formatDuration(player.time_on_server);
    case "accuracy":
      return player.accuracy === null ? "–" : `${(player.accuracy * 100).toFixed(0)}%`;
    case "last_seen":
      return (
        <span title={formatEpoch(player.last_seen)}>
          {formatRelative(player.last_seen)}
        </span>
      );
    default:
      return null;
  }
}

export function Players() {
  const [params, setParams] = useSearchParams();
  const sort = parseSort(params.get("sort"));
  const order =
    params.get("order") === "asc" || params.get("order") === "desc"
      ? (params.get("order") as "asc" | "desc")
      : defaultOrder(sort);
  const q = params.get("q") ?? "";
  const bots = params.get("bots") === "1";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);

  // The view lives in the URL, so a reload or a shared link restores it.
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

  const [search, setSearch] = useState(q);
  const lastQ = useRef(q);
  useEffect(() => {
    // follow the URL when it changes under us (back/forward, a link)
    if (q !== lastQ.current) {
      lastQ.current = q;
      setSearch(q);
    }
  }, [q]);
  useEffect(() => {
    if (search === lastQ.current) return;
    const timer = setTimeout(() => {
      lastQ.current = search;
      update({ q: search.trim() || null, page: null });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const { data, error, loading } = usePlayers({
    sort,
    order,
    q,
    bots,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  const [open, setOpen] = useState<{
    id: number;
    name: string;
    opener: HTMLElement | null;
  } | null>(null);

  function activate(player: PlayerRow, row: HTMLElement) {
    setOpen({
      id: player.id,
      name: player.name,
      opener: row.querySelector<HTMLElement>("button") ?? row,
    });
  }

  function sortBy(column: Column) {
    if (column.sort === sort) {
      update({ order: order === "asc" ? "desc" : "asc", page: null });
    } else {
      update({ sort: column.sort, order: column.first, page: null });
    }
  }

  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(total, page * PAGE_SIZE);
  const filtered = q !== "";

  return (
    <section>
      <h1>Players</h1>
      <div className="controls-row players-controls">
        <input
          type="search"
          aria-label="Search players"
          placeholder="Search by name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="search-input"
        />
        <label className="check">
          <input
            type="checkbox"
            checked={bots}
            onChange={(e) => update({ bots: e.target.checked ? "1" : null, page: null })}
          />
          Show bots
        </label>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!data && loading && <p className="muted">Loading…</p>}

      {data && total === 0 && (
        <p className="muted players-empty">
          {filtered
            ? "No players match that name."
            : "No players have been recorded yet. They appear here once someone has joined the server."}
        </p>
      )}

      {data && total > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table players-table" aria-label="Players">
              <thead>
                <tr>
                  {COLUMNS.map((c) => (
                    <th
                      key={c.sort}
                      scope="col"
                      aria-sort={ariaSort(c.sort === sort, order)}
                      className={c.numeric ? "num" : undefined}
                    >
                      <button className="sort-button" onClick={() => sortBy(c)}>
                        {c.label}
                        {c.sort === sort && (
                          <span aria-hidden="true">{order === "asc" ? " ▲" : " ▼"}</span>
                        )}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.players.map((p) => (
                  <tr
                    key={p.id}
                    className="player-row"
                    onClick={(e) => activate(p, e.currentTarget)}
                  >
                    <td>
                      <button className="link-button">
                        <span className="xon-text">
                          <ColoredText text={p.name} />
                        </span>
                      </button>
                      {p.is_bot && (
                        <span className="badge badge-bot" title="a bot">
                          bot
                        </span>
                      )}
                    </td>
                    {COLUMNS.slice(1).map((c) => (
                      <td key={c.sort} className="num">
                        {cell(p, c.sort)}
                      </td>
                    ))}
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

      {open && (
        <PlayerDialog
          id={open.id}
          name={open.name}
          returnFocusTo={open.opener}
          onClose={() => setOpen(null)}
        />
      )}
    </section>
  );
}
