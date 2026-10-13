import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Settings } from "../sections/Settings";
import { FakeEventSource } from "./fakeEventSource";
import {
  STATUS_URL,
  jsonResponse,
  makeSetting,
  makeSettingsView,
  makeStatus,
  pushStatus,
  renderSection,
  routeFetch,
} from "./util";

afterEach(() => vi.unstubAllGlobals());

const hostname = makeSetting({ live_value: "spike" });
const skill = makeSetting({
  key: "skill",
  group: "bots",
  label: "Bot skill",
  kind: "int",
  default: 8,
  min: 0,
  max: 10,
  max_length: null,
  apply: "now",
});
const maxplayers = makeSetting({
  key: "maxplayers",
  group: "identity",
  label: "Maximum players",
  kind: "int",
  default: 16,
  min: 1,
  max: 255,
  max_length: null,
  apply: "next_start",
});
const timelimit = makeSetting({
  key: "timelimit_override",
  group: "match",
  label: "Time limit",
  kind: "int",
  default: -1,
  min: -1,
  max: 1440,
  max_length: null,
  apply: "next_map",
  unit: "minutes",
  value_labels: [
    { value: -1, label: "Map default" },
    { value: 0, label: "No limit" },
  ],
});
const scorelimit = makeSetting({
  key: "fraglimit_override",
  group: "match",
  label: "Score limit",
  kind: "int",
  default: -1,
  min: -1,
  max: 100000,
  max_length: null,
  unit: "score",
});
const instagib = makeSetting({
  key: "g_instagib",
  group: "match",
  label: "Instagib",
  kind: "bool",
  default: false,
  max_length: null,
  apply: "next_map",
});

function view(
  settings = [hostname, maxplayers, timelimit, scorelimit, instagib, skill],
  o = {},
) {
  return makeSettingsView(settings, o);
}

async function openSettings(
  settingsView = view(),
  extra: Record<string, () => Response> = {},
) {
  const fetchMock = routeFetch({
    "GET /api/settings": () => jsonResponse(settingsView),
    ...extra,
  });
  renderSection(<Settings />);
  await pushStatus(makeStatus({ state: "running" }));
  await screen.findByRole("tab", { name: "Identity" });
  return fetchMock;
}

