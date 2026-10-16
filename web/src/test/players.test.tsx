import { readFileSync } from "node:fs";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PLAYERS_REFRESH_MS } from "../api/usePlayers";
import { Players } from "../sections/Players";
import { jsonResponse, makePlayerDetail, makePlayerRow, stubFetch } from "./util";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function open(route = "/players") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Players />
      <Where />
    </MemoryRouter>,
  );
}

const ANN = makePlayerRow({ id: 1, name: "^1Ann", plain_name: "Ann", frags: 20 });
const BOB = makePlayerRow({
  id: 2,
  name: "Bob",
  plain_name: "Bob",
  frags: 10,
  accuracy: null,
  wins: 0,
});
const REX = makePlayerRow({
  id: 3,
  name: "[BOT]Rex",
  plain_name: "[BOT]Rex",
  is_bot: true,
  frags: 5,
});

interface Server {
  players?: (params: URLSearchParams) => { total?: number; players: unknown[] };
  detail?: (id: number) => Response;
}

function server({ players, detail }: Server = {}) {
  return stubFetch((url) => {
    const [path, query = ""] = url.split("?");
    if (path === "/api/players") {
      const params = new URLSearchParams(query);
      const body = players
        ? players(params)
        : { players: params.get("bots") === "true" ? [ANN, BOB, REX] : [ANN, BOB] };
      const response = jsonResponse({
        revision: 1,
        total: body.total ?? body.players.length,
        players: body.players,
      });
      response.headers.set("ETag", `"1-${query.length}"`);
      return response;
    }
    const m = path.match(/^\/api\/players\/(\d+)$/);
    if (m) {
      const id = Number(m[1]);
      return detail
        ? detail(id)
        : jsonResponse(makePlayerDetail({ id, name: id === 1 ? "^1Ann" : "Bob" }));
    }
    throw new Error(`unexpected request: ${url}`);
  });
}

function lastQuery(fn: ReturnType<typeof server>): URLSearchParams {
  const calls = fn.mock.calls.filter(([u]) => String(u).startsWith("/api/players?"));
  return new URLSearchParams(String(calls.at(-1)?.[0]).split("?")[1]);
}

const names = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell")[0].textContent?.replace(/bot$/, ""));

