import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useMatch } from "../api/useMatch";
import { FakeEventSource } from "./fakeEventSource";
import { MATCH_URL, makeMatch } from "./util";

describe("useMatch (5.1)", () => {
  it("opens the match stream on mount and closes it on unmount", async () => {
    const { unmount } = renderHook(() => useMatch());
    await waitFor(() => expect(FakeEventSource.byUrl(MATCH_URL)).toBeTruthy());
    const source = FakeEventSource.byUrl(MATCH_URL)!;
    expect(source.readyState).not.toBe(2);
    unmount();
    expect(source.readyState).toBe(2); // closed: the server stops polling with it
  });

  it("does not open the stream before it is mounted", () => {
    expect(FakeEventSource.allByUrl(MATCH_URL)).toHaveLength(0);
  });

  it("applies every event it receives", async () => {
    const { result } = renderHook(() => useMatch());
    await waitFor(() => expect(FakeEventSource.byUrl(MATCH_URL)).toBeTruthy());
    expect(result.current.match).toBeNull();
    act(() => FakeEventSource.byUrl(MATCH_URL)!.emit(makeMatch({ map: "atelier" })));
    expect(result.current.match?.map).toBe("atelier");
    act(() => FakeEventSource.byUrl(MATCH_URL)!.emit(makeMatch({ map: "boil" })));
    expect(result.current.match?.map).toBe("boil");
    expect(result.current.stale).toBe(false);
  });

  it("marks a held state stale when the connection drops, and fresh again on reconnect", async () => {
    const { result } = renderHook(() => useMatch());
    await waitFor(() => expect(FakeEventSource.byUrl(MATCH_URL)).toBeTruthy());
    act(() => FakeEventSource.byUrl(MATCH_URL)!.emit(makeMatch()));
    expect(result.current.stale).toBe(false);
    act(() => FakeEventSource.byUrl(MATCH_URL)!.fail());
    expect(result.current.stale).toBe(true);
    await waitFor(() => expect(FakeEventSource.allByUrl(MATCH_URL).length).toBe(2), {
      timeout: 3000,
    });
    act(() => FakeEventSource.byUrl(MATCH_URL)!.emit(makeMatch({ map: "boil" })));
    await waitFor(() => expect(result.current.stale).toBe(false));
    expect(result.current.match?.map).toBe("boil");
  });
});
