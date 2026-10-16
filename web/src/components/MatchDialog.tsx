import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { MatchDetail, MatchHistoryPlayer } from "../api/client";
import { useResource } from "../api/useResource";
import { formatDuration, formatEpoch } from "../lib/time";
import { Dialog } from "./Dialog";
import { ScoreTable } from "./ScoreTable";
import { Outcome, Players, VsBots, Winner } from "./matchParts";

function Details({
  match,
  onOpenPlayer,
}: {
  match: MatchDetail;
  onOpenPlayer: (id: number, name: string, opener: HTMLElement) => void;
}) {
  const { scoreboard } = match;
  return (
    <>
      <dl className="detail-grid">
        <dt>Started</dt>
        <dd>{formatEpoch(match.started_at)}</dd>
        <dt>Map</dt>
        <dd>
          {match.map} · {match.gametype}
        </dd>
        <dt>Duration</dt>
        <dd>{match.duration === null ? "–" : formatDuration(match.duration)}</dd>
        <dt>Outcome</dt>
        <dd>
          <Outcome outcome={match.outcome} /> <VsBots match={match} />
        </dd>
        <dt>Players</dt>
        <dd>
          <Players match={match} />
        </dd>
        <dt>Winner</dt>
        <dd>
          <Winner winner={match.winner} />
        </dd>
      </dl>

      <h3>Final scoreboard</h3>
      {scoreboard.players.length === 0 ? (
        <p className="muted">No players are recorded for this match.</p>
      ) : (
        <div className="scoreboard">
          <ScoreTable<MatchHistoryPlayer>
            columns={scoreboard.columns}
            players={scoreboard.players}
            teams={scoreboard.teams}
            label="Final scoreboard"
            rowKey={(p) => String(p.player_id)}
            onPlayer={(p, opener) => onOpenPlayer(p.player_id, p.name, opener)}
          />
        </div>
      )}
      {!match.board_kept &&
        (match.outcome === "finished" || match.outcome === "cut_short") && (
          <p className="muted">
            Teams were not recorded for this match, so the players are not grouped by
            team.
          </p>
        )}
      {match.outcome === "no_report" && (
        <p className="muted">
          This match ended without an end-of-match report, so only frags, deaths, suicides
          and team kills were recorded.
        </p>
      )}
    </>
  );
}

/** One past match: its summary and final scoreboard, in a dialog. A player in the
 *  scoreboard opens that player (the parent swaps the dialogs, so only one is open). */
export function MatchDialog({
  id,
  returnFocusTo,
  onClose,
  onOpenPlayer,
}: {
  id: number;
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
  onOpenPlayer: (id: number, name: string, opener: HTMLElement) => void;
}) {
  const { data, error, loading } = useResource(() => api.match(id), [id]);
  return (
    <Dialog
      title={
        data ? (
          <span>
            {data.map} <span className="muted">· {formatEpoch(data.started_at)}</span>
          </span>
        ) : (
          "Match"
        )
      }
      returnFocusTo={returnFocusTo}
      onClose={onClose}
      wide
    >
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!data && !error && loading && <p className="muted">Loading…</p>}
      {data && <Details match={data} onOpenPlayer={onOpenPlayer} />}
    </Dialog>
  );
}

/** A link to the Matches section filtered to one player. */
export function MatchesLink({
  playerId,
  onClick,
}: {
  playerId: number;
  onClick?: () => void;
}) {
  return (
    <Link to={`/matches?player=${playerId}`} className="btn" onClick={onClick}>
      View matches
    </Link>
  );
}
