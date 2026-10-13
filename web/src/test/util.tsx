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
