import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { formatTimestamp } from "../lib/time";
import { FakeEventSource } from "./fakeEventSource";
import {
  STATUS_URL,
  jsonResponse,
  makePanelVersion,
  makeStatus,
  makeUpdate,
  makeUpgrade,
  mockPanelFetch,
  pushStatus,
  renderApp,
} from "./util";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openPanel(running = true) {
  renderApp("/panel");
  await pushStatus(makeStatus({ state: running ? "running" : "stopped" }));
  return screen.findByRole("heading", { name: "Panel" });
}

const card = (label: string) =>
  screen.getByText(label, { selector: ".card-label" }).closest(".card") as HTMLElement;

const calls = (fn: ReturnType<typeof mockPanelFetch>, key: string) =>
  fn.mock.calls.filter(([url, init]) => `${init?.method ?? "GET"} ${url}` === key);

describe("panel page (8.1)", () => {
  it("shows an up-to-date install", async () => {
    mockPanelFetch({ "GET /api/panel/version": makePanelVersion() });
    await openPanel();
    expect(within(card("Installed")).getByText("0.2.0")).toBeInTheDocument();
    expect(within(card("Latest release")).getByText("0.2.0")).toBeInTheDocument();
    expect(within(card("Status")).getByText("Up to date")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Upgrade to/ })).toBeNull();
    const link = screen.getByRole("link", { name: "View on GitHub" });
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/carlhako/xonotic-webui/releases/tag/v0.2.0",
    );
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("shows the last check time in the browser's timezone", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makePanelVersion({
        checked_at: "2026-10-01T01:00:00+00:00",
      }),
    });
    await openPanel();
    expect(
      screen.getByText(
        new RegExp(`Last checked ${formatTimestamp("2026-10-01T01:00:00+00:00")}`),
      ),
    ).toBeInTheDocument();
  });

  it("shows an available update with its upgrade action", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
    await openPanel();
    expect(within(card("Latest release")).getByText("0.3.0")).toBeInTheDocument();
    expect(within(card("Status")).getByText("Update available")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upgrade to 0.3.0" })).toBeEnabled();
  });

  it("says so when it has never checked", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makePanelVersion({
        latest: null,
        release_url: null,
        release_name: null,
        published_at: null,
        notes: null,
        checked_at: null,
      }),
    });
    await openPanel();
    expect(within(card("Status")).getByText("Not checked")).toBeInTheDocument();
    expect(within(card("Latest release")).getByText("unknown")).toBeInTheDocument();
    expect(screen.getByText(/Never checked/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View on GitHub" })).toBeNull();
    expect(screen.queryByText(/What's new in/)).toBeNull();
  });

  it("states that the release source could not be reached, with the reason", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({
        check_error: "release source refused the request (HTTP 403)",
      }),
    });
    await openPanel();
    expect(
      screen.getByText(
        /could not reach GitHub: release source refused the request \(HTTP 403\)/,
      ),
    ).toBeInTheDocument();
  });

  it("checks now and shows the result on the page and in the header", async () => {
    const fetchFn = mockPanelFetch({
      "GET /api/panel/version": makePanelVersion(),
      "POST /api/panel/check": makeUpdate(),
    });
    await openPanel();
    expect(await screen.findByRole("link", { name: "[0.2.0]" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check now" }));
    expect(
      await screen.findByRole("button", { name: "Upgrade to 0.3.0" }),
    ).toBeInTheDocument();
    expect(calls(fetchFn, "POST /api/panel/check")).toHaveLength(1);
    expect(
      screen.getByRole("link", { name: "[0.2.0 update available]" }),
    ).toBeInTheDocument();
  });

  it("reports a successful last upgrade", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makePanelVersion({
        current: "0.2.0",
        upgrade: makeUpgrade({
          state: "succeeded",
          from: "0.1.1",
          to: "0.2.0",
          finished_at: "2026-10-10T01:05:00+00:00",
        }),
      }),
    });
    await openPanel();
    const outcome = screen.getByText(/Last upgrade: 0\.1\.1 → 0\.2\.0, succeeded/);
    expect(outcome).toHaveClass("ok");
    expect(screen.queryByLabelText("upgrade output")).toBeNull();
  });

  it("reports a failed last upgrade with the installer's output", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({
        upgrade: makeUpgrade({
          state: "failed",
          from: "0.2.0",
          to: "0.3.0",
          finished_at: "2026-10-10T01:05:00+00:00",
          error: "the installer exited with status 1",
          log_tail: "==> restoring the previous version\nXX 0.3.0 did not start",
        }),
      }),
    });
    await openPanel();
    expect(screen.getByText(/Last upgrade: 0\.2\.0 → 0\.3\.0, failed/)).toHaveClass(
      "warn",
    );
    expect(screen.getByText("the installer exited with status 1")).toBeInTheDocument();
    expect(screen.getByLabelText("upgrade output")).toHaveTextContent(
      "XX 0.3.0 did not start",
    );
  });

  it("is routed but not listed in the navigation, and a deep link renders it", async () => {
    mockPanelFetch({ "GET /api/panel/version": makePanelVersion() });
    renderApp("/panel");
    expect(await screen.findByRole("heading", { name: "Panel" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(within(nav).queryByRole("link", { name: "Panel" })).toBeNull();
    expect(
      within(nav)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual(["Dashboard", "Players", "Matches", "Maps", "Settings", "Console"]);
  });

  it("is opened by the header version", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
    renderApp("/");
    await userEvent.click(await screen.findByRole("link", { name: /update available/ }));
    expect(await screen.findByRole("heading", { name: "Panel" })).toBeInTheDocument();
  });
});

describe("upgrade action (8.2)", () => {
  it("asks for confirmation naming the restart, and requests only on confirm", async () => {
    const fetchFn = mockPanelFetch({
      "GET /api/panel/version": makeUpdate(),
      "POST /api/panel/upgrade": makeUpdate({ upgrade: makeUpgrade() }),
    });
    await openPanel();
    await userEvent.click(screen.getByRole("button", { name: "Upgrade to 0.3.0" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(
      /game server will restart and players will be disconnected/,
    );
    expect(calls(fetchFn, "POST /api/panel/upgrade")).toHaveLength(0);

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Upgrade to 0.3.0" }),
    );
    await waitFor(() =>
      expect(calls(fetchFn, "POST /api/panel/upgrade")).toHaveLength(1),
    );
    const [, init] = calls(fetchFn, "POST /api/panel/upgrade")[0];
    expect(JSON.parse(String(init?.body))).toEqual({ version: "0.3.0" });
    // and the page now reports it in flight
    expect(
      await screen.findByText(/Upgrade to 0\.3\.0 is waiting for the helper/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("makes no request when the confirmation is cancelled", async () => {
    const fetchFn = mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
    await openPanel();
    await userEvent.click(screen.getByRole("button", { name: "Upgrade to 0.3.0" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Cancel",
      }),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(calls(fetchFn, "POST /api/panel/upgrade")).toHaveLength(0);
  });

  it("shows the manual command with a copy action, and no upgrade button, without the helper", async () => {
    const command =
      "curl -fsSL https://github.com/carlhako/xonotic-webui/releases/latest/download/install.sh | bash";
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({
        one_click_available: false,
        manual_command: command,
      }),
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    await openPanel();
    expect(screen.queryByRole("button", { name: /^Upgrade to/ })).toBeNull();
    expect(screen.getByLabelText("manual upgrade command")).toHaveTextContent(command);
    await userEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith(command);
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows the reason an upgrade was refused", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate(),
      "POST /api/panel/upgrade": jsonResponse(
        {
          detail: {
            code: "transition_in_progress",
            message:
              "the game server is starting or stopping; try again when it has finished",
          },
        },
        409,
      ),
    });
    await openPanel();
    await userEvent.click(screen.getByRole("button", { name: "Upgrade to 0.3.0" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Upgrade to 0.3.0",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the game server is starting or stopping; try again when it has finished",
    );
    // the page is still usable: the action is back
    expect(screen.getByRole("button", { name: "Upgrade to 0.3.0" })).toBeEnabled();
  });

  it("is unavailable while disconnected", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
    await openPanel();
    expect(screen.getByRole("button", { name: "Upgrade to 0.3.0" })).toBeEnabled();
    act(() => FakeEventSource.byUrl(STATUS_URL)!.fail());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Upgrade to 0.3.0" })).toBeDisabled(),
    );
  });

  it.each(["starting", "stopping"] as const)(
    "is unavailable while the game server is %s",
    async (state) => {
      mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
      renderApp("/panel");
      await pushStatus(makeStatus({ state }));
      expect(
        await screen.findByRole("button", { name: "Upgrade to 0.3.0" }),
      ).toBeDisabled();
    },
  );

  it("is available while the game server is stopped", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
    await openPanel(false);
    expect(await screen.findByRole("button", { name: "Upgrade to 0.3.0" })).toBeEnabled();
  });

  it("is unavailable while an upgrade is already in flight", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({
        upgrade: makeUpgrade({ state: "running" }),
      }),
      "GET /health": { status: "ok", version: "0.2.0" },
    });
    await openPanel();
    expect(
      await screen.findByRole("button", { name: "Upgrade to 0.3.0" }),
    ).toBeDisabled();
    expect(within(card("Status")).getByText("Upgrading")).toBeInTheDocument();
    expect(screen.getByText(/Upgrade to 0\.3\.0 is installing/)).toBeInTheDocument();
  });
});

describe("release notes (8.3)", () => {
  it("renders the latest release's notes with its version and date", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({
        release_name: "Maps overhaul",
        notes: "## Fixes\n\n- the maps list\n- `code` item",
      }),
    });
    await openPanel();
    expect(
      screen.getByRole("heading", { name: "What's new in 0.3.0" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Maps overhaul · Published/)).toBeInTheDocument();
    const notes = screen.getByLabelText("release notes");
    expect(within(notes).getByRole("heading", { name: "Fixes" })).toBeInTheDocument();
    expect(within(notes).getAllByRole("listitem")).toHaveLength(2);
  });

  it("shows no title when it only repeats the version", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate({ release_name: "v0.3.0" }) });
    await openPanel();
    expect(screen.getByText(/^Published /)).toBeInTheDocument();
  });

  it("shows the notes of the running release when it is the latest", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makePanelVersion({ notes: "- the **panel** page" }),
    });
    await openPanel();
    expect(
      screen.getByRole("heading", { name: "What's new in 0.2.0" }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("release notes")).getByText("panel"),
    ).toBeInTheDocument();
  });

  it("does not render raw HTML or run script from the notes", async () => {
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({
        notes:
          'safe text\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(2)">\n\n[x](javascript:alert(3))',
      }),
    });
    await openPanel();
    const notes = screen.getByLabelText("release notes");
    expect(notes).toHaveTextContent("safe text");
    expect(notes.querySelector("script, img, [onerror]")).toBeNull();
    expect(notes.querySelector('a[href^="javascript"]')).toBeNull();
    expect(alert).not.toHaveBeenCalled();
  });

  it("opens links outside the interface", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
    await openPanel();
    const link = within(screen.getByLabelText("release notes")).getByRole("link", {
      name: "the docs",
    });
    expect(link).toHaveAttribute("href", "https://example.test/docs");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.getAttribute("rel")).toContain("noreferrer");
  });

  it("states that no notes were published and still links to the release", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate({ notes: null }) });
    await openPanel();
    expect(screen.getByText(/No release notes were published/)).toBeInTheDocument();
    expect(screen.queryByLabelText("release notes")).toBeNull();
    expect(screen.getByRole("link", { name: "View it on GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/carlhako/xonotic-webui/releases/tag/v0.3.0",
    );
  });
});
