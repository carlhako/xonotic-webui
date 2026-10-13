import { useCallback, useRef, useState } from "react";
import { useEventSource } from "./useEventSource";
import { api, type ConsoleLine } from "./client";

const MAX_LINES = 5000;

export interface ConsoleFeed {
  lines: ConsoleLine[];
  connected: boolean;
  send: (command: string) => Promise<void>;
}

// Streams console output with a bounded scroll-back buffer, de-duplicated by sequence
// number. The server replays its whole retained history on every (re)connection, and its
// numbering restarts if the panel restarted, so the buffer is rebuilt from scratch on
// each connection rather than appended to.
export function useConsole(): ConsoleFeed {
  const [lines, setLines] = useState<ConsoleLine[]>([]);
  const lastSeq = useRef(0);

  const onOpen = useCallback(() => {
    lastSeq.current = 0;
    setLines([]);
  }, []);

  const onMessage = useCallback((ev: MessageEvent) => {
    let line: ConsoleLine;
    try {
      line = JSON.parse(ev.data) as ConsoleLine;
    } catch {
      return;
    }
    if (line.seq <= lastSeq.current) return;
    lastSeq.current = line.seq;
    setLines((prev) => {
      const next = prev.concat(line);
      return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
    });
  }, []);

  const { connected } = useEventSource("/api/console/stream", onMessage, onOpen);
  const send = useCallback((command: string) => api.sendCommand(command), []);
  return { lines, connected, send };
}
