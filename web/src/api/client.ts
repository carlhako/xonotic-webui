import type { components } from "./schema";

export type Status = components["schemas"]["StatusModel"];
export type Player = components["schemas"]["PlayerModel"];
export type ConsoleLine = components["schemas"]["ConsoleLineModel"];
export type RunState = Status["state"];
export type MatchAction = NonNullable<Status["action"]>;

type Schemas = components["schemas"];
export type SettingsView = Schemas["SettingsModel"];
export type Setting = Schemas["SettingModel"];
export type SettingsResult = Schemas["SettingsResultModel"];
export type ApplyClass = Schemas["SettingsResultModel"]["applied"][string];
export type OverridesView = Schemas["OverridesModel"];
export type OverrideResult = Schemas["OverrideResultModel"];
export type CvarPage = Schemas["CvarPageModel"];
export type Cvar = Schemas["CvarModel"];
export type GametypesView = Schemas["GametypesModel"];
export type GametypeResult = Schemas["GametypeResultModel"];
export type MapInfo = Schemas["MapModel"];
export type MapsView = Schemas["MapsModel"];
export type RotationView = Schemas["RotationModel"];
export type RotationResult = Schemas["RotationResultModel"];
export type SettingValue = string | number | boolean;
export type PanelVersion = Schemas["PanelVersion"];
export type PanelUpgrade = NonNullable<PanelVersion["upgrade"]>;
export type PlayerList = Schemas["PlayerList"];
export type PlayerRow = Schemas["PlayerRow"];
export type PlayerDetail = Schemas["PlayerDetail"];
export type PlayerWeapon = Schemas["PlayerWeapon"];

/** The columns the players table can be sorted by (the API's fixed list). */
export type PlayerSort =
  | "name"
  | "frags"
  | "deaths"
  | "kd"
  | "score"
  | "wins"
  | "matches"
  | "time_playing"
  | "time_on_server"
  | "accuracy"
  | "last_seen";

export interface PlayersQuery {
  sort: PlayerSort;
  order: "asc" | "desc";
  q: string;
  bots: boolean;
  limit: number;
  offset: number;
}

/** A players request answers either a fresh list or "unchanged since `etag`". */
export type PlayersResult =
  | { notModified: true; etag: string | null }
  | { notModified: false; etag: string | null; list: PlayerList };

/** A non-2xx API response, carrying the server's stable code and message. */
export class ApiCallError extends Error {
  readonly status: number;
  readonly code: string;
  /** The setting or cvar a validation error is about, when the server names one. */
  readonly field: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    field: string | null = null,
  ) {
    super(message);
    this.name = "ApiCallError";
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

async function fetchOrThrow(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init);
  } catch (e) {
    throw new ApiCallError(
      0,
      "network_error",
      e instanceof Error ? e.message : String(e),
    );
  }
}

async function errorFrom(response: Response): Promise<ApiCallError> {
  let code = "http_error";
  let message = `${response.status} ${response.statusText}`.trim();
  let field: string | null = null;
  try {
    const body = (await response.json()) as {
      detail?: { code?: string; message?: string; field?: string | null } | string;
    };
    if (typeof body.detail === "object" && body.detail) {
      code = body.detail.code ?? code;
      message = body.detail.message ?? message;
      field = body.detail.field ?? null;
    } else if (typeof body.detail === "string") {
      message = body.detail;
    }
  } catch {
    // not JSON: keep the status line
  }
  return new ApiCallError(response.status, code, message, field);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchOrThrow(path, init);
  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** The players list, conditional on the last answer's ETag (the table polls this). */
async function requestPlayers(
  query: PlayersQuery,
  etag: string | null,
): Promise<PlayersResult> {
  const params = new URLSearchParams({
    sort: query.sort,
    order: query.order,
    bots: String(query.bots),
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.q) params.set("q", query.q);
  const response = await fetchOrThrow(
    `/api/players?${params}`,
    etag ? { headers: { "If-None-Match": etag } } : undefined,
  );
  if (response.status === 304) return { notModified: true, etag };
  if (!response.ok) throw await errorFrom(response);
  return {
    notModified: false,
    etag: response.headers.get("ETag"),
    list: (await response.json()) as PlayerList,
  };
}

const send = <T>(method: string, path: string, body?: unknown) =>
  request<T>(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

const post = <T>(path: string, body?: unknown) => send<T>("POST", path, body);

export const api = {
  status: () => request<Status>("/api/status"),
  start: () => post<Status>("/api/lifecycle/start"),
  stop: () => post<Status>("/api/lifecycle/stop"),
  restart: () => post<Status>("/api/lifecycle/restart"),
  sendCommand: (command: string) => post<void>("/api/console/command", { command }),

  // server settings
  settings: () => request<SettingsView>("/api/settings"),
  saveSettings: (changes: Record<string, SettingValue | null>) =>
    send<SettingsResult>("PATCH", "/api/settings", changes),
  overrides: () => request<OverridesView>("/api/settings/overrides"),
  putOverride: (name: string, value: string) =>
    send<OverrideResult>("PUT", `/api/settings/overrides/${encodeURIComponent(name)}`, {
      value,
    }),
  deleteOverride: (name: string) =>
    send<OverrideResult>("DELETE", `/api/settings/overrides/${encodeURIComponent(name)}`),
  cvars: (q: string, offset = 0, limit = 25) =>
    request<CvarPage>(
      `/api/cvars?${new URLSearchParams({ q, offset: String(offset), limit: String(limit) })}`,
    ),

  // maps and match control
  gametypes: () => request<GametypesView>("/api/gametypes"),
  selectGametype: (gametype: string) =>
    send<GametypeResult>("PUT", "/api/gametype", { gametype }),
  maps: () => request<MapsView>("/api/maps"),
  rotation: () => request<RotationView>("/api/rotation"),
  saveRotation: (maps: string[], shuffle: boolean | null) =>
    send<RotationResult>("PUT", "/api/rotation", { maps, shuffle }),
  gotoMap: (map: string) => post<MatchAction>("/api/match/goto", { map }),
  skipMap: () => post<MatchAction>("/api/match/skip"),
  restartMatch: () => post<MatchAction>("/api/match/restart"),

  // recorded players
  players: (query: PlayersQuery, etag: string | null = null) =>
    requestPlayers(query, etag),
  player: (id: number) => request<PlayerDetail>(`/api/players/${id}`),

  // the panel's own version and upgrade
  panelVersion: () => request<PanelVersion>("/api/panel/version"),
  panelCheck: () => post<PanelVersion>("/api/panel/check"),
  panelUpgrade: (version: string) =>
    post<PanelVersion>("/api/panel/upgrade", { version }),
};
