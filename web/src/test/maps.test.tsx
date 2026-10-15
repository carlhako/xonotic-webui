import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Maps } from "../sections/Maps";
import { FakeEventSource } from "./fakeEventSource";
import {
  STATUS_URL,
  jsonResponse,
  makeMap,
  makeMapStats,
  makePlayerDetail,
  makeStatus,
  pushStatus,
  renderSection,
  routeFetch,
} from "./util";

afterEach(() => vi.unstubAllGlobals());

const gametypes = (extra = {}) => ({
  gametypes: [
    { id: "dm", name: "Deathmatch", score_unit: "frags", offered: true, map_count: 2 },
    {
      id: "tdm",
      name: "Team Deathmatch",
      score_unit: "points",
      offered: true,
      map_count: 1,
    },
    {
      id: "ctf",
      name: "Capture the Flag",
      score_unit: "captures",
      offered: true,
      map_count: 1,
    },
    { id: "ca", name: "Clan Arena", score_unit: "rounds", offered: false, map_count: 0 },
  ],
  selected: null,
  running: "dm",
  effective: "dm",
  ...extra,
});

const maps = [
  makeMap({ name: "stormkeep", title: "Stormkeep", gametypes: ["dm", "tdm"] }),
  makeMap({ name: "boil", title: "Boil", gametypes: ["dm"] }),
  makeMap({ name: "catharsis", title: "Catharsis", gametypes: ["ctf"], preview: false }),
  makeMap({
    name: "plain",
    title: "plain",
    gametypes: [],
    has_mapinfo: false,
    preview: false,
  }),
];

const rotation = (extra = {}) => ({
  maps: [],
  shuffle: null,
  gametype: "dm",
  ...extra,
});

async function openMaps(
  status = makeStatus({ state: "running", map: "stormkeep", gametype: "dm" }),
  routes: Record<string, (init?: RequestInit) => Response> = {},
  extra: {
    gametypes?: object;
    rotation?: object;
    favourites?: string[];
    maps?: ReturnType<typeof makeMap>[];
  } = {},
) {
  const fetchMock = routeFetch({
    "GET /api/maps": () => jsonResponse({ maps: extra.maps ?? maps }),
    "GET /api/favourites": () => jsonResponse({ maps: extra.favourites ?? [] }),
    "GET /api/gametypes": () => jsonResponse(gametypes(extra.gametypes)),
    "GET /api/rotation": () => jsonResponse(rotation(extra.rotation)),
    ...routes,
  });
  renderSection(<Maps />);
  await pushStatus(status);
  await screen.findByText("Boil", { selector: ".map-title" });
  return fetchMock;
}

function card(title: string): HTMLElement {
  return screen.getByText(title, { selector: ".map-title" }).closest("li") as HTMLElement;
}

