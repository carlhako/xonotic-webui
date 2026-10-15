import { useCallback, useRef, useState } from "react";
import { useEventSource } from "./useEventSource";
import type { Match } from "./client";

export interface MatchState {
  match: Match | null;
  /** A match state is held but the live connection is down or has not yet delivered a
   *  fresh one, so it must not be presented as current. */
  stale: boolean;
}

// Subscribes to the live match stream. The panel only polls the game while this stream is
// open, so the hook is used by the dashboard alone and the stream closes with it. On every
// (re)connection the server sends the current state first.
export function useMatch(): MatchState {
  const [match, setMatch] = useState<Match | null>(null);
  const [fresh, setFresh] = useState(false);
  const hadMatch = useRef(false);

  const onMessage = useCallback((ev: MessageEvent) => {
    try {
      setMatch(JSON.parse(ev.data) as Match);
      hadMatch.current = true;
      setFresh(true);
    } catch {
      // ignore a malformed frame
    }
  }, []);
  const onOpen = useCallback(() => setFresh(false), []);

  const { connected } = useEventSource("/api/match/stream", onMessage, onOpen);
  return { match, stale: hadMatch.current && !(connected && fresh) };
}
