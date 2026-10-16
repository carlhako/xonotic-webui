import { useCallback, useEffect, useRef, useState } from "react";
import { ApiCallError } from "./client";

/** What a conditional request answers: unchanged since `etag`, or a fresh value. */
export type Conditional<T> =
  | { notModified: true; etag: string | null }
  | { notModified: false; etag: string | null; value: T };

export interface PolledResource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** A value for `query`, kept current while the page is visible.
 *
 *  Asks again every `intervalMs` with the last answer's ETag, so an idle view costs a
 *  304. The value already on screen stays while the next answer loads or when nothing
 *  changed, and a different query is fetched at once. Hidden pages do not poll; they
 *  fetch again as soon as they are visible. */
export function usePolled<Q, T>(
  fetcher: (query: Q, etag: string | null) => Promise<Conditional<T>>,
  query: Q,
  intervalMs: number,
): PolledResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const queryRef = useRef(query);
  queryRef.current = query;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
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
      timer = setTimeout(() => void refresh(), intervalMs);
    };

    async function refresh(): Promise<void> {
      stop();
      try {
        const result = await fetcherRef.current(queryRef.current, etag);
        if (cancelled) return;
        etag = result.etag;
        if (!result.notModified) setData(result.value);
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
  }, [key, tick, intervalMs]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
