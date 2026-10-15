import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Dashboard } from "../sections/Dashboard";
import type { Match } from "../api/client";
import {
  makeBoardPlayer,
  makeMatch,
  makeStatus,
  pushMatch,
  pushStatus,
  renderSection,
} from "./util";

afterEach(() => vi.unstubAllGlobals());

const running = () => makeStatus({ state: "running", map: "atelier", gametype: "dm" });

function clock(overrides: Partial<Match["clock"]>): Match {
  const base = makeMatch();
  return { ...base, clock: { ...base.clock, ...overrides } };
}

async function showMatch(match: Match) {
  renderSection(<Dashboard />);
  await pushStatus(running());
  await pushMatch(match);
}

function clockCard(): HTMLElement {
  return screen.getByText("Match clock").parentElement!;
}

describe("match clock card (5.2)", () => {
  it("playing: time left, the limit and the score limit", async () => {
    await showMatch(makeMatch());
    const card = clockCard();
    expect(card).toHaveTextContent("6:40");
    expect(card).toHaveTextContent("left · limit 10:00");
    expect(card).toHaveTextContent("Score limit 30 frags");
    expect(within(card).queryByText("paused")).not.toBeInTheDocument();
  });

  it("playing with no time limit counts up", async () => {
    await showMatch(clock({ time_limit_s: null, left_s: null, elapsed_s: 125 }));
    expect(clockCard()).toHaveTextContent("2:05");
    expect(clockCard()).toHaveTextContent("elapsed · no time limit");
  });

  it("countdown: starting in m:ss", async () => {
    await showMatch(clock({ phase: "countdown", left_s: 12, elapsed_s: null }));
    expect(clockCard()).toHaveTextContent("Starting in 0:12");
  });

  it("warmup shows the phase and the time left when it has a limit", async () => {
    await showMatch(clock({ phase: "warmup", left_s: 95, elapsed_s: null }));
    expect(clockCard()).toHaveTextContent("Warmup");
    expect(clockCard()).toHaveTextContent("1:35 left");
  });

  it("overtime shows the phase and the time left", async () => {
    await showMatch(clock({ phase: "overtime", left_s: 70, overtimes: 1 }));
    expect(clockCard()).toHaveTextContent("Overtime");
    expect(clockCard()).toHaveTextContent("1:10 left");
  });

  it("match over", async () => {
    await showMatch(clock({ phase: "ended", left_s: null, elapsed_s: null }));
    expect(clockCard()).toHaveTextContent("Match over");
  });

  it("paused: a badge, with the time kept", async () => {
    await showMatch(clock({ paused: true }));
    expect(within(clockCard()).getByText("paused")).toBeInTheDocument();
    expect(clockCard()).toHaveTextContent("6:40");
  });

  it("no score limit", async () => {
    await showMatch(makeMatch({ score_limit: { value: null, unit: "frags" } }));
    expect(clockCard()).toHaveTextContent("No score limit");
  });

  it("the score limit names what it counts", async () => {
    await showMatch(makeMatch({ score_limit: { value: 10, unit: "captures" } }));
    expect(clockCard()).toHaveTextContent("Score limit 10 captures");
  });

  it("clock unavailable is said in its place", async () => {
    await showMatch(
      clock({
        available: false,
        phase: null,
        left_s: null,
        elapsed_s: null,
        time_limit_s: null,
      }),
    );
    expect(clockCard()).toHaveTextContent("Clock unavailable");
  });

  it("updates in place as new states arrive", async () => {
    await showMatch(makeMatch());
    expect(clockCard()).toHaveTextContent("6:40");
    await pushMatch(clock({ left_s: 399 }));
    expect(clockCard()).toHaveTextContent("6:39");
  });
});