describe("the Players table (7.2)", () => {
  it("lists players by frags, highest first, with coloured names and a bot-free list", async () => {
    const fetchMock = server();
    open();
    await screen.findByText("Ann");
    const q = lastQuery(fetchMock);
    expect(q.get("sort")).toBe("frags");
    expect(q.get("order")).toBe("desc");
    expect(q.get("bots")).toBe("false");
    expect(names()).toEqual(["Ann", "Bob"]);
    // colour codes are rendered, never shown
    expect(screen.queryByText(/\^1/)).toBeNull();
    expect(screen.getByRole("columnheader", { name: /Frags/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(screen.getByRole("columnheader", { name: /Deaths/ })).toHaveAttribute(
      "aria-sort",
      "none",
    );
  });

  it("shows every column of the spec", async () => {
    server();
    open();
    await screen.findByText("Ann");
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent?.trim());
    expect(headers.map((h) => h?.replace(/\s*[▲▼]$/, ""))).toEqual([
      "Name",
      "Frags",
      "Deaths",
      "K/D",
      "Score",
      "Wins",
      "Matches",
      "Time playing",
      "Time on server",
      "Accuracy",
      "Last seen",
    ]);
    const row = screen.getByText("Ann").closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("20"); // frags
    expect(cells[3]).toHaveTextContent("2.00"); // K/D
    expect(cells[7]).toHaveTextContent("1h 0m"); // time playing
    expect(cells[8]).toHaveTextContent("2h 5m"); // time on server
    expect(cells[9]).toHaveTextContent("42%");
    expect(cells[10].querySelector("[title]")).not.toBeNull(); // the absolute time
    const bob = screen.getByText("Bob").closest("tr") as HTMLElement;
    expect(within(bob).getAllByRole("cell")[9]).toHaveTextContent("–");
  });

  it("sorts by a column and reverses on a second activation", async () => {
    const user = userEvent.setup();
    const fetchMock = server();
    open();
    await screen.findByText("Ann");

    await user.click(screen.getByRole("button", { name: /^Deaths/ }));
    await waitFor(() => expect(lastQuery(fetchMock).get("sort")).toBe("deaths"));
    expect(lastQuery(fetchMock).get("order")).toBe("desc");
    expect(screen.getByRole("columnheader", { name: /Deaths/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );

    await user.click(screen.getByRole("button", { name: /^Deaths/ }));
    await waitFor(() => expect(lastQuery(fetchMock).get("order")).toBe("asc"));
    expect(screen.getByRole("columnheader", { name: /Deaths/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );

    // text columns start A to Z
    await user.click(screen.getByRole("button", { name: /^Name/ }));
    await waitFor(() => expect(lastQuery(fetchMock).get("sort")).toBe("name"));
    expect(lastQuery(fetchMock).get("order")).toBe("asc");
  });

  it("asks the server to sort, so the order covers every page", async () => {
    const user = userEvent.setup();
    const fetchMock = server({
      players: (p) => ({
        total: 120,
        players: p.get("sort") === "time_playing" ? [BOB] : [ANN],
      }),
    });
    open();
    await screen.findByText("Ann");
    await user.click(screen.getByRole("button", { name: /^Time playing/ }));
    await screen.findByText("Bob");
    expect(lastQuery(fetchMock).get("sort")).toBe("time_playing");
    expect(lastQuery(fetchMock).get("offset")).toBe("0");
  });

  it("searches by name after a short pause", async () => {
    const user = userEvent.setup();
    const fetchMock = server({
      players: (p) => ({ players: p.get("q") === "ace" ? [ANN] : [ANN, BOB] }),
    });
    open();
    await screen.findByText("Bob");
    await user.type(screen.getByRole("searchbox", { name: "Search players" }), "ace");
    await waitFor(() => expect(lastQuery(fetchMock).get("q")).toBe("ace"));
    await waitFor(() => expect(screen.queryByText("Bob")).toBeNull());
    // the pause means one request for the word, not one per key
    const withQ = fetchMock.mock.calls.filter(([u]) => String(u).includes("q="));
    expect(withQ.length).toBeLessThanOrEqual(2);
    expect(screen.getByTestId("where")).toHaveTextContent("q=ace");
  });

  it("hides bots until asked, and marks them", async () => {
    const user = userEvent.setup();
    const fetchMock = server();
    open();
    await screen.findByText("Ann");
    expect(screen.queryByText(/Rex/)).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: "Show bots" }));
    await screen.findByText(/Rex/);
    expect(lastQuery(fetchMock).get("bots")).toBe("true");
    const row = screen.getByText(/Rex/).closest("tr") as HTMLElement;
    expect(within(row).getByText("bot")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("bots=1");
  });

  it("says so when nobody has been recorded", async () => {
    server({ players: () => ({ players: [] }) });
    open();
    expect(
      await screen.findByText(/No players have been recorded yet/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says so when a search finds nobody", async () => {
    server({ players: () => ({ players: [] }) });
    open("/players?q=zzz");
    expect(await screen.findByText(/No players match that name/)).toBeInTheDocument();
  });

  it("pages with the total, and Next asks for the next offset", async () => {
    const user = userEvent.setup();
    const fetchMock = server({ players: () => ({ total: 120, players: [ANN, BOB] }) });
    open();
    await screen.findByText("Ann");
    expect(screen.getByText("1–50 of 120")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(lastQuery(fetchMock).get("offset")).toBe("50"));
    expect(screen.getByText("51–100 of 120")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => expect(lastQuery(fetchMock).get("offset")).toBe("0"));
  });

  it("restores the view from a deep link", async () => {
    const fetchMock = server();
    open("/players?sort=time_playing&order=asc&bots=1&q=an&page=2");
    await screen.findByText("Ann");
    const q = lastQuery(fetchMock);
    expect(q.get("sort")).toBe("time_playing");
    expect(q.get("order")).toBe("asc");
    expect(q.get("bots")).toBe("true");
    expect(q.get("q")).toBe("an");
    expect(q.get("offset")).toBe("50");
    expect(screen.getByRole("columnheader", { name: /Time playing/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(screen.getByRole("searchbox")).toHaveValue("an");
    expect(screen.getByRole("checkbox", { name: "Show bots" })).toBeChecked();
  });

  it("falls back to the default for an unknown sort in the link", async () => {
    const fetchMock = server();
    open("/players?sort=password&order=sideways");
    await screen.findByText("Ann");
    expect(lastQuery(fetchMock).get("sort")).toBe("frags");
    expect(lastQuery(fetchMock).get("order")).toBe("desc");
  });

  it("refreshes on its own and keeps the sort, search and bots choice", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["setTimeout", "clearTimeout"] });
    let frags = 20;
    const fetchMock = server({
      players: () => ({ players: [{ ...ANN, frags }, BOB] }),
    });
    open("/players?sort=deaths&order=asc&bots=1&q=a");
    await screen.findByText("Ann");
    const before = fetchMock.mock.calls.length;
    frags = 21;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PLAYERS_REFRESH_MS + 500);
    });
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(before));
    const row = (await screen.findByText("Ann")).closest("tr") as HTMLElement;
    await waitFor(() =>
      expect(within(row).getAllByRole("cell")[1]).toHaveTextContent("21"),
    );
    const q = lastQuery(fetchMock);
    expect([q.get("sort"), q.get("order"), q.get("bots"), q.get("q")]).toEqual([
      "deaths",
      "asc",
      "true",
      "a",
    ]);
  });
});

describe("the player dialog (7.3)", () => {
  it("opens from a click on the row and shows the details", async () => {
    const user = userEvent.setup();
    server();
    open();
    await user.click((await screen.findByText("Bob")).closest("tr") as HTMLElement);
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("dRXbACYQ…");
    expect(within(dialog).getByText("Old Ann")).toBeInTheDocument(); // names used
    const field = (label: string) => within(dialog).getByText(label).nextElementSibling;
    expect(field("Sessions")).toHaveTextContent("3");
    expect(field("Damage dealt")).toHaveTextContent("1234");
    expect(field("Average ping")).toHaveTextContent("32 ms");
    expect(field("Key")).toHaveTextContent("dRXbACYQ…");
    const weapons = within(within(dialog).getByRole("table", { name: "Weapons" }));
    const rows = weapons.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual(["vortex750.0%", "shotgun3–"]);
    expect(within(dialog).getByText("firstblood ×2")).toBeInTheDocument();
    expect(within(dialog).queryByText(/No match statistics recorded yet/)).toBeNull();
  });

  it("shows matches played and wins, and links to that player's matches", async () => {
    const user = userEvent.setup();
    server({
      detail: (id) =>
        jsonResponse(makePlayerDetail({ id, name: "^1Ann", matches: 12, wins: 3 })),
    });
    open();
    await user.click((await screen.findByText("Ann")).closest("tr") as HTMLElement);
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("dRXbACYQ…");
    const field = (label: string) => within(dialog).getByText(label).nextElementSibling;
    expect(field("Matches played")).toHaveTextContent("12");
    expect(field("Wins")).toHaveTextContent("3");

    await user.click(within(dialog).getByRole("link", { name: "View matches" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/matches?player=1");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("opens from the keyboard with Enter and with Space", async () => {
    const user = userEvent.setup();
    server();
    open();
    const first = await screen.findByRole("button", { name: "Ann" });
    first.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    first.focus();
    await user.keyboard(" ");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("closes with Escape and returns focus to the row", async () => {
    const user = userEvent.setup();
    server();
    open();
    await user.click((await screen.findByText("Bob")).closest("tr") as HTMLElement);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Bob" })).toHaveFocus();
    // the table is as it was
    expect(names()).toEqual(["Ann", "Bob"]);
  });

  it("closes with its button and returns focus to the row", async () => {
    const user = userEvent.setup();
    server();
    open();
    await user.click((await screen.findByText("Ann")).closest("tr") as HTMLElement);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Ann" })).toHaveFocus();
  });

  it("closes on a click on the backdrop but not on its content", async () => {
    const user = userEvent.setup();
    server();
    open();
    await user.click((await screen.findByText("Ann")).closest("tr") as HTMLElement);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("heading", { level: 2 }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(dialog); // the dialog element itself is the backdrop target
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("says when a player has no match statistics yet", async () => {
    const user = userEvent.setup();
    server({
      detail: (id) =>
        jsonResponse(
          makePlayerDetail({
            id,
            has_match_stats: false,
            weapons: [],
            achievements: [],
            accuracy: null,
          }),
        ),
    });
    open();
    await user.click((await screen.findByText("Ann")).closest("tr") as HTMLElement);
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText(/No match statistics recorded yet/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Time on server")).toBeInTheDocument();
    expect(within(dialog).queryByRole("table", { name: "Weapons" })).toBeNull();
  });

  it("shows a missing player as an error", async () => {
    const user = userEvent.setup();
    server({
      detail: () =>
        jsonResponse(
          { detail: { code: "player_not_found", message: "no player 1" } },
          404,
        ),
    });
    open();
    await user.click((await screen.findByText("Ann")).closest("tr") as HTMLElement);
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("no player 1");
  });
});

describe("the narrow-window layout (7.4)", () => {
  const css = readFileSync("src/styles.css", "utf8");
  const rule = (selector: string) => {
    const escaped = selector.replace(/[.[\]]/g, "\\$&");
    const m = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`));
    expect(m, `${selector} rule`).not.toBeNull();
    return m![1];
  };

  it("scrolls the table inside its own box, not the page", () => {
    // jsdom has no layout, so assert the rules that keep the page from scrolling sideways.
    expect(rule(".table-scroll")).toMatch(/overflow-x:\s*auto/);
    expect(rule(".table-scroll")).toMatch(/max-width:\s*100%/);
    expect(css).toMatch(/body\s*\{[^}]*overflow-x:\s*hidden/);
  });

  it("keeps the dialog inside the viewport and scrolls its body", () => {
    expect(rule(".dialog")).toMatch(/width:\s*min\(40rem,\s*100vw - 2rem\)/);
    expect(rule(".dialog")).toMatch(/max-height:/);
    expect(rule(".dialog-body")).toMatch(/overflow-y:\s*auto/);
    expect(rule(".dialog-body")).toMatch(/overflow-x:\s*hidden/);
  });

  it("puts the table in the scrolling box", async () => {
    server();
    open();
    const table = await screen.findByRole("table", { name: "Players" });
    expect(table.parentElement).toHaveClass("table-scroll");
  });
});
