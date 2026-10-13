import { useState } from "react";
import { allowedActions, useLifecycle, type LifecycleAction } from "../api/useLifecycle";
import type { Status } from "../api/client";

const LABELS: Record<LifecycleAction, string> = {
  start: "Start",
  stop: "Stop",
  restart: "Restart",
};

function playersPhrase(n: number): string {
  return `${n} ${n === 1 ? "player" : "players"}`;
}

// Start, stop and restart, each enabled only when valid for the current state
// (web-ui-shell: "The dashboard shows live state and lifecycle controls"). Stopping or
// restarting asks first when humans are connected, and says how many.
export function ServerControls({
  status,
  disabled,
}: {
  status: Status | null;
  /** True while the state shown may be stale (the connection is down). */
  disabled?: boolean;
}) {
  const { busy, error, run, clearError } = useLifecycle();
  const [confirming, setConfirming] = useState<LifecycleAction | null>(null);

  const state = status?.state;
  const allowed = allowedActions(state);
  const transitioning = state === "starting" || state === "stopping";
  const humans = status?.human_count ?? 0;
  const locked = disabled || busy !== null || state === undefined;

  function request(action: LifecycleAction) {
    if ((action === "stop" || action === "restart") && humans > 0) {
      setConfirming(action);
      return;
    }
    void run(action);
  }

  function confirm() {
    const action = confirming;
    setConfirming(null);
    if (action) void run(action);
  }

  return (
    <div className="controls">
      <div className="controls-row">
        {(Object.keys(LABELS) as LifecycleAction[]).map((action) => (
          <button
            key={action}
            className={`btn btn-${action}`}
            disabled={locked || !allowed[action] || confirming !== null}
            onClick={() => request(action)}
          >
            {LABELS[action]}
          </button>
        ))}
        {(transitioning || busy) && (
          <span className="controls-status" role="status">
            {state === "starting" || busy === "start"
              ? "Starting…"
              : state === "stopping" || busy === "stop"
                ? "Stopping…"
                : "Restarting…"}
          </span>
        )}
      </div>

      {confirming && (
        <div className="confirm" role="alertdialog" aria-label="Confirm">
          <p>
            {confirming === "stop" ? "Stop" : "Restart"} the server?{" "}
            <strong>{playersPhrase(humans)} will be disconnected.</strong>
          </p>
          <div className="controls-row">
            <button className="btn btn-danger" onClick={confirm}>
              {confirming === "stop" ? "Stop anyway" : "Restart anyway"}
            </button>
            <button className="btn" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="controls-error" role="alert">
          {error}
          <button className="link" onClick={clearError}>
            dismiss
          </button>
        </div>
      )}
    </div>
  );
}
