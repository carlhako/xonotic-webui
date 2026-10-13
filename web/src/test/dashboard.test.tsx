import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Dashboard } from "../sections/Dashboard";
import { jsonResponse, makeStatus, pushStatus, renderSection, stubFetch } from "./util";

afterEach(() => vi.unstubAllGlobals());

const player = (ent: number, name: string, bot = false, plain = name) => ({
  id: ent,
  ent,
  name,
  plain_name: plain,
  bot,
});

describe("dashboard state and controls (8.4)", () => {
  it("stopped: start is enabled, stop and restart are not", async () => {
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "stopped" }));
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Stop" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restart" })).toBeDisabled();
  });

  it("running: stop and restart are enabled, start is not", async () => {
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "running" }));
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Restart" })).toBeEnabled();
  });

  it.each(["starting", "stopping"] as const)(
    "%s: every control is disabled and the transition is shown",
    async (state) => {
      renderSection(<Dashboard />);
      await pushStatus(makeStatus({ state }));
      expect(await screen.findByRole("status")).toHaveTextContent(
        state === "starting" ? "Starting…" : "Stopping…",
      );
      for (const name of ["Start", "Stop", "Restart"]) {
        expect(screen.getByRole("button", { name })).toBeDisabled();
      }
    },
  );

  it("shows map, gametype and humans and bots separately", async () => {
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({
        state: "running",
        map: "atelier",
        gametype: "dm",
        human_count: 2,
        bot_count: 1,
        players: [
          player(1, "^1Red^7Name", false, "RedName"),
          player(2, "Plain", false),
          player(3, "[BOT]Toxic", true),
        ],
      }),
    );
    expect(await screen.findByText("atelier")).toBeInTheDocument();
    expect(screen.getByText("dm")).toBeInTheDocument();
    expect(screen.getByText("Players").parentElement).toHaveTextContent(
      "2 humans, 1 bot",
    );
    const list = screen.getByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    // colour codes are rendered, never shown raw
    expect(within(list).getByText("Red")).toBeInTheDocument();
    expect(list.textContent).not.toContain("^");
    expect(within(list).getByText("bot")).toBeInTheDocument();
  });

  it("does not guess an unknown map or gametype", async () => {
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "running", map: null, gametype: null }));
    expect((await screen.findAllByTitle("not known yet")).length).toBe(2);
  });

  it("warns instead of presenting an empty roster when the event log is unavailable", async () => {
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "running", event_log: "unavailable" }));
    expect(
      await screen.findByText(/Live player tracking is unavailable/),
    ).toBeInTheDocument();
  });

  it("reports a rejected operation with the error returned", async () => {
    stubFetch(() =>
      jsonResponse(
        { detail: { code: "game_not_installed", message: "the game is not installed" } },
        503,
      ),
    );
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "stopped" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the game is not installed",
    );
  });

  it("calls the lifecycle endpoint and does not duplicate a request while busy", async () => {
    let release: (r: Response) => void = () => {};
    const fetchMock = stubFetch(() => {
      throw new Error("unused");
    });
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => (release = resolve)),
    );
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "stopped" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/lifecycle/start", expect.anything());
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
    await act(async () => release(jsonResponse(makeStatus({ state: "running" }))));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows the last crash and an abandoned restart in the browser's time", async () => {
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({
        state: "stopped",
        restart_abandoned: true,
        last_crash: { at: "2026-03-01T23:30:00+00:00", exit_code: 139 },
      }),
    );
    expect(
      await screen.findByText(/abandoned after repeated crashes/),
    ).toBeInTheDocument();
    expect(screen.getByText(/exit status 139/)).toBeInTheDocument();
    expect(screen.getByText(/exit status 139/).textContent).toMatch(/2026/);
  });
});

describe("stop and restart confirmation (8.5)", () => {
  it("asks first when humans are connected, stating how many, and acts only on confirm", async () => {
    const fetchMock = stubFetch(() => jsonResponse(makeStatus({ state: "stopped" })));
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({
        state: "running",
        human_count: 3,
        players: [player(1, "a"), player(2, "b"), player(3, "c")],
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("3 players will be disconnected");
    expect(fetchMock).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Stop anyway" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/lifecycle/stop", expect.anything());
  });

  it("cancelling leaves the server alone", async () => {
    const fetchMock = stubFetch(() => jsonResponse(makeStatus()));
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({ state: "running", human_count: 1, players: [player(1, "a")] }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Restart" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("1 player will be disconnected");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("proceeds without a confirmation when no humans are connected", async () => {
    const fetchMock = stubFetch(() => jsonResponse(makeStatus({ state: "stopped" })));
    renderSection(<Dashboard />);
    // bots do not count as players to warn about
    await pushStatus(
      makeStatus({
        state: "running",
        human_count: 0,
        bot_count: 1,
        players: [player(1, "x", true)],
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith("/api/lifecycle/stop", expect.anything());
  });
});
