import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VERSION_POLL_MS } from "../api/usePanelVersion";
import {
  makePanelVersion,
  makeStatus,
  makeUpdate,
  makeUpgrade,
  mockPanelFetch,
  pushStatus,
  renderApp,
} from "./util";

describe("shell (8.2)", () => {
  it("names the application and lists every section", async () => {
    renderApp();
    expect(screen.getByText("xonotic-webui")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      "Dashboard",
      "Players",
      "Maps",
      "Settings",
      "Console",
    ]);
  });

  it("highlights the current section and switches without a reload", async () => {
    renderApp("/");
    await pushStatus(makeStatus());
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const dashboard = within(nav).getByRole("link", { name: "Dashboard" });
    const consoleLink = within(nav).getByRole("link", { name: "Console" });
    expect(dashboard).toHaveAttribute("aria-current", "page");
    expect(consoleLink).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();

    const marker = document.createElement("div");
    marker.id = "no-reload-marker";
    document.body.appendChild(marker);

    await userEvent.click(consoleLink);

    expect(await screen.findByRole("heading", { name: /Console/ })).toBeInTheDocument();
    expect(consoleLink).toHaveAttribute("aria-current", "page");
    expect(dashboard).not.toHaveAttribute("aria-current");
    // the persistent header is still there and the page was never reloaded
    expect(screen.getByText("xonotic-webui")).toBeInTheDocument();
    expect(document.getElementById("no-reload-marker")).not.toBeNull();
  });

  it("opens a deep link straight to its section", async () => {
    renderApp("/console");
    expect(await screen.findByRole("heading", { name: /Console/ })).toBeInTheDocument();
    expect(
      within(screen.getByRole("navigation", { name: "Sections" })).getByRole("link", {
        name: "Console",
      }),
    ).toHaveAttribute("aria-current", "page");
  });
});

describe("version badge and upgrade banner (7.3)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows [x.y.z] in green beside the brand when no newer release is known", async () => {
    mockPanelFetch({ "GET /api/panel/version": makePanelVersion() });
    renderApp();
    const badge = await screen.findByRole("link", { name: "[0.2.0]" });
    expect(badge).toHaveClass("is-current");
    expect(badge).not.toHaveClass("is-update");
    // beside the brand, not inside the section navigation
    expect(badge.closest(".brand-group")).toContainElement(
      screen.getByText("xonotic-webui"),
    );
    expect(
      within(screen.getByRole("navigation", { name: "Sections" })).queryByRole("link", {
        name: /0\.2\.0/,
      }),
    ).toBeNull();
  });

  it("shows [x.y.z update available] in orange when a newer release exists", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
    renderApp();
    const badge = await screen.findByRole("link", { name: "[0.2.0 update available]" });
    expect(badge).toHaveClass("is-update");
    expect(badge).not.toHaveClass("is-current");
  });

  it("claims nothing when availability has never been established", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makePanelVersion({
        latest: null,
        release_url: null,
        release_name: null,
        published_at: null,
        notes: null,
        checked_at: "2026-10-01T01:00:00+00:00",
        check_error: "release source unreachable: no route to host",
      }),
    });
    renderApp();
    const badge = await screen.findByRole("link", { name: "[0.2.0]" });
    expect(badge).not.toHaveClass("is-current");
    expect(badge).not.toHaveClass("is-update");
    // and no error reaches the header
    const header = badge.closest("header")!;
    expect(header).not.toHaveTextContent(/unreachable|error|update available/i);
  });

  it("keeps the last known state when a later check failed", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({ check_error: "release source unreachable" }),
    });
    renderApp();
    expect(
      await screen.findByRole("link", { name: "[0.2.0 update available]" }),
    ).toBeInTheDocument();
  });

  it("links to the panel page inside the interface, not to GitHub", async () => {
    mockPanelFetch({ "GET /api/panel/version": makeUpdate() });
    renderApp();
    const badge = await screen.findByRole("link", { name: /update available/ });
    expect(badge).toHaveAttribute("href", "/panel");
    expect(badge.getAttribute("target")).toBeNull();
  });

  it("changes to the update indication without a reload when a release appears", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let answer = makePanelVersion();
    mockPanelFetch({ "GET /api/panel/version": () => answer });
    renderApp();
    expect(await screen.findByRole("link", { name: "[0.2.0]" })).toBeInTheDocument();

    const marker = document.createElement("div");
    marker.id = "no-reload-marker";
    document.body.appendChild(marker);

    answer = makeUpdate();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(VERSION_POLL_MS);
    });
    expect(
      await screen.findByRole("link", { name: "[0.2.0 update available]" }),
    ).toBeInTheDocument();
    expect(document.getElementById("no-reload-marker")).not.toBeNull();
    marker.remove();
  });

  it("shows a banner naming the target version on every page while upgrading", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makeUpdate({
        upgrade: makeUpgrade({ state: "running" }),
      }),
      "GET /health": { status: "ok", version: "0.2.0" },
    });
    renderApp("/console");
    const banner = await screen.findByText(/Upgrading xonotic-webui to 0\.3\.0/);
    expect(banner).toHaveTextContent(/panel and the game server restart/);
    expect(banner.closest("[role=status]")).toHaveClass("upgrade-banner");
    // it is in the shell, so it is on the other pages too
    await userEvent.click(
      within(screen.getByRole("navigation", { name: "Sections" })).getByRole("link", {
        name: "Dashboard",
      }),
    );
    expect(screen.getByText(/Upgrading xonotic-webui to 0\.3\.0/)).toBeInTheDocument();
  });

  it("clears the banner when the upgrade failed without a restart", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let answer = makeUpdate({ upgrade: makeUpgrade() });
    mockPanelFetch({
      "GET /api/panel/version": () => answer,
      "GET /health": { status: "ok", version: "0.2.0" },
    });
    renderApp();
    await screen.findByText(/Upgrading xonotic-webui to 0\.3\.0/);
    answer = makeUpdate({ upgrade: makeUpgrade({ state: "failed", error: "boom" }) });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.queryByText(/Upgrading xonotic-webui to/)).toBeNull();
  });

  it("shows no banner when no upgrade is outstanding or the last one finished", async () => {
    mockPanelFetch({
      "GET /api/panel/version": makePanelVersion({
        upgrade: makeUpgrade({ state: "succeeded", finished_at: "2026-10-10T01:05:00Z" }),
      }),
    });
    renderApp();
    await screen.findByRole("link", { name: "[0.2.0]" });
    expect(screen.queryByText(/Upgrading xonotic-webui/)).toBeNull();
  });

  it("is built to wrap at a 375px viewport rather than overflow sideways", () => {
    // jsdom has no layout, so assert the rules that prevent sideways scrolling.
    const css = readFileSync("src/styles.css", "utf8");
    const rule = (selector: string) => {
      const m = css.match(new RegExp(`${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`));
      expect(m, `${selector} rule`).not.toBeNull();
      return m![1];
    };
    expect(rule(".app-header")).toMatch(/flex-wrap:\s*wrap/);
    expect(rule(".brand-group")).toMatch(/flex-wrap:\s*wrap/);
    expect(rule(".brand-group")).toMatch(/min-width:\s*0/);
    expect(rule(".version-badge")).toMatch(/overflow-wrap:\s*anywhere/);
    expect(rule(".upgrade-banner")).not.toMatch(/white-space:\s*nowrap/);
  });
});
