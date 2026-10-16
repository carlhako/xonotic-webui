import { api } from "./client";
import type { MatchList, MatchesQuery } from "./client";
import { usePolled } from "./usePolled";
import type { Conditional } from "./usePolled";

/** How often the open list asks again: a match that ends shows within a few seconds. */
export const MATCHES_REFRESH_MS = 5000;

export interface MatchesResource {
  data: MatchList | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

async function fetchMatches(
  query: MatchesQuery,
  etag: string | null,
): Promise<Conditional<MatchList>> {
  const result = await api.matches(query, etag);
  return result.notModified
    ? { notModified: true, etag: result.etag }
    : { notModified: false, etag: result.etag, value: result.list };
}

/** The match history for `query`, kept current while the page is visible (see
 *  {@link usePolled}): polls every {@link MATCHES_REFRESH_MS} with `If-None-Match`, and
 *  keeps the filters and page. */
export function useMatches(query: MatchesQuery): MatchesResource {
  return usePolled(fetchMatches, query, MATCHES_REFRESH_MS);
}
