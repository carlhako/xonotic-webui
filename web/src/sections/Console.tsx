import { useEffect, useRef, useState } from "react";
import { useConsole } from "../api/useConsole";
import { useStatus } from "../api/StatusContext";
import { ApiCallError } from "../api/client";
import { ColoredText } from "../components/ColoredText";

export function Console() {
  const { lines, connected, send } = useConsole();
  const { status } = useStatus();
  const running = status?.state === "running";
  const canSend = running && connected;

  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const el = logRef.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  function onScroll() {
    const el = logRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setPaused(!pinned.current);
  }

  function resume() {
    const el = logRef.current;
    pinned.current = true;
    setPaused(false);
    if (el) el.scrollTop = el.scrollHeight;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const command = draft.trim();
    if (!command || !canSend) return;
    setError(null);
    try {
      await send(command);
      setDraft("");
    } catch (err) {
      setError(err instanceof ApiCallError ? err.message : String(err));
    }
  }

  return (
    <section className="section console">
      <h1>
        Console
        {!connected && <span className="badge badge-warn">disconnected</span>}
      </h1>

      <div className="console-wrap">
        <div
          className="console-log xon-text"
          ref={logRef}
          onScroll={onScroll}
          role="log"
          aria-label="server console"
        >
          {lines.map((l) => (
            <div key={l.seq} className={`cl cl-${l.kind}`}>
              {l.kind === "command" ? (
                `> ${l.text}`
              ) : l.kind === "marker" ? (
                l.text
              ) : (
                <ColoredText text={l.text} />
              )}
            </div>
          ))}
          {lines.length === 0 && <div className="muted">No output yet.</div>}
        </div>
        {paused && (
          <button className="console-paused" onClick={resume}>
            Auto-scroll paused — jump to latest
          </button>
        )}
      </div>

      <form className="console-input" onSubmit={submit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            !connected
              ? "Disconnected"
              : running
                ? "Type a command"
                : "Server is not running"
          }
          disabled={!canSend}
          aria-label="console command"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
        />
        <button type="submit" className="btn" disabled={!canSend || draft.trim() === ""}>
          Send
        </button>
      </form>
      {error && (
        <div className="controls-error" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
