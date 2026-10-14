import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PanelVersionProvider,
  UPGRADE_POLL_MS,
  VERSION_POLL_MS,
  usePanelVersion,
} from "../api/usePanelVersion";
import { makePanelVersion, makeUpdate, makeUpgrade, mockPanelFetch } from "./util";

function Probe() {
  const { info } = usePanelVersion();
  if (!info) return <p>no info</p>;
  return (
    <p data-testid="info">
      {info.current}|{info.latest}|{info.upgrade?.state ?? "none"}|
      {info.upgrade?.error ?? ""}
    </p>
  );
}

function mount() {
  return render(
    <PanelVersionProvider>
      <Probe />
    </PanelVersionProvider>,
  );
}

const calls = (fn: ReturnType<typeof mockPanelFetch>, path: string) =>
  fn.mock.calls.filter(([url]) => url === path).length;

describe("usePanelVersion (7.2)", () => {
  const original = window.location;
  let reload: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...original, reload },
    });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Object.defineProperty(window, "location", { configurable: true, value: original });
  });

  it("loads the version on mount and polls it every five minutes", async () => {
    const fetchFn = mockPanelFetch({ "GET /api/panel/version": makePanelVersion() });
    mount();
    expect(await screen.findByTestId("info")).toHaveTextContent("0.2.0|0.2.0|none");
    expect(calls(fetchFn, "/api/panel/version")).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(VERSION_POLL_MS - 1000);
    });
    expect(calls(fetchFn, "/api/panel/version")).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(calls(fetchFn, "/api/panel/version")).toBe(2);
    // and it never touches /health while nothing is in flight
    expect(calls(fetchFn, "/health")).toBe(0);
  });

  it("picks up a newly published release on the next poll without a reload", async () => {
    let answer = makePanelVersion();
    mockPanelFetch({ "GET /api/panel/version": () => answer });
    mount();
    expect(await screen.findByTestId("info")).toHaveTextContent("0.2.0|0.2.0|none");
    answer = makeUpdate();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(VERSION_POLL_MS);
    });
    expect(screen.getByTestId("info")).toHaveTextContent("0.2.0|0.3.0|none");
    expect(reload).not.toHaveBeenCalled();
  });

  it("keeps the last result when a poll fails", async () => {
    let fail = false;
    mockPanelFetch({
      "GET /api/panel/version": () => {
        if (fail) throw new TypeError("connection refused");
        return makeUpdate();
      },
    });
    mount();
    expect(await screen.findByTestId("info")).toHaveTextContent("0.2.0|0.3.0");
    fail = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(VERSION_POLL_MS);
    });
    expect(screen.getByTestId("info")).toHaveTextContent("0.2.0|0.3.0");
  });

  it("polls every three seconds while an upgrade is in flight", async () => {
    const fetchFn = mockPanelFetch({
      "GET /api/panel/version": makeUpdate({ upgrade: makeUpgrade() }),
      "GET /health": { status: "ok", version: "0.2.0" },
    });
    mount();
    expect(await screen.findByTestId("info")).toHaveTextContent("pending");
    const versionBefore = calls(fetchFn, "/api/panel/version");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS * 3);
    });
    expect(calls(fetchFn, "/health")).toBe(3);
    // the same old panel answers /health, so each tick re-reads the version
    expect(calls(fetchFn, "/api/panel/version")).toBe(versionBefore + 3);
  });

  it("reloads once the panel comes back as a different version", async () => {
    let phase: "old" | "down" | "new" = "old";
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({
        upgrade: makeUpgrade({ state: "running" }),
      }),
      "GET /health": () => {
        if (phase === "down") throw new TypeError("connection refused");
        return { status: "ok", version: phase === "new" ? "0.3.0" : "0.2.0" };
      },
    });
    mount();
    await screen.findByTestId("info");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS);
    });
    expect(reload).not.toHaveBeenCalled(); // still the version the page loaded with

    phase = "down";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS * 2);
    });
    expect(reload).not.toHaveBeenCalled(); // connection errors are expected and ignored

    phase = "new";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS);
    });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not reload when the panel comes back as the same version", async () => {
    let phase: "up" | "down" = "down";
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({ upgrade: makeUpgrade() }),
      "GET /health": () => {
        if (phase === "down") throw new TypeError("connection refused");
        return { status: "ok", version: "0.2.0" };
      },
    });
    mount();
    await screen.findByTestId("info");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS * 2);
    });
    phase = "up"; // a rolled-back panel: the same version again
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS * 2);
    });
    expect(reload).not.toHaveBeenCalled();
  });

  it("picks up a failed outcome without a reload and stops following", async () => {
    let answer = makeUpdate({ upgrade: makeUpgrade() });
    const fetchFn = mockPanelFetch({
      "GET /api/panel/version": () => answer,
      "GET /health": { status: "ok", version: "0.2.0" },
    });
    mount();
    expect(await screen.findByTestId("info")).toHaveTextContent("pending");

    answer = makeUpdate({
      upgrade: makeUpgrade({ state: "failed", error: "installer exited 1" }),
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS);
    });
    expect(screen.getByTestId("info")).toHaveTextContent("failed|installer exited 1");

    const health = calls(fetchFn, "/health");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS * 3);
    });
    expect(calls(fetchFn, "/health")).toBe(health); // no longer watching
    expect(reload).not.toHaveBeenCalled();
  });
});
