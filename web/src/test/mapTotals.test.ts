import { describe, expect, it } from "vitest";
import {
  filterPlayed,
  formatTotal,
  hasTotals,
  sortMaps,
  totalsLine,
} from "../lib/mapTotals";
import { makeMap } from "./util";

describe("map totals formatting", () => {
  it("shows 0, thousands separators and a dash for null", () => {
    expect(formatTotal(0)).toBe("0");
    expect(formatTotal(1380)).toBe("1,380");
    expect(formatTotal(null)).toBe("–");
  });

  it("builds the card line, with dashes and no × when not available", () => {
    expect(totalsLine({ played: 42, frags: 1380 })).toBe("Played 42× · 1,380 frags");
    expect(totalsLine({ played: 0, frags: 0 })).toBe("Played 0× · 0 frags");
    expect(totalsLine({ played: null, frags: null })).toBe("Played – · – frags");
  });
});

describe("map sorting and filtering", () => {
  const maps = [
    makeMap({ name: "b", played: 3, frags: 10, last_played: 100 }),
    makeMap({ name: "a", played: 3, frags: 50, last_played: 300 }),
    makeMap({ name: "d", played: 0, frags: 0, last_played: null }),
    makeMap({ name: "c", played: 9, frags: 10, last_played: 200 }),
  ];
  const names = (list: { name: string }[]) => list.map((m) => m.name);

  it("orders each way, ties by name", () => {
    expect(names(sortMaps(maps, "name"))).toEqual(["a", "b", "c", "d"]);
    expect(names(sortMaps(maps, "played"))).toEqual(["c", "a", "b", "d"]);
    expect(names(sortMaps(maps, "frags"))).toEqual(["a", "b", "c", "d"]);
    expect(names(sortMaps(maps, "recent"))).toEqual(["a", "c", "b", "d"]);
  });

  it("puts never-played maps last by name under recently played", () => {
    const more = [
      ...maps,
      makeMap({ name: "0", played: 0, frags: 0, last_played: null }),
    ];
    expect(names(sortMaps(more, "recent")).slice(-2)).toEqual(["0", "d"]);
  });

  it("filters played and never played", () => {
    expect(names(filterPlayed(maps, "played"))).toEqual(["b", "a", "c"]);
    expect(names(filterPlayed(maps, "never"))).toEqual(["d"]);
    expect(names(filterPlayed(maps, "all"))).toEqual(["b", "a", "d", "c"]);
  });

  it("knows whether totals are available", () => {
    expect(hasTotals(maps)).toBe(true);
    expect(hasTotals([makeMap({ played: null, frags: null })])).toBe(false);
    expect(hasTotals([])).toBe(true);
  });
});
