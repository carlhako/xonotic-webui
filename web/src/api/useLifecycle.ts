import { useCallback, useState } from "react";
import { ApiCallError, api } from "./client";
import type { RunState } from "./client";

export type LifecycleAction = "start" | "stop" | "restart";

export interface LifecycleControls {
  busy: LifecycleAction | null;
  error: string | null;
  run: (action: LifecycleAction) => Promise<void>;
  clearError: () => void;
}

/** Which actions are valid for a lifecycle state. A transition in progress allows none. */
export function allowedActions(
  state: RunState | undefined,
): Record<LifecycleAction, boolean> {
  return {
    start: state === "stopped",
    stop: state === "running",
    restart: state === "running",
  };
}

export function useLifecycle(): LifecycleControls {
  const [busy, setBusy] = useState<LifecycleAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (action: LifecycleAction) => {
    setBusy(action);
    setError(null);
    try {
      await api[action]();
    } catch (e) {
      setError(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);
  return { busy, error, run, clearError };
}
