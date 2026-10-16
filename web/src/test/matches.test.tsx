import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MatchDetail, MatchSummary } from "../api/client";
import { Matches } from "../sections/Matches";
import {
  jsonResponse,
  makeHistoryPlayer,
  makeMap,
  makeMatchDetail,
  makeMatchSummary,
  makePlayerDetail,
  stubFetch,
} from "./util";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function open(route = "/matches") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Matches />
      <Where />
    </MemoryRouter>,
  );
}

const DM = makeMatchSummary({
  id: 3,
  started_at: 1_790_000_300,
  map: "boil",
  gametype: "dm",
  duration: 725,
  humans: 1,
  bots: 3,
  vs_bots: true,
});
const TDM = makeMatchSummary({
  id: 2,
  started_at: 1_790_000_200,
  map: "atelier",
  gametype: "tdm",
  duration: 900,
  humans: 2,
  bots: 0,
  vs_bots: false,
  winner: { kind: "team", team: 14, color: "blue" },
});
const CRASH = makeMatchSummary({
  id: 1,
  started_at: 1_790_000_100,
  map: "boil",
  gametype: "unknown",
  duration: null,
  outcome: "no_report",
  winner: null,
});

interface Server {
  matches?: (
    params: URLSearchParams,
  ) => { total?: number; matches: MatchSummary[] } | Response;
  detail?: (id: number) => Response;
}

function server({ matches, detail }: Server = {}) {
  return stubFetch((url) => {
    const [path, query = ""] = url.split("?");
    if (path === "/api/matches") {
      const params = new URLSearchParams(query);
      const body = matches ? matches(params) : { matches: [DM, TDM, CRASH] };
      if (body instanceof Response) return body;
      const response = jsonResponse({
        revision: 1,
        total: body.total ?? body.matches.length,
        matches: body.matches,
      });
      response.headers.set("ETag", `"1--${query.length}"`);
      return response;
    }
    const m = path.match(/^\/api\/matches\/(\d+)$/);
    if (m) {
      const id = Number(m[1]);
      return detail ? detail(id) : jsonResponse(makeMatchDetail({ id }));
    }
    if (path === "/api/maps") {
      return jsonResponse({
        maps: [makeMap({ name: "boil" }), makeMap({ name: "atelier" })],
      });
    }
    if (path === "/api/gametypes") {
      return jsonResponse({
        effective: "dm",
        running: "dm",
        selected: null,
        gametypes: ["dm", "tdm", "ctf"].map((id) => ({
          id,
          name: id,
          map_count: 5,
          offered: true,
          score_unit: "frags",
        })),
      });
    }
    const p = path.match(/^\/api\/players\/(\d+)$/);
    if (p) {
      const id = Number(p[1]);
      return jsonResponse(
        makePlayerDetail({ id, name: id === 7 ? "^1Ace" : "Bob", plain_name: "x" }),
      );
    }
    throw new Error(`unexpected request: ${url}`);
  });
}

function lastQuery(fn: ReturnType<typeof server>): URLSearchParams {
  const calls = fn.mock.calls.filter(([u]) => String(u).startsWith("/api/matches?"));
  return new URLSearchParams(String(calls.at(-1)?.[0]).split("?")[1]);
}

const where = () => screen.getByTestId("where").textContent;

/** The first table row whose map cell is `map`. */
async function rowFor(map: string): Promise<HTMLElement> {
  const cells = await screen.findAllByText(map, { selector: "td" });
  return cells[0].closest("tr") as HTMLElement;
}

