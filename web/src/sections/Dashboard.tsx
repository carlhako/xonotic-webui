import { useStatus } from "../api/StatusContext";
import { ColoredText } from "../components/ColoredText";
import { MatchActions } from "../components/MatchActions";
import { ServerControls } from "../components/ServerControls";
import { formatTimestamp } from "../lib/time";
import type { RunState } from "../api/client";

const STATE_LABEL: Record<RunState, string> = {
  stopped: "Stopped",
  starting: "Starting",
  running: "Running",
  stopping: "Stopping",
};

function Unknown() {
  return (
    <span className="muted" title="not known yet">
      —
    </span>
  );
}

export function Dashboard() {
  const { status, stale } = useStatus();
  const state = status?.state;

  return (
    <section className={`section dashboard${stale ? " is-stale" : ""}`}>
      <h1>Dashboard</h1>

      <div className="cards">
        <div className="card">
          <div className="card-label">Server</div>
          <div className={`card-value state-${state ?? "unknown"}`}>
            {state ? STATE_LABEL[state] : "…"}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Map</div>
          <div className="card-value">{status?.map ?? <Unknown />}</div>
        </div>
        <div className="card">
          <div className="card-label">Gametype</div>
          <div className="card-value">{status?.gametype ?? <Unknown />}</div>
        </div>
        <div className="card">
          <div className="card-label">Players</div>
          <div className="card-value">
            {status ? (
              <>
                {status.human_count}
                <span className="card-sub">
                  {" "}
                  {status.human_count === 1 ? "human" : "humans"}, {status.bot_count}{" "}
                  {status.bot_count === 1 ? "bot" : "bots"}
                </span>
              </>
            ) : (
              "—"
            )}
          </div>
        </div>
      </div>

      <ServerControls status={status} disabled={stale} />
      <MatchActions status={status} disabled={stale} />

      {status?.event_log === "unavailable" && (
        <div className="panel is-warn" role="status">
          <strong>Live player tracking is unavailable.</strong>{" "}
          <span className="muted">
            The server&apos;s event log is not enabled, so the player list is refreshed
            periodically instead of live.
          </span>
        </div>
      )}

      <div className="panel">
        <h2>Players online</h2>
        {status && status.players.length > 0 ? (
          <ul className="player-list">
            {status.players.map((p) => (
              <li key={p.ent}>
                <span className="xon-text" title={p.plain_name}>
                  <ColoredText text={p.name} />
                </span>
                {p.bot && <span className="badge">bot</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No one is connected.</p>
        )}
      </div>

      {status?.last_start_failure && (
        <div className="panel is-warn">
          <h2>Last start failed</h2>
          <p>
            {status.last_start_failure.reason}
            <span className="muted">
              {" "}
              · {formatTimestamp(status.last_start_failure.at)}
            </span>
          </p>
        </div>
      )}

      {status?.last_crash && (
        <div className={`panel${status.restart_abandoned ? " is-warn" : ""}`}>
          <h2>Last crash</h2>
          <p>
            {status.restart_abandoned
              ? "Automatic restart was abandoned after repeated crashes. Start the server to try again."
              : "The server crashed and was started again."}
            <span className="muted">
              {" "}
              · exit status {status.last_crash.exit_code ?? "unknown"} ·{" "}
              {formatTimestamp(status.last_crash.at)}
            </span>
          </p>
        </div>
      )}
    </section>
  );
}
