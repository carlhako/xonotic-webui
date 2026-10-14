import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PlayersQuery } from "../api/client";
import { PLAYERS_REFRESH_MS, usePlayers } from "../api/usePlayers";
import { jsonResponse, makePlayerRow } from "./util";

const QUERY: PlayersQuery = {
  sort: "frags",
  order: "desc",
  q: "",
  bots: false,
  limit: 50,
  offset: 0,
};

function list(names: string[], revision = 1) {
  return {
    revision,
    total: names.length,
    players: names.map((n, i) => makePlayerRow({ id: i + 1, name: n, plain_name: n })),
  };
}

interface Reply {
  status?: number;
  etag?: string;
  body?: unknown;
}

function stub(replies: (url: string, ifNoneMatch: string | null, n: number) => Reply) {
  let n = 0;
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    const reply = replies(url, headers.get("If-None-Match"), n++);
    const status = reply.status ?? 200;
    if (status === 304)
      return new Response(null, { status, headers: { ETag: reply.etag ?? "" } });
    const response = jsonResponse(reply.body ?? {}, status);
    if (reply.etag) response.headers.set("ETag", reply.etag);
    return response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    value: state,
    configurable: true,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  // The clock also runs by itself, so the testing library's own timeouts still fire.
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

describe("usePlayers (7.1)", () => {
  it("loads at once and then asks again on the interval", async () => {
    const fetchMock = stub(() => ({ body: list(["Ann"]), etag: '"1-a"' }));
    const { result } = renderHook(() => usePlayers(QUERY));
    await waitFor(() => expect(result.current.data?.total).toBe(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await tick(PLAYERS_REFRESH_MS - 1000); // (the clock also ticks by itself a little)
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await tick(2000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await tick(PLAYERS_REFRESH_MS);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("sends the last ETag and keeps the rows on a 304", async () => {
    stub((_url, inm, n) =>
      n === 0 ? { body: list(["Ann"]), etag: '"1-a"' } : { status: 304, etag: inm ?? "" },
    );
    const fetchMock = vi.mocked(fetch);
    const { result } = renderHook(() => usePlayers(QUERY));
    await waitFor(() => expect(result.current.data?.total).toBe(1));
    expect(
      new Headers(fetchMock.mock.calls[0][1]?.headers).get("If-None-Match"),
    ).toBeNull();

    await tick(PLAYERS_REFRESH_MS);
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get("If-None-Match")).toBe(
      '"1-a"',
    );
    expect(result.current.data?.players[0].name).toBe("Ann");
    expect(result.current.error).toBeNull();
  });

  it("picks up a changed list on the next tick and keeps rows while loading", async () => {
    let second: (r: Response) => void = () => {};
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        call += 1;
        if (call === 1) {
          const r = jsonResponse(list(["Ann"], 1));
          r.headers.set("ETag", '"1-a"');
          return r;
        }
        return new Promise<Response>((resolve) => (second = resolve));
      }),
    );
    const { result } = renderHook(() => usePlayers(QUERY));
    await waitFor(() => expect(result.current.data?.players[0].name).toBe("Ann"));
    await tick(PLAYERS_REFRESH_MS);
    // the second request is still in flight: the first answer is still shown
    expect(result.current.data?.players[0].name).toBe("Ann");
    await act(async () => {
      const r = jsonResponse(list(["Zed", "Ann"], 2));
      r.headers.set("ETag", '"2-a"');
      second(r);
    });
    await waitFor(() => expect(result.current.data?.total).toBe(2));
  });

  it("does not poll while the page is hidden, and asks again when it is shown", async () => {
    const fetchMock = stub(() => ({ body: list(["Ann"]), etag: '"1-a"' }));
    const { result } = renderHook(() => usePlayers(QUERY));
    await waitFor(() => expect(result.current.data).not.toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => setVisibility("hidden"));
    await tick(PLAYERS_REFRESH_MS * 4);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => setVisibility("visible"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("fetches a changed query at once, without waiting for the interval", async () => {
    const fetchMock = stub((url) => ({
      body: list(url.includes("sort=deaths") ? ["Deaths first"] : ["Frags first"]),
      etag: `"${url.length}"`,
    }));
    const { result, rerender } = renderHook(({ q }) => usePlayers(q), {
      initialProps: { q: QUERY },
    });
    await waitFor(() => expect(result.current.data?.players[0].name).toBe("Frags first"));
    rerender({ q: { ...QUERY, sort: "deaths" } });
    await waitFor(() =>
      expect(result.current.data?.players[0].name).toBe("Deaths first"),
    );
    expect(fetchMock.mock.calls.at(-1)?.[0]).toContain("sort=deaths");
    // a new query is not conditional on the old query's ETag
    expect(
      new Headers(fetchMock.mock.calls.at(-1)?.[1]?.headers).get("If-None-Match"),
    ).toBeNull();
  });

  it("reports an error and recovers on the next tick", async () => {
    stub((_url, _inm, n) =>
      n === 0
        ? {
            status: 503,
            body: { detail: { code: "players_unavailable", message: "off" } },
          }
        : { body: list(["Ann"]), etag: '"1-a"' },
    );
    const { result } = renderHook(() => usePlayers(QUERY));
    await waitFor(() => expect(result.current.error).toBe("off"));
    await tick(PLAYERS_REFRESH_MS);
    await waitFor(() => expect(result.current.data?.total).toBe(1));
    expect(result.current.error).toBeNull();
  });
});
