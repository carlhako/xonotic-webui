// All timestamps are shown in the viewing browser's own timezone and never in one
// configured on the server (web-ui-shell: "Times are shown in the browser's timezone").

const formatter = () =>
  new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });

/** Format an ISO 8601 instant for display; the input is returned unchanged if invalid. */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  // Constructed per call so a changed browser/OS timezone is honoured.
  return formatter().format(date);
}

/** A length of time as `18h 2m`, `12m 5s` or `45s` (always whole units, never decimals). */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${rest}s`;
  return `${rest}s`;
}

/** An epoch-seconds instant in the browser's timezone, like {@link formatTimestamp}. */
export function formatEpoch(epochSeconds: number): string {
  return formatTimestamp(new Date(epochSeconds * 1000).toISOString());
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 86400],
  ["month", 30 * 86400],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

/** "5 minutes ago", "2 days ago" or "just now"; `nowMs` is injectable for tests. */
export function formatRelative(epochSeconds: number, nowMs: number = Date.now()): string {
  const elapsed = Math.max(0, nowMs / 1000 - epochSeconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "always" });
  for (const [unit, size] of UNITS) {
    if (elapsed >= size) return formatter.format(-Math.floor(elapsed / size), unit);
  }
  return elapsed < 10 ? "just now" : formatter.format(-Math.floor(elapsed), "second");
}

/** `m:ss`, or `h:mm:ss` from an hour up; whole seconds, never negative. */
export function formatClock(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}