describe("the Matches section (7.2)", () => {
  it("lists the matches in the order the API gives, newest first, with every column", async () => {
    server();
    open();
    await screen.findByRole("table", { name: "Matches" });
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent?.trim())).toEqual(
      ["Started", "Map", "Gametype", "Duration", "Outcome", "Players", "Winner"],
    );

    const cells = within(rows[0]).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("boil");
    expect(cells[2]).toHaveTextContent("dm");
    expect(cells[3]).toHaveTextContent("12m 5s");
    expect(cells[4]).toHaveTextContent("Finished");
    expect(cells[5]).toHaveTextContent("1 + 3 bots");
    expect(cells[5]).toHaveTextContent("vs bots");
    expect(cells[6]).toHaveTextContent("Ace");
    // colour codes are rendered, never shown
    expect(screen.queryByText(/\^1/)).toBeNull();

    // a team game: the team's name, and no vs-bots tag with two humans
    const tdm = within(rows[1]).getAllByRole("cell");
    expect(tdm[5]).toHaveTextContent("2 humans");
    expect(tdm[5]).not.toHaveTextContent("vs bots");
    expect(tdm[6]).toHaveTextContent("Blue");

    // no report: no duration, no winner
    const crash = within(rows[2]).getAllByRole("cell");
    expect(crash[3]).toHaveTextContent("–");
    expect(crash[4]).toHaveTextContent("No report");
    expect(crash[6]).toHaveTextContent("–");
  });

  it("shows each outcome and a winner's other winners", async () => {
    server({
      matches: () => ({
        matches: [
          makeMatchSummary({ id: 5, outcome: "in_progress", winner: null }),
          makeMatchSummary({ id: 4, outcome: "cut_short", winner: null }),
          makeMatchSummary({
            id: 3,
            winner: {
              kind: "player",
              player_id: 7,
              name: "^1Ace",
              plain_name: "Ace",
              is_bot: false,
              others: 2,
            },
          }),
        ],
      }),
    });
    open();
    await screen.findByRole("table", { name: "Matches" });
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("Cut short")).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[2]).getAllByRole("cell")[6]).toHaveTextContent("Ace +2");
  });

  it("says so when nothing has been recorded, not an empty table", async () => {
    server({ matches: () => ({ matches: [] }) });
    open();
    expect(
      await screen.findByText(/No matches have been recorded yet/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Matches" })).toBeNull();
  });

  it("says no match fits when a filter is on and nothing matches", async () => {
    server({ matches: () => ({ matches: [] }) });
    open("/matches?map=boil");
    expect(
      await screen.findByText("No matches match these filters."),
    ).toBeInTheDocument();
  });

  it("says player history is not being recorded when the API answers 503", async () => {
    server({
      matches: () =>
        jsonResponse(
          {
            detail: {
              code: "players_unavailable",
              message: "player history is not being recorded",
            },
          },
          503,
        ),
    });
    open();
    expect(
      await screen.findByText("Player history is not being recorded."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("filters by map and by gametype, in the URL and in the request", async () => {
    const user = userEvent.setup();
    const fetchMock = server();
    open();
    await screen.findByRole("table", { name: "Matches" });
    expect(lastQuery(fetchMock).get("map")).toBeNull();

    const map = screen.getByRole("combobox", { name: "Map" });
    await waitFor(() => expect(within(map).getAllByRole("option")).toHaveLength(3));
    await user.selectOptions(map, "boil");
    await waitFor(() => expect(lastQuery(fetchMock).get("map")).toBe("boil"));
    expect(where()).toBe("/matches?map=boil");

    const gametype = screen.getByRole("combobox", { name: "Gametype" });
    await waitFor(() =>
      expect(
        within(gametype)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["All gametypes", "dm", "tdm", "ctf", "unknown"]),
    );
    await user.selectOptions(gametype, "ctf");
    await waitFor(() => expect(lastQuery(fetchMock).get("gametype")).toBe("ctf"));
    expect(lastQuery(fetchMock).get("map")).toBe("boil"); // they combine
    expect(where()).toBe("/matches?map=boil&gametype=ctf");

    await user.selectOptions(map, "");
    await waitFor(() => expect(lastQuery(fetchMock).get("map")).toBeNull());
    expect(where()).toBe("/matches?gametype=ctf");
  });

  it("hides matches against bots", async () => {
    const user = userEvent.setup();
    const fetchMock = server();
    open();
    await screen.findByRole("table", { name: "Matches" });
    expect(lastQuery(fetchMock).get("vs_bots")).toBeNull();
    const box = screen.getByRole("checkbox", { name: "Hide vs bots" });
    expect(box).not.toBeChecked();
    await user.click(box);
    await waitFor(() => expect(lastQuery(fetchMock).get("vs_bots")).toBe("false"));
    expect(where()).toBe("/matches?vs_bots=0");
    expect(box).toBeChecked();
    await user.click(box);
    await waitFor(() => expect(lastQuery(fetchMock).get("vs_bots")).toBeNull());
    expect(where()).toBe("/matches");
  });

  it("a reload with ?player= applies the filter and shows the player's name", async () => {
    const user = userEvent.setup();
    const fetchMock = server();
    open("/matches?player=7&map=boil&vs_bots=0&page=1");
    await screen.findByRole("table", { name: "Matches" });
    const q = lastQuery(fetchMock);
    expect(q.get("player")).toBe("7");
    expect(q.get("map")).toBe("boil");
    expect(q.get("vs_bots")).toBe("false");
    await waitFor(() => expect(document.querySelector(".chip")).toHaveTextContent("Ace"));
    expect(screen.getByRole("combobox", { name: "Map" })).toHaveValue("boil");
    expect(screen.getByRole("checkbox", { name: "Hide vs bots" })).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Remove the player filter" }));
    await waitFor(() => expect(lastQuery(fetchMock).get("player")).toBeNull());
    expect(where()).toBe("/matches?map=boil&vs_bots=0");
    expect(document.querySelector(".chip")).toBeNull();
  });

  it("pages through the list and goes back to the first page on a new filter", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 50 }, (_, i) =>
      makeMatchSummary({ id: 200 - i, started_at: 1_790_000_000 - i }),
    );
    const fetchMock = server({
      matches: (p) => ({ total: 120, matches: p.get("offset") === "0" ? many : [DM] }),
    });
    open();
    await screen.findByText("1–50 of 120");
    expect(lastQuery(fetchMock).get("limit")).toBe("50");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(lastQuery(fetchMock).get("offset")).toBe("50"));
    expect(where()).toBe("/matches?page=2");
    await screen.findByText("51–100 of 120");
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();

    await user.click(screen.getByRole("checkbox", { name: "Hide vs bots" }));
    await waitFor(() => expect(lastQuery(fetchMock).get("offset")).toBe("0"));
    expect(where()).toBe("/matches?vs_bots=0");
  });

  it("keeps the rows and picks up a match that ended on the next poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["setTimeout", "clearTimeout"] });
    let n = 0;
    server({
      matches: () => {
        n += 1;
        return {
          matches: [
            makeMatchSummary({
              id: 1,
              outcome: n === 1 ? "in_progress" : "finished",
              winner: null,
            }),
          ],
        };
      },
    });
    open();
    await screen.findByText("In progress");
    await vi.advanceTimersByTimeAsync(5500);
    await screen.findByText("Finished");
    expect(screen.queryByText("In progress")).toBeNull();
  });

  it("scrolls the table inside its own box", async () => {
    server();
    open();
    const table = await screen.findByRole("table", { name: "Matches" });
    expect(table.parentElement).toHaveClass("table-scroll");
  });
});

