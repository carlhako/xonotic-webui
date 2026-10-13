import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Console } from "../sections/Console";
import { FakeEventSource } from "./fakeEventSource";
import {
  CONSOLE_URL,
  jsonResponse,
  makeStatus,
  pushConsole,
  pushStatus,
  renderSection,
  stubFetch,
} from "./util";

afterEach(() => vi.unstubAllGlobals());

describe("console (8.6)", () => {
  it("disables the command input while the server is not running", async () => {
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "stopped" }));
    expect(await screen.findByLabelText("console command")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("streams output and shows a submitted command and its response", async () => {
    const fetchMock = stubFetch(() => new Response(null, { status: 204 }));
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "running" }));
    await pushConsole({ seq: 1, kind: "output", text: "^7Server listening" });
    expect(await screen.findByText("Server listening")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("console command"), "status 1");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/console/command",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ command: "status 1" }),
      }),
    );
    expect(screen.getByLabelText("console command")).toHaveValue("");

    await pushConsole({ seq: 2, kind: "command", text: "status 1" });
    await pushConsole({ seq: 3, kind: "output", text: "^7players:  0 active (8 max)" });
    expect(await screen.findByText("> status 1")).toBeInTheDocument();
    expect(
      screen.getByText("players: 0 active (8 max)", { exact: false }),
    ).toBeInTheDocument();
  });

  it("shows a rejected command's error and keeps the draft", async () => {
    stubFetch(() =>
      jsonResponse(
        { detail: { code: "not_running", message: "the server is not running" } },
        409,
      ),
    );
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "running" }));
    await userEvent.type(await screen.findByLabelText("console command"), "status 1");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the server is not running",
    );
    expect(screen.getByLabelText("console command")).toHaveValue("status 1");
  });

  it("renders colour codes as colour and never shows the code characters", async () => {
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "running" }));
    await pushConsole({
      seq: 1,
      kind: "output",
      text: "^7:join:1:1:127.0.0.1:^1Red^xf80Orange^7 Pl:ay^^er",
    });
    const log = await screen.findByRole("log");
    await waitFor(() =>
      expect(log.textContent).toContain(":join:1:1:127.0.0.1:RedOrange Pl:ay^er"),
    );
    expect(log.textContent).not.toMatch(/\^[0-9x]/);
    const red = screen.getByText("Red");
    expect(red).toHaveStyle({ color: "rgb(255, 0, 0)" });
  });

  it("marks where each server run begins", async () => {
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "running" }));
    await pushConsole({ seq: 1, kind: "output", text: "^7first run" });
    await pushConsole({ seq: 2, kind: "marker", text: "— server starting —" });
    await pushConsole({ seq: 3, kind: "output", text: "^7second run" });
    const marker = await screen.findByText("— server starting —");
    expect(marker).toHaveClass("cl-marker");
    expect(screen.getByText("first run")).toBeInTheDocument();
    expect(screen.getByText("second run")).toBeInTheDocument();
  });

  it("does not duplicate lines when a reconnect replays history", async () => {
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "running" }));
    await pushConsole({ seq: 1, kind: "output", text: "line one" });
    await pushConsole({ seq: 2, kind: "output", text: "line two" });
    await pushConsole({ seq: 2, kind: "output", text: "line two" }); // a replayed frame
    await screen.findByText("line two");
    expect(screen.getAllByText("line two")).toHaveLength(1);
  });

  it("rebuilds from scratch after reconnecting, even if the panel restarted its numbering", async () => {
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "running" }));
    await pushConsole({ seq: 500, kind: "output", text: "before restart" });
    await screen.findByText("before restart");

    // the panel restarted: a new connection replays a short history from seq 1
    act(() => FakeEventSource.byUrl(CONSOLE_URL)!.fail());
    await waitFor(
      () => expect(FakeEventSource.allByUrl(CONSOLE_URL).length).toBeGreaterThan(1),
      {
        timeout: 3000,
      },
    );
    await pushConsole({ seq: 1, kind: "output", text: "after restart" });
    expect(await screen.findByText("after restart")).toBeInTheDocument();
    expect(screen.queryByText("before restart")).toBeNull();
  });

  it("pauses auto-scroll when scrolled up and offers a jump to the latest", async () => {
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "running" }));
    await pushConsole({ seq: 1, kind: "output", text: "one" });
    const log = await screen.findByRole("log");
    // jsdom has no layout: simulate a user scrolled well away from the bottom
    Object.defineProperty(log, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(log, "clientHeight", { value: 100, configurable: true });
    log.scrollTop = 0;
    fireEvent.scroll(log);

    const paused = await screen.findByRole("button", { name: /Auto-scroll paused/ });
    await userEvent.click(paused);
    expect(screen.queryByRole("button", { name: /Auto-scroll paused/ })).toBeNull();
  });

  it("disables input while disconnected", async () => {
    renderSection(<Console />);
    await pushStatus(makeStatus({ state: "running" }));
    expect(await screen.findByLabelText("console command")).toBeEnabled();
    act(() => FakeEventSource.byUrl(CONSOLE_URL)!.fail());
    await waitFor(() => expect(screen.getByLabelText("console command")).toBeDisabled());
    expect(screen.getByText("disconnected")).toBeInTheDocument();
  });
});
