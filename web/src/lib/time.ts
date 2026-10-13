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
