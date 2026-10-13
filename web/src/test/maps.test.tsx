import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Maps } from "../sections/Maps";
import {
  jsonResponse,
  makeMap,
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
  extra: { gametypes?: object; rotation?: object } = {},
) {
  const fetchMock = routeFetch({
    "GET /api/maps": () => jsonResponse({ maps }),
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
