import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { MatchColumn, MatchTeam } from "../api/client";
import { ScoreTable } from "../components/ScoreTable";
import type { ScoreTablePlayer } from "../components/ScoreTable";

const COLUMNS: MatchColumn[] = [
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
];

function player(
  name: string,
  values: Record<string, number>,
  extra: Partial<ScoreTablePlayer> = {},
): ScoreTablePlayer {
  return {
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

const key = (p: ScoreTablePlayer) => p.plain_name;

describe("ScoreTable (6.1)", () => {
  it("shows the columns, the players in order and their time", () => {
    render(
      <ScoreTable
        columns={COLUMNS}
        players={[
          player("^1Ace", { score: 9, kills: 9 }),
          player("Bee", { score: 4.4 }, { bot: true, ping: null, time_s: null }),
        ]}
        teams={[]}
        rowKey={key}
      />,
    );
    const table = screen.getByRole("table", { name: "Scoreboard" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("#PlayerScoreKillsPingTime");
    expect(rows[1]).toHaveTextContent("1Ace99202m 5s");
    // a missing value is 0, a fractional one is rounded, and no ping or time is a dash
    expect(rows[2]).toHaveTextContent("2Beebot40——");
  });

  it("marks only a player who was not there at the end", () => {
    render(
      <ScoreTable
        columns={COLUMNS}
        players={[
          player("Stayer", { score: 5 }, { at_end: true }),
          player("Leaver", { score: 3 }, { at_end: false }),
          player("Unknown", { score: 1 }, { at_end: null }),
        ]}
        teams={[]}
        rowKey={key}
      />,
    );
    expect(screen.getAllByText("not at end")).toHaveLength(1);
    const row = screen.getByText("Leaver").closest("tr")!;
    expect(within(row).getByText("not at end")).toBeInTheDocument();
  });

  it("names are plain text unless the table is given a handler", () => {
    render(
      <ScoreTable
        columns={COLUMNS}
        players={[player("Ace", { score: 1 })]}
        teams={[]}
        rowKey={key}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("a player's name is a button that reports the player and where it was", async () => {
    const onPlayer = vi.fn();
    const ace = player("Ace", { score: 1 });
    render(
      <ScoreTable
        columns={COLUMNS}
        players={[ace, player("Bee", { score: 0 })]}
        teams={[]}
        rowKey={key}
        onPlayer={onPlayer}
      />,
    );
    const button = screen.getByRole("button", { name: "Ace" });
    await userEvent.click(button);
    expect(onPlayer).toHaveBeenCalledTimes(1);
    expect(onPlayer.mock.calls[0][0]).toBe(ace);
    expect(onPlayer.mock.calls[0][1]).toBe(button);
  });

  it("groups players under their team's totals in the team's colour", () => {
    const teams: MatchTeam[] = [
      { team: 14, color: "blue", values: { score: 8 } },
      { team: 5, color: "red", values: { score: 4 } },
    ];
    render(
      <ScoreTable
        columns={COLUMNS}
        players={[
          player("Red1", { score: 4 }, { team: 5 }),
          player("Blue1", { score: 6 }, { team: 14 }),
          player("Blue2", { score: 2 }, { team: 14 }),
          player("Nobody", { score: 0 }, { team: null }),
        ]}
        teams={teams}
        label="Final scoreboard"
        rowKey={key}
      />,
    );
    const table = screen.getByRole("table", { name: "Final scoreboard" });
    const rows = within(table).getAllByRole("row");
    expect(
      rows.map((r) => r.textContent?.replace(/\s+/g, " ").trim().slice(0, 24)),
    ).toEqual([
      expect.stringContaining("Player"),
      expect.stringContaining("Blue · 2"),
      expect.stringContaining("1Blue1"),
      expect.stringContaining("2Blue2"),
      expect.stringContaining("Red · 1"),
      expect.stringContaining("1Red1"),
      expect.stringContaining("No team · 1"),
      expect.stringContaining("1Nobody"),
    ]);
    expect(rows[1]).toHaveClass("team-blue");
    expect(rows[1]).toHaveTextContent("8");
    expect(rows[4]).toHaveClass("team-red");
  });
});