describe("scoreboard (5.3)", () => {
  const dm = (): Match =>
    makeMatch({
      scoreboard: {
        ...makeMatch().scoreboard,
        players: [
          makeBoardPlayer("^1Red^7Name", { score: 12, kills: 14, deaths: 6 }, { ent: 1 }),
          makeBoardPlayer(
            "[BOT]Toxic",
            { score: 8.4, kills: 9, deaths: 7 },
            { ent: 2, bot: true, ping: 0, time_s: 3725 },
          ),
        ],
      },
    });

  it("deathmatch: players in the game's order, with its columns, ping and time", async () => {
    await showMatch(dm());
    const table = screen.getByRole("table", { name: "Scoreboard" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual(["#", "Player", "Score", "Kills", "Deaths", "Ping", "Time"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(/^1Red\s*Name12146202m 5s$/);
    // fractional values are rounded for display, and the second row is ranked 2
    expect(rows[1]).toHaveTextContent("2");
    expect(rows[1]).toHaveTextContent("8");
    expect(rows[1]).toHaveTextContent("1h 2m");
  });

  it("renders game colours and never the raw codes", async () => {
    await showMatch(dm());
    const table = screen.getByRole("table", { name: "Scoreboard" });
    expect(within(table).getByText("Red")).toBeInTheDocument();
    expect(table.textContent).not.toContain("^");
  });

  it("marks bots", async () => {
    await showMatch(dm());
    const table = screen.getByRole("table", { name: "Scoreboard" });
    expect(within(table).getAllByText("bot")).toHaveLength(1);
  });

  it("replaces the players online list", async () => {
    await showMatch(dm());
    expect(screen.queryByText("Players online")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Scoreboard" })).toBeInTheDocument();
  });

  it("team game: a coloured total row above each team's players", async () => {
    const base = makeMatch();
    await showMatch(
      makeMatch({
        gametype: "tdm",
        scoreboard: {
          ...base.scoreboard,
          teams: [
            { team: 5, color: "red", values: { score: 21 } },
            { team: 14, color: "blue", values: { score: 17 } },
          ],
          players: [
            makeBoardPlayer(
              "Ann",
              { score: 12, kills: 12, deaths: 3 },
              { ent: 1, team: 5 },
            ),
            makeBoardPlayer(
              "Bob",
              { score: 9, kills: 9, deaths: 5 },
              { ent: 2, team: 14 },
            ),
            makeBoardPlayer("Cy", { score: 9, kills: 9, deaths: 5 }, { ent: 3, team: 5 }),
          ],
        },
      }),
    );
    const table = screen.getByRole("table", { name: "Scoreboard" });
    const bodies = within(table).getAllByRole("rowgroup").slice(1);
    expect(bodies).toHaveLength(2);
    const red = within(bodies[0]).getAllByRole("row");
    expect(red[0]).toHaveClass("team-row", "team-red");
    expect(red[0]).toHaveTextContent("Red");
    expect(red[0]).toHaveTextContent("21");
    expect(red).toHaveLength(3); // header + Ann + Cy
    expect(within(red[1]).getByText("Ann")).toBeInTheDocument();
    expect(within(red[2]).getByText("Cy")).toBeInTheDocument();
    const blue = within(bodies[1]).getAllByRole("row");
    expect(blue[0]).toHaveClass("team-blue");
    expect(blue[0]).toHaveTextContent("17");
    expect(within(blue[1]).getByText("Bob")).toBeInTheDocument();
  });

  it("spectators are on a muted line underneath", async () => {
    const base = makeMatch();
    await showMatch(
      makeMatch({
        scoreboard: {
          ...base.scoreboard,
          players: [makeBoardPlayer("Ann", { score: 1, kills: 1, deaths: 0 })],
          spectators: [
            { ent: 4, name: "^2Watcher", plain_name: "Watcher", bot: false },
            { ent: 5, name: "Other", plain_name: "Other", bot: false },
          ],
        },
      }),
    );
    const line = screen.getByText(/Spectators:/);
    expect(line).toHaveClass("muted");
    expect(line).toHaveTextContent("Spectators: Watcher, Other");
    const table = screen.getByRole("table", { name: "Scoreboard" });
    expect(within(table).queryByText("Watcher")).not.toBeInTheDocument();
  });

  it("scoreboard unavailable: players online is shown with the reason, and the clock stays", async () => {
    renderSection(<Dashboard />);
    await pushStatus(
      makeStatus({
        state: "running",
        human_count: 1,
        players: [{ id: 1, ent: 1, name: "Ann", plain_name: "Ann", bot: false }],
      }),
    );
    const base = makeMatch();
    await pushMatch({
      ...base,
      scoreboard: { ...base.scoreboard, available: false, columns: [] },
    });
    expect(screen.getByRole("heading", { name: "Players online" })).toBeInTheDocument();
    expect(screen.getByText(/Scoreboard unavailable/)).toBeInTheDocument();
    expect(within(screen.getByRole("list")).getByText("Ann")).toBeInTheDocument();
    expect(clockCard()).toHaveTextContent("6:40");
    expect(screen.queryByRole("table", { name: "Scoreboard" })).not.toBeInTheDocument();
  });

  it("no match: neither the clock nor the scoreboard, and no reason is given", async () => {
    renderSection(<Dashboard />);
    await pushStatus(makeStatus({ state: "stopped" }));
    await pushMatch(
      makeMatch({
        live: false,
        map: null,
        gametype: null,
        clock: { ...makeMatch().clock, available: false, phase: null },
        scoreboard: {
          available: false,
          columns: [],
          players: [],
          spectators: [],
          teams: [],
        },
      }),
    );
    expect(screen.queryByText("Match clock")).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Scoreboard" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Scoreboard unavailable/)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Players online" })).toBeInTheDocument();
  });

  it("before the first state arrives there is no clock or scoreboard", async () => {
    renderSection(<Dashboard />);
    await pushStatus(running());
    expect(screen.queryByText("Match clock")).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Scoreboard" })).not.toBeInTheDocument();
  });
});