describe("curated settings (6.1)", () => {
  it("renders the tabs and fields from the API metadata", async () => {
    await openSettings();
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Identity", "Match", "Bots", "Raw cvars"]);
    expect(screen.getByLabelText("Server name")).toHaveValue("Xonotic 0.8.6 Server");
    expect(screen.getByText(/default: Xonotic 0\.8\.6 Server/)).toBeInTheDocument();
    // what the running server currently has
    expect(screen.getByText("spike")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Match" }));
    expect(screen.getByLabelText("Time limit")).toHaveValue(-1);
    expect(screen.getByText("Map default")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Instagib" })).not.toBeChecked();
  });

  it("marks a setting that server.cfg also sets", async () => {
    await openSettings(view([makeSetting({ server_cfg: true }), maxplayers]));
    const field = screen.getByLabelText("Server name").closest(".field") as HTMLElement;
    expect(within(field).getByText("also set in server.cfg")).toBeInTheDocument();
    const other = screen
      .getByLabelText("Maximum players")
      .closest(".field") as HTMLElement;
    expect(within(other).queryByText("also set in server.cfg")).toBeNull();
  });

  it("labels the score limit with the current gametype's unit", async () => {
    await openSettings(view(undefined, { score_unit: "captures" }));
    await userEvent.click(screen.getByRole("tab", { name: "Match" }));
    const field = screen.getByLabelText("Score limit").closest(".field") as HTMLElement;
    expect(within(field).getByText("captures")).toBeInTheDocument();
    expect(
      within(
        screen.getByLabelText("Time limit").closest(".field") as HTMLElement,
      ).getByText("minutes"),
    ).toBeInTheDocument();
  });

  it("saves only what changed and says the change was applied now", async () => {
    const fetchMock = await openSettings(view(), {
      "PATCH /api/settings": () => jsonResponse({ applied: { hostname: "now" } }),
    });
    const save = screen.getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();
    const input = screen.getByLabelText("Server name");
    await userEvent.clear(input);
    await userEvent.type(input, "LAN Party");
    await userEvent.click(save);

    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(call![1]!.body as string)).toEqual({ hostname: "LAN Party" });
    expect(await screen.findByRole("status", { name: "" })).toBeDefined();
    await waitFor(() => expect(screen.getByText("Applied")).toBeInTheDocument());
  });

  it("says when a change applies at the next map", async () => {
    await openSettings(view(), {
      "PATCH /api/settings": () => jsonResponse({ applied: { g_instagib: "next_map" } }),
    });
    await userEvent.click(screen.getByRole("tab", { name: "Match" }));
    await userEvent.click(screen.getByRole("switch", { name: "Instagib" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Applies at the next map")).toBeInTheDocument();
  });

  it("says when a change needs a restart and offers one", async () => {
    const fetchMock = await openSettings(view(), {
      "PATCH /api/settings": () =>
        jsonResponse({ applied: { maxplayers: "next_start" } }),
      "POST /api/lifecycle/restart": () => jsonResponse(makeStatus({ state: "running" })),
    });
    const input = screen.getByLabelText("Maximum players");
    await userEvent.clear(input);
    await userEvent.type(input, "8");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText("Applies when the server restarts"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Restart the server to apply/)).toBeInTheDocument();
    expect(screen.getByText(/Maximum players\./)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Restart now" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/lifecycle/restart", expect.anything());
  });

  it("asks before restarting when players are connected", async () => {
    const fetchMock = await openSettings(view(), {
      "PATCH /api/settings": () =>
        jsonResponse({ applied: { maxplayers: "next_start" } }),
      "POST /api/lifecycle/restart": () => jsonResponse(makeStatus({ state: "running" })),
    });
    await pushStatus(
      makeStatus({
        state: "running",
        human_count: 2,
        players: [
          { id: 1, ent: 1, name: "a", plain_name: "a", bot: false },
          { id: 2, ent: 2, name: "b", plain_name: "b", bot: false },
        ],
      }),
    );
    const input = screen.getByLabelText("Maximum players");
    await userEvent.clear(input);
    await userEvent.type(input, "8");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await userEvent.click(await screen.findByRole("button", { name: "Restart now" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("2 players will be disconnected");
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/lifecycle/restart",
      expect.anything(),
    );
  });

  it("shows the server's validation error on the field and changes nothing else", async () => {
    await openSettings(view(), {
      "PATCH /api/settings": () =>
        jsonResponse(
          {
            detail: {
              code: "invalid_setting",
              message: "Bot skill must be between 0 and 10",
              field: "skill",
            },
          },
          422,
        ),
    });
    await userEvent.click(screen.getByRole("tab", { name: "Bots" }));
    const input = screen.getByLabelText("Bot skill");
    await userEvent.clear(input);
    await userEvent.type(input, "99");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const field = input.closest(".field") as HTMLElement;
    expect(await within(field).findByRole("alert")).toHaveTextContent("between 0 and 10");
    // the edit is kept so it can be corrected
    expect(input).toHaveValue(99);
  });

  it("explains a non-numeric entry without calling the server", async () => {
    const fetchMock = await openSettings();
    await userEvent.click(screen.getByRole("tab", { name: "Bots" }));
    const input = screen.getByLabelText("Bot skill");
    await userEvent.clear(input);
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must be a number");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(false);
  });

  it("resets a setting to its default with null", async () => {
    const fetchMock = await openSettings(
      view([makeSetting({ value: "LAN Party" }), skill]),
      {
        "PATCH /api/settings": () => jsonResponse({ applied: { hostname: "now" } }),
      },
    );
    expect(screen.getByLabelText("Server name")).toHaveValue("LAN Party");
    await userEvent.click(screen.getByRole("button", { name: "use default" }));
    expect(screen.getByLabelText("Server name")).toHaveValue("Xonotic 0.8.6 Server");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(call![1]!.body as string)).toEqual({ hostname: null });
  });

  it("saved while stopped reports that it applies at the next start", async () => {
    await openSettings(view(undefined, { running: false }), {
      "PATCH /api/settings": () => jsonResponse({ applied: { hostname: "next_start" } }),
    });
    expect(screen.getByText(/The server is stopped/)).toBeInTheDocument();
    const input = screen.getByLabelText("Server name");
    await userEvent.clear(input);
    await userEvent.type(input, "x");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText("Saved; applies when the server starts"),
    ).toBeInTheDocument();
    // no restart is offered for a server that is not running
    expect(screen.queryByRole("button", { name: "Restart now" })).toBeNull();
  });

  it("disables the controls while disconnected", async () => {
    await openSettings();
    expect(screen.getByLabelText("Server name")).toBeEnabled();
    act(() => FakeEventSource.byUrl(STATUS_URL)!.fail());
    await waitFor(() => expect(screen.getByLabelText("Server name")).toBeDisabled());
    await userEvent.click(screen.getByRole("tab", { name: "Match" }));
    expect(screen.getByRole("switch", { name: "Instagib" })).toBeDisabled();
  });
});

describe("raw cvars (6.2)", () => {
  const cvar = (name: string, extra = {}) => ({
    name,
    default: "0",
    description: `${name} description`,
    editable: true,
    live_value: null,
    override: null,
    server_cfg: false,
    ...extra,
  });
  const page = (items: ReturnType<typeof cvar>[], total = items.length) => ({
    running: true,
    total,
    offset: 0,
    limit: 25,
    items,
  });

  async function openRaw(
    routes: Record<string, (init?: RequestInit) => Response> = {},
    firstName = "g_maplist",
  ) {
    const fetchMock = await openSettings(view(), {
      "GET /api/settings/overrides": () => jsonResponse({ running: true, overrides: [] }),
      "GET /api/cvars?q=&offset=0&limit=25": () =>
        jsonResponse(page([cvar("g_maplist"), cvar("sv_eventlog", { editable: false })])),
      ...routes,
    });
    await userEvent.click(screen.getByRole("tab", { name: "Raw cvars" }));
    await screen.findByText(firstName);
    return fetchMock;
  }

  it("lists catalogue results with defaults, descriptions and live values", async () => {
    await openRaw(
      {
        "GET /api/cvars?q=&offset=0&limit=25": () =>
          jsonResponse(
            page([cvar("g_maplist_votable", { default: "6", live_value: "3" })]),
          ),
      },
      "g_maplist_votable",
    );
    expect(screen.getByText("g_maplist_votable description")).toBeInTheDocument();
    expect(screen.getByText(/default:/).textContent).toContain("6");
    expect(screen.getByText(/now:/).textContent).toContain("3");
  });

  it("searches the catalogue", async () => {
    const fetchMock = await openRaw({
      "GET /api/cvars?q=votable&offset=0&limit=25": () =>
        jsonResponse(page([cvar("g_maplist_votable")])),
    });
    await userEvent.type(screen.getByLabelText("Search cvars"), "votable");
    await screen.findByText("g_maplist_votable");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/cvars?q=votable&offset=0&limit=25",
      undefined,
    );
  });

  it("adds an override and reports that it may need a restart", async () => {
    const fetchMock = await openRaw({
      "PUT /api/settings/overrides/g_maplist": () =>
        jsonResponse({ name: "g_maplist", apply: "may_need_restart" }),
    });
    await userEvent.click(screen.getAllByRole("button", { name: "Override…" })[0]);
    const value = screen.getByLabelText("Value for g_maplist");
    await userEvent.clear(value);
    await userEvent.type(value, "boil stormkeep");
    await userEvent.click(screen.getByRole("button", { name: "Set override" }));
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(call![1]!.body as string)).toEqual({ value: "boil stormkeep" });
    expect(
      await screen.findByText(/May need a map change or restart/),
    ).toBeInTheDocument();
  });

  it("removes an override", async () => {
    const fetchMock = await openRaw({
      "GET /api/settings/overrides": () =>
        jsonResponse({
          running: true,
          overrides: [
            {
              name: "g_balance_health_start",
              value: "150",
              live_value: "150",
              server_cfg: false,
            },
          ],
        }),
      "DELETE /api/settings/overrides/g_balance_health_start": () =>
        jsonResponse({ name: "g_balance_health_start", apply: "next_start" }),
    });
    expect(screen.getAllByText("g_balance_health_start").length).toBeGreaterThan(0);
    await userEvent.click(
      screen.getByRole("button", { name: "Remove g_balance_health_start" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/overrides/g_balance_health_start",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    expect(await screen.findByText(/g_balance_health_start removed/)).toBeInTheDocument();
  });

  it("shows a reserved cvar read-only", async () => {
    await openRaw();
    const row = screen.getByText("sv_eventlog").closest("li") as HTMLElement;
    expect(within(row).getByText("reserved")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /Override/ })).toBeNull();
  });

  it("shows the server's reason when an override is refused", async () => {
    await openRaw({
      "PUT /api/settings/overrides/g_maplist": () =>
        jsonResponse(
          {
            detail: {
              code: "invalid_setting",
              message: "a value must not contain a double quote",
            },
          },
          422,
        ),
    });
    await userEvent.click(screen.getAllByRole("button", { name: "Override…" })[0]);
    await userEvent.type(screen.getByLabelText("Value for g_maplist"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Set override" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("double quote");
  });
});
