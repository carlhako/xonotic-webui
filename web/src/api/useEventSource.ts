import { useEffect, useRef, useState } from "react";

export interface EventSourceState {
  connected: boolean;
}

// Wraps EventSource with automatic reconnection and a `connected` flag the shell uses to
// show a disconnected banner and avoid presenting stale state as current (web-ui-shell:
// "Connection loss is shown and recovered from"). `onOpen` fires on every (re)connection
// so a consumer can discard what it had: the server replays its state on connect.
export function useEventSource(
  url: string,
  onMessage: (ev: MessageEvent) => void,
  onOpen?: () => void,
): EventSourceState {
  const [connected, setConnected] = useState(false);
  const messageRef = useRef(onMessage);
  messageRef.current = onMessage;
  const openRef = useRef(onOpen);
  openRef.current = onOpen;

  useEffect(() => {
    let es: EventSource | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      es = new EventSource(url);
      es.onopen = () => {
        retry = 0;
        openRef.current?.();
        setConnected(true);
      };
      es.onmessage = (ev) => messageRef.current(ev);
      es.onerror = () => {
        setConnected(false);
        es?.close();
        es = null;
        const delay = Math.min(500 * 2 ** retry, 10000);
        retry += 1;
        timer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [url]);

  return { connected };
}
