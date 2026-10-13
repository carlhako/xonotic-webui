import { useState } from "react";
import { ApiCallError, api } from "../api/client";
import type { MatchAction, Status } from "../api/client";
import { describeAction } from "../lib/actions";
import { playersPhrase } from "../lib/text";
import { Confirm } from "./Confirm";

type Kind = "skip" | "restart";

const LABEL: Record<Kind, string> = { skip: "Skip map", restart: "Restart match" };

export function ActionStatus({ action }: { action: MatchAction | null | undefined }) {
  if (!action) return null;
  return (
    <p
      role="status"
      className={`action-status is-${action.state}${action.state === "timed_out" ? " is-warn" : ""}`}
    >
      {describeAction(action)}
    </p>
  );
}

// Skip and Restart match, enabled only on a running server with no action pending. With
// humans connected they ask first and say how many are in the match; with nobody
// connected they just go.
export function MatchActions({
  status,
  disabled,
}: {
  status: Status | null;
  disabled?: boolean;
}) {
  const [confirming, setConfirming] = useState<Kind | null>(null);
  const [busy, setBusy] = useState<Kind | null>(null);
  const [error, setError] = useState<string | null>(null);

  const running = status?.state === "running";
  const pending = status?.action?.state === "pending";
  const humans = status?.human_count ?? 0;
  const locked = disabled || !running || pending || busy !== null || confirming !== null;

  async function run(kind: Kind) {
    setBusy(kind);
    setError(null);
    try {
      await (kind === "skip" ? api.skipMap() : api.restartMatch());
    } catch (e) {
      setError(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  function request(kind: Kind) {
    if (humans > 0) {
      setConfirming(kind);
      return;
    }
    void run(kind);
  }

  return (
    <div className="controls match-actions">
      <div className="controls-row">
        {(Object.keys(LABEL) as Kind[]).map((kind) => (
          <button
            key={kind}
            className="btn"
            disabled={locked}
            onClick={() => request(kind)}
          >
            {LABEL[kind]}
          </button>
        ))}
      </div>

      {confirming && (
        <Confirm
          confirmLabel={confirming === "skip" ? "Skip anyway" : "Restart anyway"}
          onConfirm={() => {
            const kind = confirming;
            setConfirming(null);
            void run(kind);
          }}
          onCancel={() => setConfirming(null)}
        >
          {confirming === "skip" ? "Skip this map?" : "Restart the match?"}{" "}
          <strong>
            {playersPhrase(humans)} {humans === 1 ? "is" : "are"} in the match.
          </strong>
        </Confirm>
      )}

      <ActionStatus action={status?.action} />

      {error && (
        <div className="controls-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
