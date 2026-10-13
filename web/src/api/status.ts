import { useCallback, useRef, useState } from "react";
import { useEventSource } from "./useEventSource";
import type { Status } from "./client";

export interface ServerStatus {
  status: Status | null;
  connected: boolean;
  /** True when a status is held but the live connection is down or has not yet
   *  delivered a fresh snapshot, so it must not be presented as current. */
  stale: boolean;
}

// Subscribes to the status stream. On every (re)connection the server sends the current
// snapshot first, which replaces whatever was held (web-ui-shell: displayed state is
// replaced with fresh state on reconnect).
export function useServerStatus(): ServerStatus {
  const [status, setStatus] = useState<Status | null>(null);
  const [fresh, setFresh] = useState(false);
  const hadStatus = useRef(false);

  const onMessage = useCallback((ev: MessageEvent) => {
    try {
      setStatus(JSON.parse(ev.data) as Status);
      hadStatus.current = true;
      setFresh(true);
    } catch {
      // ignore a malformed frame
    }
  }, []);

  const onOpen = useCallback(() => setFresh(false), []);

  const { connected } = useEventSource("/api/status/stream", onMessage, onOpen);
  return {
    status,
    connected,
    stale: hadStatus.current && !(connected && fresh),
  };
}
