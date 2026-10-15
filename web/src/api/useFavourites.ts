import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiCallError, api } from "./client";

export interface Favourites {
  /** The starred map names, with a toggle that has not been confirmed yet applied. */
  has: (name: string) => boolean;
  /** Star or unstar a map; the star changes at once and is put back if the panel refuses. */
  toggle: (name: string) => Promise<void>;
  /** The error from loading the favourites or from the last toggle, if any. */
  error: string | null;
}

/** The shared favourite maps with optimistic toggling (map-favourites spec). */
export function useFavourites(): Favourites {
  const [saved, setSaved] = useState<ReadonlySet<string>>(new Set());
  // name -> the state a toggle in flight is moving it to
  const [pending, setPending] = useState<ReadonlyMap<string, boolean>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const pendingRef = useRef(pending);
  pendingRef.current = pending;

  useEffect(() => {
    let cancelled = false;
    api
      .favourites()
      .then((view) => {
        if (!cancelled) setSaved(new Set(view.maps));
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiCallError ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const shown = useMemo(() => {
    const next = new Set(saved);
    pending.forEach((on, name) => (on ? next.add(name) : next.delete(name)));
    return next;
  }, [saved, pending]);
  const shownRef = useRef(shown);
  shownRef.current = shown;

  const toggle = useCallback(async (name: string) => {
    const want = !shownRef.current.has(name);
    setError(null);
    setPending((p) => new Map(p).set(name, want));
    try {
      if (want) await api.addFavourite(name);
      else await api.removeFavourite(name);
      // the change is confirmed: it becomes the saved state (never replace the whole
      // set with an answer that may be older than another toggle's)
      setSaved((s) => {
        const next = new Set(s);
        if (want) next.add(name);
        else next.delete(name);
        return next;
      });
    } catch (e) {
      setError(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setPending((p) => {
        const next = new Map(p);
        next.delete(name);
        return next;
      });
    }
  }, []);

  return { has: (name) => shown.has(name), toggle, error };
}
