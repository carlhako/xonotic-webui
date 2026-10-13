import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FakeEventSource } from "./fakeEventSource";
import { STATUS_URL, makeStatus, pushStatus, renderApp } from "./util";

describe("connection loss and recovery (8.3)", () => {
  it("shows a banner while unreachable and clears it, with fresh state, on reconnect", async () => {
    renderApp();
    await pushStatus(makeStatus({ state: "running", map: "atelier", gametype: "dm" }));
    expect(await screen.findByText("atelier")).toBeInTheDocument();
    expect(screen.queryByText(/Disconnected from the panel/)).toBeNull();

    act(() => FakeEventSource.byUrl(STATUS_URL)!.fail());
    expect(await screen.findByText(/Disconnected from the panel/)).toBeInTheDocument();

    // the hook retries with a new connection for the same URL
    await waitFor(
      () => expect(FakeEventSource.allByUrl(STATUS_URL).length).toBeGreaterThan(1),
      {
        timeout: 3000,
      },
    );
    // the panel came back with different state; the display is replaced, not merged
    act(() =>
      FakeEventSource.byUrl(STATUS_URL)!.emit(
        makeStatus({ state: "stopped", map: null, gametype: null }),
      ),
    );
    await waitFor(() =>
      expect(screen.queryByText(/Disconnected from the panel/)).toBeNull(),
    );
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.queryByText("atelier")).toBeNull();
  });

  it("disables controls that change the server until reconnection", async () => {
    renderApp();
    await pushStatus(makeStatus({ state: "running" }));
    const stop = await screen.findByRole("button", { name: "Stop" });
    expect(stop).toBeEnabled();

    act(() => FakeEventSource.byUrl(STATUS_URL)!.fail());
    await screen.findByText(/Disconnected from the panel/);
    expect(screen.getByRole("button", { name: "Stop" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restart" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();

    await waitFor(
      () => expect(FakeEventSource.allByUrl(STATUS_URL).length).toBeGreaterThan(1),
      {
        timeout: 3000,
      },
    );
    // reconnected but no fresh snapshot yet: still not authoritative
    expect(screen.getByRole("button", { name: "Stop" })).toBeDisabled();
    act(() => FakeEventSource.byUrl(STATUS_URL)!.emit(makeStatus({ state: "running" })));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled(),
    );
  });
});
