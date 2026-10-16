import type { MatchOutcome, MatchSummary, MatchWinner } from "../api/client";
import { ColoredText } from "./ColoredText";

const OUTCOMES: Record<MatchOutcome, { label: string; hint: string }> = {
  finished: { label: "Finished", hint: "Ran to its limit" },
  cut_short: { label: "Cut short", hint: "Ended early by a map change, vote or stop" },
  in_progress: { label: "In progress", hint: "Being played now" },
  no_report: { label: "No report", hint: "Ended without an end-of-match report" },
};

/** How a match ended, as a badge. */
export function Outcome({ outcome }: { outcome: MatchOutcome }) {
  const o = OUTCOMES[outcome];
  return (
    <span className={`badge badge-outcome badge-${outcome}`} title={o.hint}>
      {o.label}
    </span>
  );
}

/** The "vs bots" tag, when it applies. */
export function VsBots({ match }: { match: Pick<MatchSummary, "vs_bots"> }) {
  if (!match.vs_bots) return null;
  return (
    <span className="badge badge-vs-bots" title="One human against bots">
      vs bots
    </span>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Who took part: "1 + 3 bots", or "2 humans" when there were no bots. */
export function Players({ match }: { match: Pick<MatchSummary, "humans" | "bots"> }) {
  const { humans, bots } = match;
  if (bots === 0) return <span>{plural(humans, "human")}</span>;
  return (
    <span title={`${plural(humans, "human")} and ${plural(bots, "bot")}`}>
      {humans} + {plural(bots, "bot")}
    </span>
  );
}

const TEAM_NAMES: Record<string, string> = {
  red: "Red",
  blue: "Blue",
  yellow: "Yellow",
  pink: "Pink",
};

/** The winning team (with its colour) or player, or a dash when there is none. */
export function Winner({ winner }: { winner: MatchWinner | null }) {
  if (winner === null) return <span className="muted">–</span>;
  if (winner.kind === "team") {
    const color = winner.color ?? "none";
    return (
      <span className={`winner-team team-${color}`}>
        <span className="team-swatch" aria-hidden="true" />
        {winner.color ? TEAM_NAMES[winner.color] : `Team ${winner.team}`}
      </span>
    );
  }
  return (
    <span>
      <span className="xon-text" title={winner.plain_name}>
        <ColoredText text={winner.name} />
      </span>
      {winner.others > 0 && <span className="muted"> +{winner.others}</span>}
    </span>
  );
}
