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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (e) {
    throw new ApiCallError(
      0,
      "network_error",
      e instanceof Error ? e.message : String(e),
    );
  }
  if (!response.ok) {
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
    throw new ApiCallError(response.status, code, message, field);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
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

  // the panel's own version and upgrade
  panelVersion: () => request<PanelVersion>("/api/panel/version"),
  panelCheck: () => post<PanelVersion>("/api/panel/check"),
  panelUpgrade: (version: string) =>
    post<PanelVersion>("/api/panel/upgrade", { version }),
};
