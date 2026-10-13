import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { makeStatus, pushStatus, renderApp } from "./util";

describe("shell (8.2)", () => {
  it("names the application and lists the Dashboard and Console sections", async () => {
    renderApp();
    expect(screen.getByText("xonotic-webui")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Dashboard", "Console"]);
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
