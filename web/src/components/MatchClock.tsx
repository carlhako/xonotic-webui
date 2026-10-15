import type { Match, MatchClock as Clock } from "../api/client";
import { formatClock } from "../lib/time";

function ClockValue({ clock }: { clock: Clock }) {
  const left = clock.left_s;
  switch (clock.phase) {
    case "countdown":
      return <>Starting in {formatClock(left ?? 0)}</>;
    case "warmup":
      return <>Warmup</>;
    case "overtime":
      return <>Overtime</>;
    case "ended":
      return <>Match over</>;
    default:
      // playing: time left, or time elapsed when there is no time limit
      return <>{formatClock(left ?? clock.elapsed_s ?? 0)}</>;
  }
}

function ClockDetail({ clock }: { clock: Clock }) {
  const left = clock.left_s;
  const limit = clock.time_limit_s;
  switch (clock.phase) {
    case "warmup":
    case "overtime":
      return <>{left !== null ? `${formatClock(left)} left` : "no time limit"}</>;
    case "playing":
      return left !== null ? (
        <>left · limit {formatClock(limit ?? 0)}</>
      ) : (
        <>elapsed · no time limit</>
      );
    default:
      return null;
  }
}

/** The match clock card: the phase or the time left, whether the server is paused, and
 *  the score limit beside it. Rendered only while a match is live. */
export function MatchClockCard({ match, stale }: { match: Match; stale: boolean }) {
  const { clock, score_limit: limit } = match;
  return (
    <div className={`card match-clock${stale ? " is-stale" : ""}`}>
      <div className="card-label">Match clock</div>
      {clock.available ? (
        <>
          <div className="card-value">
            <span className="match-clock-time">
              <ClockValue clock={clock} />
            </span>
            {clock.paused && <span className="badge badge-warn">paused</span>}
          </div>
          <div className="card-sub">
            <ClockDetail clock={clock} />
          </div>
        </>
      ) : (
        <div className="card-value muted">Clock unavailable</div>
      )}
      <div className="card-sub match-limit">
        {limit.value !== null
          ? `Score limit ${limit.value} ${limit.unit}`
          : "No score limit"}
      </div>
    </div>
  );
}
