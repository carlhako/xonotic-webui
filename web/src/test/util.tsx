import { act, render, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "../App";
import { StatusProvider } from "../api/StatusContext";
import type { Status } from "../api/client";
import { FakeEventSource } from "./fakeEventSource";

export const STATUS_URL = "/api/status/stream";
export const CONSOLE_URL = "/api/console/stream";

export function makeStatus(overrides: Partial<Status> = {}): Status {
  return {
    state: "stopped",
    map: null,
    gametype: null,
    players: [],
    human_count: 0,
    bot_count: 0,
    event_log: null,
    last_crash: null,
    restart_abandoned: false,
    last_start_failure: null,
    action: null,
    ...overrides,
  };
}

/** Render one section inside the providers it needs. */
export function renderSection(ui: ReactElement) {
  return render(
    <MemoryRouter>
      <StatusProvider>{ui}</StatusProvider>
    </MemoryRouter>,
  );
}

/** Render the whole application at a route. */
export function renderApp(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );
}

/** Wait for the status stream to be opened, then push a status through it. */
export async function pushStatus(status: Status) {
  await waitFor(() => expect(FakeEventSource.byUrl(STATUS_URL)).toBeTruthy());
  act(() => FakeEventSource.byUrl(STATUS_URL)!.emit(status));
}

export async function pushConsole(line: {
  seq: number;
  kind: "output" | "command" | "marker";
  text: string;
  plain?: string;
}) {
  await waitFor(() => expect(FakeEventSource.byUrl(CONSOLE_URL)).toBeTruthy());
  act(() => FakeEventSource.byUrl(CONSOLE_URL)!.emit({ plain: line.text, ...line }));
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => handler(url, init));
  vi.stubGlobal("fetch", fn);
  return fn;
}

// -- fixtures for the panel's own version and upgrade --------------------------------------

import type { PanelVersion } from "../api/client";

export const RUNNING = "0.2.0";

export function makePanelVersion(overrides: Partial<PanelVersion> = {}): PanelVersion {
  return {
    current: RUNNING,
    latest: RUNNING,
    update_available: false,
    release_url: "https://github.com/carlhako/xonotic-webui/releases/tag/v0.2.0",
    release_name: "v0.2.0",
    published_at: "2026-10-01T00:00:00Z",
    notes: "## What's new\n\n- the **panel** page",
    checked_at: "2026-10-01T01:00:00+00:00",
    check_error: null,
    one_click_available: true,
    manual_command: null,
    upgrade: null,
    ...overrides,
  };
}

/** A newer release is available (0.3.0 over the running 0.2.0). */
export function makeUpdate(overrides: Partial<PanelVersion> = {}): PanelVersion {
  return makePanelVersion({
    latest: "0.3.0",
    update_available: true,
    release_url: "https://github.com/carlhako/xonotic-webui/releases/tag/v0.3.0",
    release_name: "v0.3.0",
    published_at: "2026-10-10T00:00:00Z",
    notes: "## Fixes\n\n- maps list, see [the docs](https://example.test/docs)",
    ...overrides,
  });
}

export function makeUpgrade(
  overrides: Partial<NonNullable<PanelVersion["upgrade"]>> = {},
): NonNullable<PanelVersion["upgrade"]> {
  return {
    state: "pending",
    from: RUNNING,
    to: "0.3.0",
    requested_at: "2026-10-10T01:00:00+00:00",
    finished_at: null,
    error: null,
    log_tail: null,
    ...overrides,
  };
}

/** Route fetches for the panel's own endpoints (and `/health`), by "METHOD path". A
 *  function value is called per request, so a test can change answers over time or throw
 *  to simulate the panel being down. Anything unrouted answers `{}` like an idle API. */
export function mockPanelFetch(routes: Record<string, unknown | (() => unknown)>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const entry = routes[key];
    if (entry === undefined) return jsonResponse({});
    const body = typeof entry === "function" ? (entry as () => unknown)() : entry;
    if (body instanceof Response) return body;
    return jsonResponse(body);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

// -- fixtures for the settings and maps sections ---------------------------------------

import type { MapInfo, Setting, SettingsView } from "../api/client";

export function makeSetting(overrides: Partial<Setting> = {}): Setting {
  return {
    key: "hostname",
    group: "identity",
    label: "Server name",
    help: "Shown in the server browser.",
    kind: "string",
    default: "Xonotic 0.8.6 Server",
    value: null,
    live_value: null,
    apply: "now",
    min: null,
    max: null,
    max_length: 100,
    choices: [],
    unit: null,
    value_labels: [],
    switch: null,
    server_cfg: false,
    ...overrides,
  };
}

export function makeSettingsView(
  settings: Setting[],
  overrides: Partial<SettingsView> = {},
): SettingsView {
  return {
    running: true,
    groups: [
      { id: "identity", label: "Identity" },
      { id: "match", label: "Match" },
      { id: "bots", label: "Bots" },
    ],
    settings,
    score_unit: "frags",
    ...overrides,
  };
}

export function makeMap(overrides: Partial<MapInfo> = {}): MapInfo {
  return {
    name: "stormkeep",
    title: "Stormkeep",
    description: "",
    author: "",
    gametypes: ["dm", "tdm"],
    has_mapinfo: true,
    preview: true,
    source: "game",
    package: "xonotic-data-maps.pk3",
    package_size: 41_943_040,
    pending_restart: false,
    played: 0,
    frags: 0,
    last_played: null,
    ...overrides,
  };
}

/** Route fetches by `METHOD path` (query strings included in the key); unknown routes
 *  fail loudly so a test never silently depends on a request it did not expect. */
export function routeFetch(routes: Record<string, (init?: RequestInit) => Response>) {
  return stubFetch((url, init) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const route = routes[key];
    if (!route) throw new Error(`unexpected request: ${key}`);
    return route(init);
  });
}

