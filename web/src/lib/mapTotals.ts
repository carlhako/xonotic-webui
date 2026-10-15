import type { MapInfo } from "../api/client";

/** A play total with thousands separators, or a dash when the figure is not available. */
export function formatTotal(value: number | null): string {
  return value === null ? "–" : value.toLocaleString("en-US");
}

/** The card's line: `Played 42× · 1,380 frags` (dashes when the totals are not
 *  available, never zero). */
export function totalsLine(map: Pick<MapInfo, "played" | "frags">): string {
  const played = map.played === null ? "–" : `${formatTotal(map.played)}×`;
  return `Played ${played} · ${formatTotal(map.frags)} frags`;
}

export const MAP_SORTS = ["name", "played", "frags", "recent"] as const;
export type MapSort = (typeof MAP_SORTS)[number];

export const MAP_SORT_LABELS: Record<MapSort, string> = {
  name: "Name",
  played: "Most played",
  frags: "Most frags",
  recent: "Recently played",
};

export const PLAYED_FILTERS = ["all", "played", "never"] as const;
export type PlayedFilter = (typeof PLAYED_FILTERS)[number];

/** True when every map carries its play totals (they are all null together when player
 *  history is not being recorded). */
export function hasTotals(maps: readonly MapInfo[]): boolean {
  return maps.every((m) => m.played !== null);
}

const byName = (a: MapInfo, b: MapInfo) =>
  a.name < b.name ? -1 : a.name > b.name ? 1 : 0;

/** The maps ordered by `sort`; ties, and maps never played under "recent", go by name. */
export function sortMaps(maps: readonly MapInfo[], sort: MapSort): MapInfo[] {
  const key: Record<MapSort, (m: MapInfo) => number> = {
    name: () => 0,
    played: (m) => -(m.played ?? 0),
    frags: (m) => -(m.frags ?? 0),
    // never played sorts after every real time
    recent: (m) => (m.last_played === null ? Infinity : -m.last_played),
  };
  const by = key[sort];
  return [...maps].sort((a, b) => {
    const x = by(a);
    const y = by(b);
    return x < y ? -1 : x > y ? 1 : byName(a, b);
  });
}

export function filterPlayed(maps: readonly MapInfo[], filter: PlayedFilter): MapInfo[] {
  if (filter === "all") return [...maps];
  return maps.filter((m) => (filter === "played") === (m.played ?? 0) > 0);
}
