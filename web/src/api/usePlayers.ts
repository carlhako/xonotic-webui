import { useCallback, useEffect, useRef, useState } from "react";
import { ApiCallError, api } from "./client";
import type { PlayerList, PlayersQuery } from "./client";

/** How often the open table asks again. */
export const PLAYERS_REFRESH_MS = 5000;

export interface PlayersResource {
  data: PlayerList | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** The players list for `query`, kept current while the page is visible.
 *
 *  Polls every {@link PLAYERS_REFRESH_MS} with `If-None-Match`, so an idle table costs a
 *  304. The rows already on screen stay while the next answer loads or when nothing
 *  changed, and a different query is fetched at once. Hidden pages do not poll; they
 *  fetch again as soon as they are visible. */
export function usePlayers(query: PlayersQuery): PlayersResource {
  const [data, setData] = useState<PlayerList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const queryRef = useRef(query);
  queryRef.current = query;
  const key = JSON.stringify(query);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let etag: string | null = null;

    const visible = () => document.visibilityState !== "hidden";
    const stop = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
    };
    const schedule = () => {
      stop();
      if (cancelled || !visible()) return;
      timer = setTimeout(() => void refresh(), PLAYERS_REFRESH_MS);
    };

    async function refresh(): Promise<void> {
      stop();
      try {
        const result = await api.players(queryRef.current, etag);
        if (cancelled) return;
        etag = result.etag;
        if (!result.notModified) setData(result.list);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiCallError ? e.message : String(e));
      } finally {
        if (!cancelled) {
          setLoading(false);
          schedule();
        }
      }
    }

    const onVisibility = () => {
      if (visible()) void refresh();
      else stop();
    };

    setLoading(true);
    document.addEventListener("visibilitychange", onVisibility);
    if (visible()) void refresh();
    else setLoading(false);
    return () => {
      cancelled = true;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
