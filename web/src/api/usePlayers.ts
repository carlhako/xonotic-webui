import { api } from "./client";
import type { PlayerList, PlayersQuery } from "./client";
import { usePolled } from "./usePolled";
import type { Conditional } from "./usePolled";

/** How often the open table asks again. */
export const PLAYERS_REFRESH_MS = 5000;

export interface PlayersResource {
  data: PlayerList | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

async function fetchPlayers(
  query: PlayersQuery,
  etag: string | null,
): Promise<Conditional<PlayerList>> {
  const result = await api.players(query, etag);
  return result.notModified
    ? { notModified: true, etag: result.etag }
    : { notModified: false, etag: result.etag, value: result.list };
}

/** The players list for `query`, kept current while the page is visible (see
 *  {@link usePolled}): polls every {@link PLAYERS_REFRESH_MS} with `If-None-Match`. */
export function usePlayers(query: PlayersQuery): PlayersResource {
  return usePolled(fetchPlayers, query, PLAYERS_REFRESH_MS);
}