// -- fixtures for the players section ----------------------------------------------------

import type { MapStats, PlayerDetail, PlayerRow } from "../api/client";

export function makePlayerRow(overrides: Partial<PlayerRow> = {}): PlayerRow {
  return {
    id: 1,
    name: "^1Ann",
    plain_name: "Ann",
    is_bot: false,
    frags: 10,
    deaths: 5,
    kd: 2,
    suicides: 1,
    teamkills: 0,
    score: 30,
    wins: 2,
    matches: 4,
    time_playing: 3600,
    time_on_server: 7500,
    accuracy: 0.42,
    first_seen: 1_790_000_000,
    last_seen: 1_790_100_000,
    ...overrides,
  };
}

export function makeMapStats(overrides: Partial<MapStats> = {}): MapStats {
  return {
    name: "boil",
    played: 12,
    cut_short: 3,
    frags: 1380,
    first_played: 1_790_000_000,
    last_played: 1_790_900_000,
    gametypes: [
      { gametype: "dm", played: 9 },
      { gametype: "unknown", played: 3 },
    ],
    top_fraggers: [
      { player_id: 7, name: "^1Ann", frags: 500, is_bot: false },
      { player_id: 8, name: "[BOT]Rex", frags: 400, is_bot: true },
    ],
    ...overrides,
  };
}

export function makePlayerDetail(overrides: Partial<PlayerDetail> = {}): PlayerDetail {
  return {
    ...makePlayerRow(),
    aliases: [
      { name: "^1Ann", plain_name: "Ann", last_used: 1_790_100_000 },
      { name: "Old Ann", plain_name: "Old Ann", last_used: 1_790_000_000 },
    ],
    sessions: 3,
    key_prefix: "dRXbACYQ",
    damage_dealt: 1234.4,
    damage_taken: 800,
    avg_latency: 31.6,
    weapons: [
      {
        weapon: "vortex",
        frags: 7,
        hit: 50,
        fired: 100,
        cnt_hit: 5,
        cnt_fired: 10,
        accuracy: 0.5,
      },
      {
        weapon: "shotgun",
        frags: 3,
        hit: 10,
        fired: 100,
        cnt_hit: 1,
        cnt_fired: 10,
        accuracy: null,
      },
    ],
    achievements: [{ name: "firstblood", count: 2 }],
    extra: [],
    has_match_stats: true,
    ...overrides,
  };
}

// -- the live match stream -----------------------------------------------------------------

import type { Match } from "../api/client";

export const MATCH_URL = "/api/match/stream";

const COLUMNS: Match["scoreboard"]["columns"] = [
  {
    key: "score",
    label: "Score",
    primary: true,
    secondary: false,
    lower_is_better: false,
  },
  {
    key: "kills",
    label: "Kills",
    primary: false,
    secondary: false,
    lower_is_better: false,
  },
  {
    key: "deaths",
    label: "Deaths",
    primary: false,
    secondary: false,
    lower_is_better: true,
  },
];

export function makeMatch(overrides: Partial<Match> = {}): Match {
  return {
    live: true,
    map: "atelier",
    gametype: "dm",
    clock: {
      available: true,
      phase: "playing",
      paused: false,
      time_limit_s: 600,
      left_s: 400,
      elapsed_s: 200,
      overtimes: 0,
    },
    score_limit: { value: 30, unit: "frags" },
    scoreboard: {
      available: true,
      columns: COLUMNS,
      players: [],
      spectators: [],
      teams: [],
    },
    ...overrides,
  };
}

export function makeBoardPlayer(
  name: string,
  values: Record<string, number>,
  extra: Partial<Match["scoreboard"]["players"][number]> = {},
): Match["scoreboard"]["players"][number] {
  return {
    ent: 1,
    name,
    plain_name: name.replace(/\^\d/g, ""),
    bot: false,
    ping: 20,
    time_s: 125,
    team: null,
    values,
    ...extra,
  };
}

/** Wait for the match stream to be opened, then push a match state through it. */
export async function pushMatch(match: Match) {
  await waitFor(() => expect(FakeEventSource.byUrl(MATCH_URL)).toBeTruthy());
  act(() => FakeEventSource.byUrl(MATCH_URL)!.emit(match));
}
