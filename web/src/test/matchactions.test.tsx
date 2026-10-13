import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Dashboard } from "../sections/Dashboard";
import { jsonResponse, makeStatus, pushStatus, renderSection, stubFetch } from "./util";

afterEach(() => vi.unstubAllGlobals());

const humans = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    ent: i + 1,
    name: `p${i}`,
    plain_name: `p${i}`,
    bot: false,
  }));

const accepted = (kind: "skip" | "restart") =>
  jsonResponse({ id: 1, kind, map: null, state: "pending" }, 202);

describe("map actions on the dashboard (6.4)", () => {
  it("are disabled unless the server is running", async () => {
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "stopped" }));
    expect(await screen.findByRole("button", { name: "Skip map" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restart match" })).toBeDisabled();
  });

  it("run at once when nobody is connected", async () => {
    const fetchMock = stubFetch(() => accepted("skip"));
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "running", map: "boil", gametype: "dm" }));
    await userEvent.click(await screen.findByRole("button", { name: "Skip map" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith("/api/match/skip", expect.anything());
  });

  it("do not count bots as players to confirm for", async () => {
    const fetchMock = stubFetch(() => accepted("restart"));
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({
        state: "running",
        bot_count: 1,
        players: [{ id: 1, ent: 1, name: "[BOT]x", plain_name: "[BOT]x", bot: true }],
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Restart match" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith("/api/match/restart", expect.anything());
  });

  it("ask first, stating how many are in the match, and act only on confirmation", async () => {
    const fetchMock = stubFetch(() => accepted("skip"));
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({ state: "running", human_count: 2, players: humans(2) }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Skip map" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("2 players are in the match");
    expect(fetchMock).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(fetchMock).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Skip map" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Skip anyway",
      }),
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/match/skip", expect.anything());
  });

  it("say a single player is in the match", async () => {
    stubFetch(() => accepted("restart"));
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({ state: "running", human_count: 1, players: humans(1) }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Restart match" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(
      "1 player is in the match",
    );
  });

  it("show a pending action to every client and lock the buttons", async () => {
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({
        state: "running",
        action: { id: 4, kind: "skip", map: null, state: "pending" },
      }),
    );
    expect(await screen.findByText("Skipping the map…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip map" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restart match" })).toBeDisabled();
  });

  it("show that an action completed, and unlock the buttons", async () => {
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({
        state: "running",
        action: { id: 4, kind: "goto", map: "warfare", state: "done" },
      }),
    );
    expect(await screen.findByText("Now playing warfare")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip map" })).toBeEnabled();
  });

  it("show that an action did not complete", async () => {
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({
        state: "running",
        action: { id: 4, kind: "skip", map: null, state: "timed_out" },
      }),
    );
    const note = await screen.findByText(/did not complete/);
    expect(note).toHaveClass("is-warn");
    expect(screen.getByRole("button", { name: "Skip map" })).toBeEnabled();
  });

  it("report a rejected action with the server's reason", async () => {
    stubFetch(() =>
      jsonResponse(
        {
          detail: {
            code: "action_in_progress",
            message: "a map action is already in progress",
          },
        },
        409,
      ),
    );
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "running" }));
    await userEvent.click(await screen.findByRole("button", { name: "Skip map" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already in progress");
  });
});
