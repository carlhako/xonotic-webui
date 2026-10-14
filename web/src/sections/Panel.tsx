import { useState } from "react";
import Markdown, { type Components } from "react-markdown";
import { useStatus } from "../api/StatusContext";
import { ApiCallError, api, type PanelVersion } from "../api/client";
import { upgradeInFlight, usePanelVersion } from "../api/usePanelVersion";
import { Confirm } from "../components/Confirm";
import { formatTimestamp } from "../lib/time";

function fmtDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

// Release notes come from GitHub: raw HTML in them is never rendered (no rehype-raw),
// unsafe URLs are dropped by react-markdown's default urlTransform, and links leave the
// interface.
const NOTES_COMPONENTS: Components = {
  a: ({ node: _node, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
};

/** The latest release's notes, whether or not it is newer than this install. */
function ReleaseNotes({ info }: { info: PanelVersion }) {
  if (!info.latest) return null;
  const date = fmtDate(info.published_at);
  // GitHub titles a release with its tag unless someone names it; only show a title that
  // says more than the version already in the heading.
  const title =
    !info.release_name || info.release_name.replace(/^v/, "") === info.latest
      ? null
      : info.release_name;
  return (
    <div className="panel release-notes">
      <h2>What's new in {info.latest}</h2>
      <div className="muted">
        {title && <>{title} · </>}
        {date ? `Published ${date}` : "Publish date unknown"}
      </div>
      {info.notes ? (
        <div className="release-notes-body" aria-label="release notes">
          <Markdown components={NOTES_COMPONENTS}>{info.notes}</Markdown>
        </div>
      ) : (
        <p className="muted">
          No release notes were published for this release.
          {info.release_url && (
            <>
              {" "}
              <a href={info.release_url} target="_blank" rel="noopener noreferrer">
                View it on GitHub
              </a>
            </>
          )}
        </p>
      )}
    </div>
  );
}

/** The installed and latest versions, the check, and the upgrade. */
function PanelCard({ info }: { info: PanelVersion }) {
  const { status, connected, stale } = useStatus();
  const { set } = usePanelVersion();
  const [working, setWorking] = useState<null | "check" | "upgrade">(null);
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const u = info.upgrade;
  const inFlight = upgradeInFlight(info);
  // Unavailable without a live connection, while the game server is starting or stopping
  // (an upgrade restarts it), and while an upgrade is already under way.
  const transition = status?.state === "starting" || status?.state === "stopping";
  const busy = !connected || stale || transition || inFlight;

  const call = async (kind: "check" | "upgrade", fn: () => Promise<PanelVersion>) => {
    setWorking(kind);
    setErr(null);
    try {
      set(await fn());
      setConfirm(false);
    } catch (e) {
      setErr(e instanceof ApiCallError ? e.message : String(e));
      setConfirm(false);
    } finally {
      setWorking(null);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(info.manual_command ?? "");
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const statusText = inFlight
    ? "Upgrading"
    : info.update_available
      ? "Update available"
      : info.latest
        ? "Up to date"
        : "Not checked";

  return (
    <div className="panel panel-card">
      <div className="cards">
        <div className="card">
          <div className="card-label">Installed</div>
          <div className="card-value">{info.current}</div>
        </div>
        <div className="card">
          <div className="card-label">Latest release</div>
          <div className="card-value">{info.latest ?? "unknown"}</div>
        </div>
        <div className="card">
          <div className="card-label">Status</div>
          <div className="card-value">{statusText}</div>
        </div>
      </div>
      <div className="muted">
        {info.checked_at
          ? `Last checked ${formatTimestamp(info.checked_at)}`
          : "Never checked"}
        {info.release_url && (
          <>
            {" · "}
            <a href={info.release_url} target="_blank" rel="noopener noreferrer">
              View on GitHub
            </a>
          </>
        )}
      </div>
      {info.check_error && (
        <div className="muted" role="status">
          The last check could not reach GitHub: {info.check_error}
        </div>
      )}

      <div className="controls-row panel-actions">
        <button
          className="btn"
          disabled={working !== null}
          onClick={() => void call("check", api.panelCheck)}
        >
          {working === "check" ? "Checking…" : "Check now"}
        </button>
        {info.update_available && info.one_click_available && info.latest && (
          <button
            className="btn btn-start"
            disabled={busy || working !== null}
            onClick={() => setConfirm(true)}
          >
            Upgrade to {info.latest}
          </button>
        )}
      </div>

      {info.update_available && !info.one_click_available && info.manual_command && (
        <div className="manual-upgrade">
          <p>
            One-click upgrade is not available on this install (it predates it, or the
            helper was removed). To upgrade, run this as root on the host. Later upgrades
            can then be done from here.
          </p>
          <div className="controls-row">
            <code aria-label="manual upgrade command">{info.manual_command}</code>
            <button className="btn" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}

      {confirm && info.latest && (
        <Confirm
          confirmLabel={`Upgrade to ${info.latest}`}
          onConfirm={() =>
            void call("upgrade", () => api.panelUpgrade(info.latest ?? ""))
          }
          onCancel={() => setConfirm(false)}
        >
          Upgrade xonotic-webui to {info.latest}?{" "}
          <strong>The game server will restart and players will be disconnected.</strong>{" "}
          The panel installs {info.latest} and restarts; this page reloads by itself when
          it is back.
        </Confirm>
      )}

      {err && (
        <div className="controls-error" role="alert">
          {err}
        </div>
      )}

      {inFlight && u && (
        <div className="muted" role="status">
          Upgrade to {u.to}{" "}
          {u.state === "running" ? "is installing" : "is waiting for the helper"}…
        </div>
      )}
      {u && !inFlight && (
        <div className={u.state === "succeeded" ? "ok" : "warn"} role="status">
          Last upgrade: {u.from ?? "?"} → {u.to ?? "?"},{" "}
          {u.state === "succeeded" ? "succeeded" : u.state}
          {u.finished_at && <> {formatTimestamp(u.finished_at)}</>}
          {u.error && <div>{u.error}</div>}
        </div>
      )}
      {u && !inFlight && u.state !== "succeeded" && u.log_tail && (
        <pre className="diag-output" aria-label="upgrade output">
          {u.log_tail}
        </pre>
      )}
    </div>
  );
}

/** The panel page, opened from the header version badge; not in the navigation bar. */
export function Panel() {
  const { stale } = useStatus();
  const { info } = usePanelVersion();
  return (
    <section className={`section panel-page${stale ? " is-stale" : ""}`}>
      <h1>Panel</h1>
      <p className="muted">
        The control panel itself, separate from the game server and its settings.
      </p>
      {info ? (
        <>
          <PanelCard info={info} />
          <ReleaseNotes info={info} />
        </>
      ) : (
        <p className="muted">Loading…</p>
      )}
    </section>
  );
}
