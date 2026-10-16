import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MatchesQuery } from "../api/client";
import { MATCHES_REFRESH_MS, useMatches } from "../api/useMatches";
import { jsonResponse, makeMatchSummary } from "./util";

const QUERY: MatchesQuery = {
  map: "",
  gametype: "",
  player: null,
  vsBots: true,
  limit: 50,
  offset: 0,
};

function list(maps: string[], revision = 1) {
  return {
    revision,
    total: maps.length,
    matches: maps.map((map, i) => makeMatchSummary({ id: i + 1, map })),
  };
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    value: state,
    configurable: true,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["setTimeout", "clearTimeout"] });
  setVisibility("visible");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function reply(body: unknown, etag: string): Response {
  const response = jsonResponse(body);
  response.headers.set("ETag", etag);
  return response;
}

describe("useMatches (7.1)", () => {
  it("loads at once and asks again on the interval with the last ETag", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      new Headers(init?.headers).get("If-None-Match")
        ? new Response(null, { status: 304, headers: { ETag: '"1--a"' } })
        : reply(list(["boil"]), '"1--a"'),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useMatches(QUERY));
    await waitFor(() => expect(result.current.data?.total).toBe(1));
    expect(
      new Headers(fetchMock.mock.calls[0][1]?.headers).get("If-None-Match"),
    ).toBeNull();

    await tick(MATCHES_REFRESH_MS);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get("If-None-Match")).toBe(
      '"1--a"',
    );
    // a 304 keeps the rows on screen
    expect(result.current.data?.matches[0].map).toBe("boil");
    expect(result.current.error).toBeNull();
  });

  it("shows a match that ended on the next poll", async () => {
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        call += 1;
        return call === 1
          ? reply(
              {
                ...list(["boil"]),
                matches: [makeMatchSummary({ outcome: "in_progress", winner: null })],
              },
              '"1-0.5.5-a"',
            )
          : reply(list(["boil"], 2), '"2--a"');
      }),
    );
    const { result } = renderHook(() => useMatches(QUERY));
    await waitFor(() =>
      expect(result.current.data?.matches[0].outcome).toBe("in_progress"),
    );
    await tick(MATCHES_REFRESH_MS);
    await waitFor(() => expect(result.current.data?.matches[0].outcome).toBe("finished"));
  });

  it("fetches again at once for a different query and sends its filters", async () => {
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) =>
      reply(list(url.includes("map=atelier") ? ["atelier"] : ["boil"]), '"1--x"'),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result, rerender } = renderHook(({ q }) => useMatches(q), {
      initialProps: { q: QUERY },
    });
    await waitFor(() => expect(result.current.data?.matches[0].map).toBe("boil"));
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/matches?limit=50&offset=0");

    rerender({
      q: {
        ...QUERY,
        map: "atelier",
        gametype: "ctf",
        player: 7,
        vsBots: false,
        offset: 50,
      },
    });
    await waitFor(() => expect(result.current.data?.matches[0].map).toBe("atelier"));
    const url = new URL(String(fetchMock.mock.calls.at(-1)?.[0]), "http://x");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      limit: "50",
      offset: "50",
      map: "atelier",
      gametype: "ctf",
      player: "7",
      vs_bots: "false",
    });
    // the new query starts without the old query's ETag
    expect(
      new Headers(fetchMock.mock.calls.at(-1)?.[1]?.headers).get("If-None-Match"),
    ).toBeNull();
  });

  it("reports an error and keeps the last rows", async () => {
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        call += 1;
        if (call === 1) return reply(list(["boil"]), '"1--a"');
        return jsonResponse(
          { detail: { code: "players_unavailable", message: "no history" } },
          503,
        );
      }),
    );
    const { result } = renderHook(() => useMatches(QUERY));
    await waitFor(() => expect(result.current.data?.total).toBe(1));
    await tick(MATCHES_REFRESH_MS);
    await waitFor(() => expect(result.current.error).toBe("no history"));
    expect(result.current.data?.total).toBe(1);
  });

  it("does not poll while the page is hidden and fetches when it is shown", async () => {
    const fetchMock = vi.fn(async () => reply(list(["boil"]), '"1--a"'));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useMatches(QUERY));
    await waitFor(() => expect(result.current.data).not.toBeNull());
    setVisibility("hidden");
    await tick(MATCHES_REFRESH_MS * 3);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    setVisibility("visible");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