describe("maps (6.3)", () => {
  it("shows the installed maps with preview, title and gametype badges", async () => {
    await openMaps();
    const stormkeep = card("Stormkeep");
    expect(within(stormkeep).getByText("Deathmatch")).toBeInTheDocument();
    expect(within(stormkeep).getByText("Team Deathmatch")).toBeInTheDocument();
    expect(stormkeep.querySelector("img")).toHaveAttribute(
      "src",
      "/api/maps/stormkeep/preview",
    );
    // no preview image and no map information
    const plain = card("plain");
    expect(plain.querySelector("img")).toBeNull();
    expect(within(plain).getByText("unknown gametypes")).toBeInTheDocument();
  });

  it("filters the grid by gametype", async () => {
    await openMaps();
    await userEvent.selectOptions(screen.getByLabelText("Show maps for"), "ctf");
    expect(screen.queryByText("Stormkeep", { selector: ".map-title" })).toBeNull();
    expect(screen.getByText("Catharsis", { selector: ".map-title" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Show maps for"), "");
    expect(screen.getByText("Stormkeep", { selector: ".map-title" })).toBeInTheDocument();
  });

  it("offers only gametypes some installed map supports", async () => {
    await openMaps();
    const options = within(screen.getByLabelText("Gametype"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual([
      "Deathmatch (2 maps)",
      "Team Deathmatch (1 map)",
      "Capture the Flag (1 map)",
    ]);
  });

  it("selects the gametype for the next map and says so", async () => {
    const fetchMock = await openMaps(undefined, {
      "PUT /api/gametype": () => jsonResponse({ gametype: "tdm", apply: "next_map" }),
    });
    await userEvent.selectOptions(screen.getByLabelText("Gametype"), "tdm");
    await userEvent.click(screen.getByRole("button", { name: "Use at next map" }));
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(call![1]!.body as string)).toEqual({ gametype: "tdm" });
    expect(await screen.findByText(/applies at the next map/)).toBeInTheDocument();
  });

  it("switches gametype now by going to a map that supports it", async () => {
    const fetchMock = await openMaps(undefined, {
      "PUT /api/gametype": () => jsonResponse({ gametype: "ctf", apply: "next_map" }),
      "POST /api/match/goto": () =>
        jsonResponse({ id: 1, kind: "goto", map: "catharsis", state: "pending" }, 202),
    });
    await userEvent.selectOptions(screen.getByLabelText("Gametype"), "ctf");
    await userEvent.click(screen.getByRole("button", { name: "Switch now…" }));
    // only maps for the chosen gametype are offered
    const choices = within(screen.getByLabelText("Map to switch to"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(choices).toEqual(["Choose a map…", "Catharsis"]);
    await userEvent.selectOptions(screen.getByLabelText("Map to switch to"), "catharsis");
    await userEvent.click(screen.getByRole("button", { name: "Switch and go" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/match/goto",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const methods = fetchMock.mock.calls.map(
      ([url, init]) => `${init?.method ?? "GET"} ${url}`,
    );
    expect(methods.indexOf("PUT /api/gametype")).toBeLessThan(
      methods.indexOf("POST /api/match/goto"),
    );
  });

  it("goes to a map straight away when nobody is connected", async () => {
    const fetchMock = await openMaps(undefined, {
      "POST /api/match/goto": () =>
        jsonResponse({ id: 1, kind: "goto", map: "boil", state: "pending" }, 202),
    });
    await userEvent.click(
      within(card("Boil")).getByRole("button", { name: "Go to this map" }),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    const call = fetchMock.mock.calls.find(([url]) => url === "/api/match/goto");
    expect(JSON.parse(call![1]!.body as string)).toEqual({ map: "boil" });
  });

  it("asks first, stating how many, when players are connected", async () => {
    const fetchMock = await openMaps(
      makeStatus({
        state: "running",
        map: "stormkeep",
        gametype: "dm",
        human_count: 2,
        players: [
          { id: 1, ent: 1, name: "a", plain_name: "a", bot: false },
          { id: 2, ent: 2, name: "b", plain_name: "b", bot: false },
        ],
      }),
      {
        "POST /api/match/goto": () =>
          jsonResponse({ id: 1, kind: "goto", map: "boil", state: "pending" }, 202),
      },
    );
    await userEvent.click(
      within(card("Boil")).getByRole("button", { name: "Go to this map" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("2 players are in the match");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/match/goto")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Go anyway" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === "/api/match/goto")).toBe(true),
    );
  });

  it("only offers 'go to' for maps the current gametype supports, and only while running", async () => {
    await openMaps();
    expect(
      within(card("Boil")).getByRole("button", { name: "Go to this map" }),
    ).toBeEnabled();
    expect(
      within(card("Catharsis")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
    expect(
      within(card("plain")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
  });

  it("is disabled while the server is stopped", async () => {
    await openMaps(makeStatus({ state: "stopped" }));
    expect(
      within(card("Boil")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Switch now…" })).toBeDisabled();
  });

  it("shows the reason when the server refuses a go-to", async () => {
    await openMaps(undefined, {
      "POST /api/match/goto": () =>
        jsonResponse(
          {
            detail: {
              code: "map_unsupported_gametype",
              message: "boil does not support Capture the Flag",
            },
          },
          422,
        ),
    });
    await userEvent.click(
      within(card("Boil")).getByRole("button", { name: "Go to this map" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("does not support");
  });
});

describe("rotation", () => {
  const withRotation = {
    rotation: {
      maps: [
        { name: "stormkeep", title: "Stormkeep", installed: true, supported: true },
        { name: "catharsis", title: "Catharsis", installed: true, supported: false },
        { name: "boil", title: "Boil", installed: true, supported: true },
      ],
      shuffle: false,
      gametype: "tdm",
    },
    gametypes: { selected: "tdm", effective: "tdm" },
  };

  it("shows the saved order and flags a map the gametype cannot play", async () => {
    await openMaps(undefined, {}, withRotation);
    const items = screen
      .getAllByRole("listitem")
      .filter((li) => li.className === "rotation-item");
    expect(
      items.map((li) => within(li).getByText(/Stormkeep|Catharsis|Boil/).textContent),
    ).toEqual(["Stormkeep", "Catharsis", "Boil"]);
    expect(
      within(items[1]).getByText("does not support Team Deathmatch"),
    ).toBeInTheDocument();
    expect(within(items[0]).queryByText(/does not support/)).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Shuffle" })).not.toBeChecked();
  });

  it("reorders, removes and saves", async () => {
    const fetchMock = await openMaps(
      undefined,
      {
        "PUT /api/rotation": () =>
          jsonResponse({
            apply: "next_map",
            rotation: { maps: [], shuffle: false, gametype: "tdm" },
          }),
      },
      withRotation,
    );
    await userEvent.click(screen.getByRole("button", { name: "Move boil up" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Remove catharsis from the rotation" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save rotation" }));
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(call![1]!.body as string)).toEqual({
      maps: ["stormkeep", "boil"],
      shuffle: false,
    });
    expect(
      await screen.findByText(/Rotation saved: applies at the next map/),
    ).toBeInTheDocument();
  });

  it("adds a map from the grid to the rotation", async () => {
    const fetchMock = await openMaps(
      undefined,
      {
        "PUT /api/rotation": () =>
          jsonResponse({ apply: "next_map", rotation: rotation() }),
      },
      { rotation: { maps: [], shuffle: null, gametype: "dm" } },
    );
    expect(
      screen.getByText(/No rotation: the server plays every map/),
    ).toBeInTheDocument();
    await userEvent.click(
      within(card("Boil")).getByRole("button", { name: "Add to rotation" }),
    );
    expect(
      within(card("Boil")).getByRole("button", { name: "In rotation" }),
    ).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Save rotation" }));
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    // shuffle was never chosen: the game's default stays in force
    expect(JSON.parse(call![1]!.body as string)).toEqual({
      maps: ["boil"],
      shuffle: null,
    });
  });
});

// -- favourites, the Files view and map packages ---------------------------------------

const userMaps = [
  makeMap({
    name: "stormkeep",
    title: "Stormkeep",
    gametypes: ["dm", "tdm"],
    package: "xonotic-data-maps.pk3",
    package_size: 41_943_040,
  }),
  makeMap({
    name: "boil",
    title: "Boil",
    gametypes: ["dm"],
    package: "xonotic-data-maps.pk3",
    package_size: 41_943_040,
  }),
  makeMap({
    name: "mymap",
    title: "My Map",
    gametypes: ["dm"],
    source: "user",
    package: "mymap_v2.pk3",
    package_size: 2_516_582,
  }),
  makeMap({
    name: "mysecond",
    title: "My Second",
    gametypes: ["ctf"],
    source: "user",
    package: "mymap_v2.pk3",
    package_size: 2_516_582,
  }),
  makeMap({
    name: "latemap",
    title: "Late Map",
    gametypes: ["dm"],
    source: "user",
    package: "late.pk3",
    package_size: 1_024,
    pending_restart: true,
  }),
];

const withUserMaps = { maps: userMaps };

function row(title: string): HTMLElement {
  return screen.getByText(title, { selector: ".map-title" }).closest("tr") as HTMLElement;
}

async function openFiles(
  status?: ReturnType<typeof makeStatus>,
  routes: Record<string, (init?: RequestInit) => Response> = {},
  extra: Parameters<typeof openMaps>[2] = {},
) {
  const fetchMock = await openMaps(status, routes, { maps: userMaps, ...extra });
  await userEvent.click(screen.getByRole("button", { name: "Files" }));
  await screen.findByRole("table", { name: "Installed map files" });
  return fetchMock;
}

describe("favourites", () => {
  it("stars a map and shows it starred in both views", async () => {
    const fetchMock = await openMaps(
      undefined,
      {
        "PUT /api/favourites/boil": () => jsonResponse({ maps: ["boil"] }),
      },
      withUserMaps,
    );
    const star = within(card("Boil")).getByRole("button", {
      name: "Add boil to favourites",
    });
    expect(star).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(star);
    expect(
      await within(card("Boil")).findByRole("button", {
        name: "Remove boil from favourites",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/favourites/boil",
      expect.objectContaining({ method: "PUT" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(
      within(row("Boil")).getByRole("button", { name: "Remove boil from favourites" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("unstars a map from the table", async () => {
    const fetchMock = await openFiles(
      undefined,
      { "DELETE /api/favourites/boil": () => jsonResponse({ maps: [] }) },
      { favourites: ["boil"] },
    );
    await userEvent.click(
      within(row("Boil")).getByRole("button", { name: "Remove boil from favourites" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/favourites/boil",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    expect(
      await within(row("Boil")).findByRole("button", { name: "Add boil to favourites" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("puts the star back and shows the error when the panel cannot save it", async () => {
    await openMaps(
      undefined,
      {
        "PUT /api/favourites/boil": () =>
          jsonResponse(
            {
              detail: { code: "invalid_map_name", message: "cannot save the favourite" },
            },
            500,
          ),
      },
      withUserMaps,
    );
    await userEvent.click(
      within(card("Boil")).getByRole("button", { name: "Add boil to favourites" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "cannot save the favourite",
    );
    expect(
      within(card("Boil")).getByRole("button", { name: "Add boil to favourites" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("lists only the starred maps with 'Favourites only', in both views", async () => {
    await openMaps(
      undefined,
      {},
      { ...withUserMaps, favourites: ["boil", "mymap", "gone"] },
    );
    expect(screen.getByText("Stormkeep", { selector: ".map-title" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Favourites only" }));
    expect(screen.queryByText("Stormkeep", { selector: ".map-title" })).toBeNull();
    expect(screen.getByText("Boil", { selector: ".map-title" })).toBeInTheDocument();
    expect(screen.getByText("My Map", { selector: ".map-title" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    const table = await screen.findByRole("table", { name: "Installed map files" });
    const titles = within(table)
      .getAllByText(/./, { selector: ".map-title" })
      .map((e) => e.textContent);
    expect(titles).toEqual(["Boil", "My Map"]); // "gone" is not installed: not listed
    expect(screen.getByRole("checkbox", { name: "Favourites only" })).toBeChecked();
  });

  it("combines with the gametype filter", async () => {
    await openMaps(undefined, {}, { ...withUserMaps, favourites: ["boil", "mysecond"] });
    await userEvent.click(screen.getByRole("checkbox", { name: "Favourites only" }));
    await userEvent.selectOptions(screen.getByLabelText("Show maps for"), "dm");
    expect(screen.getByText("Boil", { selector: ".map-title" })).toBeInTheDocument();
    expect(screen.queryByText("My Second", { selector: ".map-title" })).toBeNull();
    expect(screen.queryByText("Stormkeep", { selector: ".map-title" })).toBeNull();
  });

  it("says there are no favourites yet when nothing is starred", async () => {
    await openMaps(undefined, {}, withUserMaps);
    await userEvent.click(screen.getByRole("checkbox", { name: "Favourites only" }));
    expect(screen.getByText(/No favourites yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(screen.getByText(/No favourites yet/)).toBeInTheDocument();
  });
});

describe("the Files view", () => {
  it("switches between the views and keeps both buttons", async () => {
    await openMaps(undefined, {}, withUserMaps);
    const cards = screen.getByRole("button", { name: "Cards" });
    const files = screen.getByRole("button", { name: "Files" });
    expect(cards).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(files);
    expect(screen.getByRole("button", { name: "Cards" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Files" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const table = screen.getByRole("table", { name: "Installed map files" });
    expect(table.querySelector("img")).toBeNull(); // no preview image
    expect(table.parentElement).toHaveClass("table-scroll");
    // one row per map, with its package and size
    expect(within(row("My Map")).getByText("mymap_v2.pk3")).toBeInTheDocument();
    expect(within(row("My Map")).getByText("2.4 MB")).toBeInTheDocument();
    expect(within(row("Stormkeep")).getByText("40.0 MB")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cards" }));
    expect(screen.queryByRole("table", { name: "Installed map files" })).toBeNull();
    expect(screen.getByText("Boil", { selector: ".map-title" })).toBeInTheDocument();
  });

  it("lets the map and package cells wrap, so long names do not widen the table", async () => {
    await openMaps(undefined, {}, withUserMaps);
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    const cells = within(row("My Map")).getAllByRole("cell");
    // favourite, map, package, size, played, frags, actions
    expect(cells[1]).toHaveClass("wrap-cell");
    expect(cells[2]).toHaveClass("wrap-cell");
    for (const i of [0, 3, 4, 5, 6]) expect(cells[i]).not.toHaveClass("wrap-cell");
  });

  it("remembers the view after a reload", async () => {
    const first = await openMaps(undefined, {}, withUserMaps);
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(first).toBeDefined();
    // a new page load: a fresh render with the same browser storage
    cleanup();
    vi.unstubAllGlobals();
    routeFetch({
      "GET /api/maps": () => jsonResponse(withUserMaps),
      "GET /api/favourites": () => jsonResponse({ maps: [] }),
      "GET /api/gametypes": () => jsonResponse(gametypes()),
      "GET /api/rotation": () => jsonResponse(rotation()),
    });
    renderSection(<Maps />);
    await pushStatus(makeStatus({ state: "running", gametype: "dm" }));
    expect(
      await screen.findByRole("table", { name: "Installed map files" }),
    ).toBeInTheDocument();
  });

  it("works when browser storage is unavailable", async () => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage")!;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("blocked");
      },
    });
    try {
      await openMaps(undefined, {}, withUserMaps);
      await userEvent.click(screen.getByRole("button", { name: "Files" }));
      expect(
        screen.getByRole("table", { name: "Installed map files" }),
      ).toBeInTheDocument();
    } finally {
      Object.defineProperty(window, "localStorage", original);
    }
  });

  it("offers Go to this map under the same rules as the cards", async () => {
    await openFiles();
    expect(
      within(row("Boil")).getByRole("button", { name: "Go to this map" }),
    ).toBeEnabled();
    // the current gametype is dm: a capture-the-flag map is off in both views
    expect(
      within(row("My Second")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
    // a package the game has not loaded is off too
    expect(
      within(row("Late Map")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Cards" }));
    expect(
      within(card("Boil")).getByRole("button", { name: "Go to this map" }),
    ).toBeEnabled();
    expect(
      within(card("My Second")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
    expect(
      within(card("Late Map")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
  });

  it("disables Go to this map in the table while stopped or while an action is pending", async () => {
    await openFiles(makeStatus({ state: "stopped" }));
    expect(
      within(row("Boil")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
  });

  it("disables Go to this map in the table while an action is pending", async () => {
    await openFiles(
      makeStatus({
        state: "running",
        gametype: "dm",
        action: { id: 1, kind: "skip", map: null, state: "pending" },
      }),
    );
    expect(
      within(row("Boil")).getByRole("button", { name: "Go to this map" }),
    ).toBeDisabled();
  });

  it("asks first when players are connected, then goes", async () => {
    const fetchMock = await openFiles(
      makeStatus({
        state: "running",
        gametype: "dm",
        human_count: 2,
        players: [
          { id: 1, ent: 1, name: "a", plain_name: "a", bot: false },
          { id: 2, ent: 2, name: "b", plain_name: "b", bot: false },
        ],
      }),
      {
        "POST /api/match/goto": () =>
          jsonResponse({ id: 1, kind: "goto", map: "mymap", state: "pending" }, 202),
      },
    );
    await userEvent.click(
      within(row("My Map")).getByRole("button", { name: "Go to this map" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("2 players are in the match");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/match/goto")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Go anyway" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === "/api/match/goto")).toBe(true),
    );
  });

  it("adds a map to the rotation being edited from a row", async () => {
    await openFiles();
    await userEvent.click(
      within(row("Boil")).getByRole("button", { name: "Add to rotation" }),
    );
    expect(
      within(row("Boil")).getByRole("button", { name: "In rotation" }),
    ).toBeDisabled();
    // the rotation panel above has it in its draft
    expect(screen.getByRole("button", { name: "Save rotation" })).toBeEnabled();
    expect(screen.getByText("boil", { selector: ".rotation-name" })).toBeInTheDocument();
  });

  it("offers download and delete for user packages only", async () => {
    await openFiles();
    for (const title of ["My Map", "My Second", "Late Map"]) {
      expect(
        within(row(title)).getByRole("link", { name: "Download" }),
      ).toBeInTheDocument();
      expect(
        within(row(title)).getByRole("button", { name: "Delete" }),
      ).toBeInTheDocument();
    }
    for (const title of ["Stormkeep", "Boil"]) {
      expect(within(row(title)).queryByRole("link", { name: "Download" })).toBeNull();
      expect(within(row(title)).queryByRole("button", { name: "Delete" })).toBeNull();
      // still has the match actions
      expect(
        within(row(title)).getByRole("button", { name: "Go to this map" }),
      ).toBeInTheDocument();
    }
  });

  it("links Download to the package", async () => {
    await openFiles();
    const link = within(row("My Map")).getByRole("link", { name: "Download" });
    expect(link).toHaveAttribute("href", "/api/packages/mymap_v2.pk3");
    expect(link).toHaveAttribute("download", "mymap_v2.pk3");
  });

  it("notes that a package the game has not loaded needs a restart", async () => {
    await openFiles();
    expect(
      within(row("Late Map")).getByText("restart the server to use this map"),
    ).toBeInTheDocument();
    expect(
      within(row("My Map")).queryByText("restart the server to use this map"),
    ).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Cards" }));
    expect(
      within(card("Late Map")).getByText("restart the server to use this map"),
    ).toBeInTheDocument();
  });
});

describe("after a restart", () => {
  it("lists the maps of an uploaded package without the note", async () => {
    let restarted = false;
    const fetchMock = await openFiles(undefined, {
      "GET /api/maps": () =>
        jsonResponse({
          maps: userMaps.map((m) => ({
            ...m,
            pending_restart: restarted ? false : m.pending_restart,
          })),
        }),
    });
    expect(
      within(row("Late Map")).getByText("restart the server to use this map"),
    ).toBeInTheDocument();
    restarted = true;
    // the server stops and starts again: the list is read again
    await pushStatus(makeStatus({ state: "stopped" }));
    await pushStatus(makeStatus({ state: "running", gametype: "dm" }));
    await waitFor(() =>
      expect(
        within(row("Late Map")).queryByText("restart the server to use this map"),
      ).toBeNull(),
    );
    expect(
      within(row("Late Map")).getByRole("button", { name: "Go to this map" }),
    ).toBeEnabled();
    expect(
      fetchMock.mock.calls.filter(([url]) => url === "/api/maps").length,
    ).toBeGreaterThan(1);
  });
});

describe("uploading a map package", () => {
  function pk3(name = "mymap_v2.pk3") {
    return new File(["PK"], name, { type: "application/octet-stream" });
  }
  const installed = (extra: object = {}) => ({
    name: "mymap_v2.pk3",
    size: 2_516_582,
    maps: ["mymap", "mysecond"],
    duplicates: [],
    restart_required: false,
    ...extra,
  });

  it("only offers .pk3 files", async () => {
    await openFiles();
    expect(screen.getByLabelText("Map package file")).toHaveAttribute("accept", ".pk3");
  });

  it("sends the file, names the maps found and reloads the list", async () => {
    let listed = 0;
    const fetchMock = await openFiles(undefined, {
      "PUT /api/packages/mymap_v2.pk3": () => jsonResponse(installed()),
      "GET /api/maps": () => {
        listed += 1;
        return jsonResponse(withUserMaps);
      },
    });
    const before = listed;
    const file = pk3();
    await userEvent.upload(screen.getByLabelText("Map package file"), file);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Installed mymap_v2.pk3");
    expect(status).toHaveTextContent("mymap, mysecond");
    const call = fetchMock.mock.calls.find(
      ([url]) => url === "/api/packages/mymap_v2.pk3",
    );
    expect(call![1]!.method).toBe("PUT");
    expect(call![1]!.body).toBe(file);
    await waitFor(() => expect(listed).toBeGreaterThan(before));
  });

  it("warns about a name another package already provides and about the restart", async () => {
    await openFiles(undefined, {
      "PUT /api/packages/my_boil.pk3": () =>
        jsonResponse(
          installed({
            name: "my_boil.pk3",
            maps: ["boil"],
            duplicates: [
              {
                map: "boil",
                package: "xonotic-data-maps.pk3",
                source: "game",
                used: true,
              },
            ],
            restart_required: true,
          }),
        ),
    });
    await userEvent.upload(screen.getByLabelText("Map package file"), pk3("my_boil.pk3"));
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(
      "boil has the same name as a map in xonotic-data-maps.pk3 (part of the game); the uploaded one is used",
    );
    expect(status).toHaveTextContent("restart it to use the map");
  });

  it.each([
    ["not_pk3", 422, "only .pk3 map packages are accepted"],
    ["bad_filename", 422, "the file name is not allowed"],
    ["too_large", 413, "the package is larger than the 256 MB limit"],
    ["not_a_package", 422, "the file is not a valid map package"],
    ["no_map", 422, "the package contains no map"],
    ["already_exists", 409, "mymap_v2.pk3 is already installed; delete it first"],
  ])("shows the panel's refusal (%s)", async (code, status, message) => {
    await openFiles(undefined, {
      "PUT /api/packages/mymap_v2.pk3": () =>
        jsonResponse({ detail: { code, message } }, status),
    });
    await userEvent.upload(screen.getByLabelText("Map package file"), pk3());
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText(/Installed mymap_v2.pk3/)).toBeNull();
  });
});

describe("deleting a map package", () => {
  const rotationWith = {
    rotation: {
      maps: [{ name: "mysecond", title: "My Second", installed: true, supported: false }],
      shuffle: null,
      gametype: "dm",
    },
  };

  it("names the file and its maps and deletes only on confirmation", async () => {
    let calls = 0;
    const fetchMock = await openFiles(undefined, {
      "DELETE /api/packages/mymap_v2.pk3": () => {
        calls += 1;
        return jsonResponse({ name: "mymap_v2.pk3", maps: ["mymap", "mysecond"] });
      },
    });
    await userEvent.click(within(row("My Map")).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Delete mymap_v2.pk3?");
    expect(dialog).toHaveTextContent("My Map");
    expect(dialog).toHaveTextContent("My Second");
    expect(dialog).toHaveTextContent("2.4 MB");
    expect(calls).toBe(0); // nothing is deleted by opening the popup
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete package" }));
    await waitFor(() => expect(calls).toBe(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/packages/mymap_v2.pk3",
      expect.objectContaining({ method: "DELETE" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("does nothing on cancel", async () => {
    const fetchMock = await openFiles();
    await userEvent.click(within(row("My Map")).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(
      false,
    );
    expect(row("My Map")).toBeInTheDocument();
  });

  it("calls out a map that is in the rotation", async () => {
    await openFiles(undefined, {}, rotationWith);
    await userEvent.click(within(row("My Map")).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("In the rotation: mysecond");
  });

  it("shows a failed delete and keeps the row", async () => {
    await openFiles(undefined, {
      "DELETE /api/packages/mymap_v2.pk3": () =>
        jsonResponse(
          { detail: { code: "package_not_found", message: "no such package" } },
          404,
        ),
    });
    await userEvent.click(within(row("My Map")).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete package" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("no such package");
    expect(row("My Map")).toBeInTheDocument();
  });
});

describe("package changes while the panel is disconnected", () => {
  it("offers no upload, download or delete", async () => {
    await openFiles();
    expect(screen.getByLabelText("Map package file")).toBeEnabled();
    expect(
      within(row("My Map")).getByRole("link", { name: "Download" }),
    ).toBeInTheDocument();

    act(() => FakeEventSource.byUrl(STATUS_URL)!.fail());
    await waitFor(() => expect(screen.getByLabelText("Map package file")).toBeDisabled());
    expect(within(row("My Map")).getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(within(row("My Map")).queryByRole("link", { name: "Download" })).toBeNull();
    expect(
      within(row("My Map")).getByRole("button", { name: "Download" }),
    ).toBeDisabled();
    expect(
      within(row("My Map")).getByRole("button", { name: "Add mymap to favourites" }),
    ).toBeDisabled();
  });
});

// --- play totals, sorting, the played filter and the details dialog -----------------------

const played = [
  makeMap({
    name: "boil",
    title: "Boil",
    gametypes: ["dm"],
    played: 5,
    frags: 100,
    last_played: 1_000,
  }),
  makeMap({
    name: "atelier",
    title: "Atelier",
    gametypes: ["dm"],
    played: 9,
    frags: 50,
    last_played: 3_000,
  }),
  makeMap({
    name: "zeta",
    title: "Zeta",
    gametypes: ["ctf"],
    played: 0,
    frags: 0,
    last_played: null,
  }),
  makeMap({
    name: "cinder",
    title: "Cinder",
    gametypes: ["dm"],
    played: 5,
    frags: 100,
    last_played: 2_000,
  }),
];
const withPlayed = { maps: played };
const unavailable = {
  maps: played.map((m) => ({ ...m, played: null, frags: null, last_played: null })),
};

/** The map titles in the order they are listed, in either view. */
const listed = () =>
  Array.from(document.querySelectorAll(".map-title")).map((e) => e.textContent);

describe("play totals (map-control)", () => {
  it("shows identical figures on the card and the table row", async () => {
    await openMaps(
      undefined,
      {},
      {
        maps: [
          makeMap({ name: "boil", title: "Boil", played: 42, frags: 1380 }),
          makeMap({ name: "zeta", title: "Zeta", played: 0, frags: 0 }),
        ],
      },
    );
    expect(
      within(card("Boil")).getByText("Played 42× · 1,380 frags"),
    ).toBeInTheDocument();
    expect(within(card("Zeta")).getByText("Played 0× · 0 frags")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    const cells = (title: string) =>
      within(row(title))
        .getAllByRole("cell")
        .map((c) => c.textContent);
    expect(cells("Boil")).toEqual(expect.arrayContaining(["42", "1,380"]));
    expect(cells("Zeta")).toEqual(expect.arrayContaining(["0", "0"]));
    const headers = within(
      screen.getByRole("table", { name: "Installed map files" }),
    ).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual(
      expect.arrayContaining(["Played", "Frags"]),
    );
  });

  it("shows dashes, not zero, when the totals are not available", async () => {
    await openMaps(undefined, {}, unavailable);
    expect(within(card("Boil")).getByText("Played – · – frags")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    const cells = within(row("Boil"))
      .getAllByRole("cell")
      .map((c) => c.textContent);
    expect(cells.filter((c) => c === "–")).toHaveLength(2);
  });
});

describe("sorting the maps", () => {
  it("is by name to begin with", async () => {
    await openMaps(undefined, {}, withPlayed);
    expect(listed()).toEqual(["Atelier", "Boil", "Cinder", "Zeta"]);
    expect(screen.getByLabelText("Sort by")).toHaveValue("name");
  });

  it.each([
    ["played", ["Atelier", "Boil", "Cinder", "Zeta"]],
    ["frags", ["Boil", "Cinder", "Atelier", "Zeta"]],
    ["recent", ["Atelier", "Cinder", "Boil", "Zeta"]],
  ])("orders by %s in both views, ties by name", async (choice, expected) => {
    await openMaps(undefined, {}, withPlayed);
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), choice);
    expect(listed()).toEqual(expected);
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    await screen.findByRole("table", { name: "Installed map files" });
    expect(listed()).toEqual(expected);
  });

  it("lists maps never played last, by name, under recently played", async () => {
    const more = [
      ...played,
      makeMap({ name: "alpha", title: "Alpha", played: 0, frags: 0 }),
    ];
    await openMaps(undefined, {}, { maps: more });
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "recent");
    expect(listed().slice(-2)).toEqual(["Alpha", "Zeta"]);
  });

  it("remembers the choice after a reload", async () => {
    await openMaps(undefined, {}, withPlayed);
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "frags");
    cleanup();
    vi.unstubAllGlobals();
    routeFetch({
      "GET /api/maps": () => jsonResponse(withPlayed),
      "GET /api/favourites": () => jsonResponse({ maps: [] }),
      "GET /api/gametypes": () => jsonResponse(gametypes()),
      "GET /api/rotation": () => jsonResponse(rotation()),
    });
    renderSection(<Maps />);
    await pushStatus(makeStatus({ state: "running", gametype: "dm" }));
    await screen.findByText("Boil", { selector: ".map-title" });
    expect(screen.getByLabelText("Sort by")).toHaveValue("frags");
    expect(listed()).toEqual(["Boil", "Cinder", "Atelier", "Zeta"]);
  });

  it("disables the stat choices and lists by name when totals are not available", async () => {
    window.localStorage.setItem("xonotic-webui.maps.sort", "played");
    window.localStorage.setItem("xonotic-webui.maps.played", "never");
    await openMaps(undefined, {}, unavailable);
    expect(listed()).toEqual(["Atelier", "Boil", "Cinder", "Zeta"]);
    const sort = screen.getByLabelText("Sort by");
    expect(sort).toHaveValue("name");
    const disabled = within(sort)
      .getAllByRole("option")
      .filter((o) => (o as HTMLOptionElement).disabled)
      .map((o) => o.textContent);
    expect(disabled).toEqual(["Most played", "Most frags", "Recently played"]);
    expect(screen.getByLabelText("Played filter")).toBeDisabled();
    expect(screen.getByLabelText("Played filter")).toHaveValue("all");
    // the stored choices were not overwritten
    expect(window.localStorage.getItem("xonotic-webui.maps.sort")).toBe("played");
    expect(window.localStorage.getItem("xonotic-webui.maps.played")).toBe("never");
  });

  it("restores the stored choice once the totals come back", async () => {
    window.localStorage.setItem("xonotic-webui.maps.sort", "played");
    let body: object = unavailable;
    await openMaps(undefined, { "GET /api/maps": () => jsonResponse(body) }, {});
    expect(listed()).toEqual(["Atelier", "Boil", "Cinder", "Zeta"]);
    body = withPlayed;
    // a restart of the server reloads the list
    await pushStatus(makeStatus({ state: "stopped" }));
    await waitFor(() => expect(screen.getByLabelText("Sort by")).toHaveValue("played"));
    expect(listed()).toEqual(["Atelier", "Boil", "Cinder", "Zeta"]);
    expect(screen.getByLabelText("Played filter")).toBeEnabled();
  });
});

describe("the played filter", () => {
  it("lists only played or only never-played maps", async () => {
    await openMaps(undefined, {}, withPlayed);
    await userEvent.selectOptions(screen.getByLabelText("Played filter"), "played");
    expect(listed()).toEqual(["Atelier", "Boil", "Cinder"]);
    await userEvent.selectOptions(screen.getByLabelText("Played filter"), "never");
    expect(listed()).toEqual(["Zeta"]);
    await userEvent.selectOptions(screen.getByLabelText("Played filter"), "all");
    expect(listed()).toHaveLength(4);
  });

  it("combines with favourites only and with a gametype", async () => {
    await openMaps(undefined, {}, { ...withPlayed, favourites: ["boil", "zeta"] });
    await userEvent.click(screen.getByRole("checkbox", { name: "Favourites only" }));
    await userEvent.selectOptions(screen.getByLabelText("Played filter"), "played");
    expect(listed()).toEqual(["Boil"]);
    await userEvent.click(screen.getByRole("checkbox", { name: "Favourites only" }));
    await userEvent.selectOptions(screen.getByLabelText("Show maps for"), "ctf");
    await userEvent.selectOptions(screen.getByLabelText("Played filter"), "never");
    expect(listed()).toEqual(["Zeta"]);
  });

  it("says no maps match when nothing is left, in both views", async () => {
    await openMaps(undefined, {}, withPlayed);
    await userEvent.selectOptions(screen.getByLabelText("Show maps for"), "ctf");
    await userEvent.selectOptions(screen.getByLabelText("Played filter"), "played");
    expect(screen.getByText("No maps match.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(screen.getByText("No maps match.")).toBeInTheDocument();
  });
});

describe("the map details dialog", () => {
  const stats = (overrides = {}) => jsonResponse(makeMapStats(overrides));

  it("opens from the card title with the play details", async () => {
    await openMaps(undefined, { "GET /api/maps/boil/stats": () => stats() }, withPlayed);
    await userEvent.click(within(card("Boil")).getByRole("button", { name: "Boil" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Matches played");
    const field = (label: string) =>
      within(dialog).getByText(label, { selector: "dt" }).nextElementSibling;
    expect(field("Matches played")).toHaveTextContent("12");
    expect(field("Cut short")).toHaveTextContent("3");
    expect(field("Frags")).toHaveTextContent("1,380");
    const gametypes = within(
      within(dialog).getByRole("table", { name: "Matches per gametype" }),
    );
    expect(gametypes.getByText("unknown")).toBeInTheDocument();
    const fraggers = within(within(dialog).getByRole("table", { name: "Top fraggers" }));
    expect(fraggers.getByText("[BOT]Rex")).toBeInTheDocument();
    expect(fraggers.getByText("bot")).toBeInTheDocument();
  });

  it("opens from the table row title too", async () => {
    await openMaps(undefined, { "GET /api/maps/boil/stats": () => stats() }, withPlayed);
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    await userEvent.click(within(row("Boil")).getByRole("button", { name: "Boil" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await screen.findByText("Matches played");
  });

  it("says a never-played map has not been played yet", async () => {
    await openMaps(
      undefined,
      {
        "GET /api/maps/zeta/stats": () =>
          stats({
            name: "zeta",
            played: 0,
            cut_short: 0,
            frags: 0,
            first_played: null,
            last_played: null,
            gametypes: [],
            top_fraggers: [],
          }),
      },
      withPlayed,
    );
    await userEvent.click(within(card("Zeta")).getByRole("button", { name: "Zeta" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText(/has not been played yet/),
    ).toBeInTheDocument();
    expect(within(dialog).queryByRole("table")).toBeNull();
  });

  it("shows a failed load", async () => {
    await openMaps(
      undefined,
      {
        "GET /api/maps/boil/stats": () =>
          jsonResponse({ detail: { code: "boom", message: "it broke" } }, 500),
      },
      withPlayed,
    );
    await userEvent.click(within(card("Boil")).getByRole("button", { name: "Boil" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("says player history is not being recorded", async () => {
    await openMaps(
      undefined,
      {
        "GET /api/maps/boil/stats": () =>
          jsonResponse(
            {
              detail: {
                code: "players_unavailable",
                message: "player history is not being recorded",
              },
            },
            503,
          ),
      },
      withPlayed,
    );
    await userEvent.click(within(card("Boil")).getByRole("button", { name: "Boil" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText(/history is not being recorded/),
    ).toBeInTheDocument();
  });

  it("closes with Escape or the button and leaves the view, sort and filters alone", async () => {
    await openMaps(undefined, { "GET /api/maps/boil/stats": () => stats() }, withPlayed);
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "frags");
    await userEvent.selectOptions(screen.getByLabelText("Played filter"), "played");
    const title = within(card("Boil")).getByRole("button", { name: "Boil" });
    await userEvent.click(title);
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(title).toHaveFocus();
    await userEvent.click(title);
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Close" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByLabelText("Sort by")).toHaveValue("frags");
    expect(screen.getByLabelText("Played filter")).toHaveValue("played");
    expect(screen.getByRole("button", { name: "Cards" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(listed()).toEqual(["Boil", "Cinder", "Atelier"]);
  });

  it("opens a top fragger's player dialog and closes the map dialog", async () => {
    await openMaps(
      undefined,
      {
        "GET /api/maps/boil/stats": () => stats(),
        "GET /api/players/7": () =>
          jsonResponse(makePlayerDetail({ id: 7, name: "^1Ann", plain_name: "Ann" })),
      },
      withPlayed,
    );
    await userEvent.click(within(card("Boil")).getByRole("button", { name: "Boil" }));
    const dialog = await screen.findByRole("dialog");
    const fraggers = within(
      await within(dialog).findByRole("table", { name: "Top fraggers" }),
    );
    await userEvent.click(fraggers.getByRole("button", { name: "Ann" }));
    await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
    const player = screen.getByRole("dialog");
    expect(await within(player).findByText("dRXbACYQ…")).toBeInTheDocument();
    expect(within(player).queryByText("Matches played")).toBeNull();
  });
});
