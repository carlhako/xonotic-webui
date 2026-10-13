import type { MatchAction } from "../api/client";

/** The sentence describing an action's progress, shared with the Maps section. */
export function describeAction(action: MatchAction): string {
  const what =
    action.kind === "goto"
      ? `Going to ${action.map ?? "the map"}`
      : action.kind === "skip"
        ? "Skipping the map"
        : "Restarting the match";
  switch (action.state) {
    case "pending":
      return `${what}…`;
    case "done":
      return action.kind === "goto"
        ? `Now playing ${action.map ?? "the map"}`
        : action.kind === "skip"
          ? "Skipped: the next match has started"
          : "The match was restarted";
    case "timed_out":
      return `${what} did not complete: no new match started in time`;
  }
}