describe("the match dialog (7.3)", () => {
  const TEAMS: MatchDetail = makeMatchDetail({
    id: 2,
    gametype: "tdm",
    map: "atelier",
    winner: { kind: "team", team: 14, color: "blue" },
    scoreboard: {
      columns: makeMatchDetail().scoreboard.columns,
      teams: [
        { team: 14, color: "blue", values: { score: 8 } },
        { team: 5, color: "red", values: { score: 4 } },
      ],
      players: [
        makeHistoryPlayer("Bee", { score: 6 }, { player_id: 2, team: 14 }),
        makeHistoryPlayer(
          "^1Ace",
          { score: 4 },
          { player_id: 7, team: 5, at_end: false, time_s: 40 },
        ),
      ],
    },
  });

  it("opens from a click on a row with the summary and the final scoreboard", async () => {
    const user = userEvent.setup();
    server();
    open();
    await user.click(await rowFor("boil"));
    const dialog = await screen.findByRole("dialog");
    const board = within(
      await within(dialog).findByRole("table", { name: "Final scoreboard" }),
    );
    const rows = board.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("1Ace"),
      expect.stringContaining("2[BOT]Rexbot"),
    ]);
    expect(
      within(dialog).getByText("Final scoreboard", { selector: "h3" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Winner")).toBeInTheDocument();
    expect(within(dialog).queryByText(/Teams were not recorded/)).toBeNull();
  });

  it("opens from the keyboard and Escape closes it, returning focus with filters intact", async () => {
    const user = userEvent.setup();
    server();
    open("/matches?map=boil&vs_bots=0");
    const opener = (
      await screen.findAllByRole("button", { name: /20\d\d|\d\d?:\d\d/ })
    )[0];
    opener.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
    expect(where()).toBe("/matches?map=boil&vs_bots=0");
    expect(screen.getByRole("table", { name: "Matches" })).toBeInTheDocument();
  });

  it("the close control closes it", async () => {
    const user = userEvent.setup();
    server();
    open();
    await user.click(await rowFor("boil"));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("groups a team game under its teams' totals and marks who was not there at the end", async () => {
    const user = userEvent.setup();
    server({ detail: () => jsonResponse(TEAMS) });
    open();
    await user.click(await rowFor("atelier"));
    const dialog = await screen.findByRole("dialog");
    const board = within(
      await within(dialog).findByRole("table", { name: "Final scoreboard" }),
    );
    const rows = board.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent?.replace(/\s+/g, " "))).toEqual([
      expect.stringContaining("Blue · 1"),
      expect.stringContaining("1Bee"),
      expect.stringContaining("Red · 1"),
      expect.stringContaining("1Acenot at end"),
    ]);
    expect(rows[0]).toHaveClass("team-blue");
    expect(within(dialog).getAllByText("not at end")).toHaveLength(1);
  });

  it("says teams were not recorded for a match recorded before they were kept", async () => {
    const user = userEvent.setup();
    server({ detail: () => jsonResponse({ ...TEAMS, board_kept: false }) });
    open();
    await user.click(await rowFor("atelier"));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText(/Teams were not recorded/),
    ).toBeInTheDocument();
  });

  it("explains a match that ended without a report", async () => {
    const user = userEvent.setup();
    server({
      detail: () =>
        jsonResponse(
          makeMatchDetail({ outcome: "no_report", winner: null, duration: null }),
        ),
    });
    open();
    await user.click(await rowFor("boil"));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText(/ended without an end-of-match report/),
    ).toBeInTheDocument();
  });

  it("opens a player from the scoreboard, with only one dialog open", async () => {
    const user = userEvent.setup();
    server();
    open();
    await user.click(await rowFor("boil"));
    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("button", { name: "Ace" }));
    await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
    const player = screen.getByRole("dialog");
    expect(await within(player).findByText("dRXbACYQ…")).toBeInTheDocument();
    expect(within(player).queryByRole("table", { name: "Final scoreboard" })).toBeNull();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows an error from the API in the dialog", async () => {
    const user = userEvent.setup();
    server({
      detail: () =>
        jsonResponse({ detail: { code: "match_not_found", message: "no match 3" } }, 404),
    });
    open();
    await user.click(await rowFor("boil"));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("no match 3");
  });
});
