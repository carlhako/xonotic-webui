import type { components } from "./schema";

export type Status = components["schemas"]["StatusModel"];
export type Player = components["schemas"]["PlayerModel"];
export type ConsoleLine = components["schemas"]["ConsoleLineModel"];
export type RunState = Status["state"];

/** A non-2xx API response, carrying the server's stable code and message. */
export class ApiCallError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiCallError";
    this.status = status;
    this.code = code;
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
    try {
      const body = (await response.json()) as {
        detail?: { code?: string; message?: string } | string;
      };
      if (typeof body.detail === "object" && body.detail) {
        code = body.detail.code ?? code;
        message = body.detail.message ?? message;
      } else if (typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // not JSON: keep the status line
    }
    throw new ApiCallError(response.status, code, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  status: () => request<Status>("/api/status"),
  start: () => post<Status>("/api/lifecycle/start"),
  stop: () => post<Status>("/api/lifecycle/stop"),
  restart: () => post<Status>("/api/lifecycle/restart"),
  sendCommand: (command: string) => post<void>("/api/console/command", { command }),
};
