import { useEffect, useState } from "react";
import { ApiCallError, api } from "../api/client";
import type { ApplyClass, Cvar } from "../api/client";
import { useResource } from "../api/useResource";
import { applyMessage } from "../lib/apply";

const PAGE = 25;

function OverrideEditor({
  name,
  initial,
  disabled,
  onDone,
  onCancel,
}: {
  name: string;
  initial: string;
  disabled: boolean;
  onDone: (apply: ApplyClass) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.putOverride(name, value);
      onDone(result.apply);
    } catch (e) {
      setError(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="override-editor">
      <input
        type="text"
        aria-label={`Value for ${name}`}
        value={value}
        disabled={disabled || busy}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void submit();
        }}
      />
      <button
        className="btn btn-save"
        disabled={disabled || busy}
        onClick={() => void submit()}
      >
        Set override
      </button>
      <button className="btn" onClick={onCancel}>
        Cancel
      </button>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function CvarRow({
  cvar,
  running,
  disabled,
  editing,
  onEdit,
  onCancel,
  onSaved,
}: {
  cvar: Cvar;
  running: boolean;
  disabled: boolean;
  editing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSaved: (apply: ApplyClass) => void;
}) {
  return (
    <li className="cvar">
      <div className="cvar-head">
        <code className="cvar-name">{cvar.name}</code>
        {cvar.override !== null && <span className="badge">overridden</span>}
        {cvar.server_cfg && <span className="badge badge-warn">in server.cfg</span>}
        {!cvar.editable && <span className="badge">reserved</span>}
      </div>
      <p className="muted cvar-desc">{cvar.description || "no description"}</p>
      <p className="muted cvar-meta">
        default: <code>{cvar.default === "" ? "(empty)" : cvar.default}</code>
        {running && cvar.live_value !== null && (
          <>
            {" "}
            · now: <code>{cvar.live_value === "" ? "(empty)" : cvar.live_value}</code>
          </>
        )}
        {cvar.override !== null && (
          <>
            {" "}
            · override: <code>{cvar.override}</code>
          </>
        )}
      </p>
      {cvar.editable && !editing && (
        <button className="btn" disabled={disabled} onClick={onEdit}>
          {cvar.override === null ? "Override…" : "Change override…"}
        </button>
      )}
      {editing && (
        <OverrideEditor
          name={cvar.name}
          initial={cvar.override ?? cvar.live_value ?? cvar.default}
          disabled={disabled}
          onDone={onSaved}
          onCancel={onCancel}
        />
      )}
    </li>
  );
}

export function RawCvars({ running, disabled }: { running: boolean; disabled: boolean }) {
  const [query, setQuery] = useState("");
  const [term, setTerm] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [editing, setEditing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  // A short pause after typing, so the catalogue is not queried on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setTerm(query.trim());
      setLimit(PAGE);
    }, 200);
    return () => clearTimeout(t);
  }, [query]);

  const overrides = useResource(() => api.overrides(), []);
  const results = useResource(() => api.cvars(term, 0, limit), [term, limit]);

  function saved(name: string, apply: ApplyClass) {
    setEditing(null);
    setNotice(`${name}: ${applyMessage(apply, running)}`);
    overrides.reload();
    results.reload();
  }

  async function remove(name: string) {
    try {
      const result = await api.deleteOverride(name);
      setNotice(`${name} removed; ${applyMessage(result.apply, running).toLowerCase()}`);
      overrides.reload();
      results.reload();
    } catch (e) {
      setNotice(e instanceof ApiCallError ? e.message : String(e));
    }
  }

  const page = results.data;
  const list = overrides.data?.overrides ?? [];

  return (
    <div className="panel raw-cvars">
      <h2>Overrides</h2>
      <p className="muted">
        Raw overrides are applied after the settings above and win over them. They may
        need a map change or restart to take effect. The cvars the panel itself depends on
        are reserved.
      </p>
      {notice && (
        <p role="status" className="field-feedback">
          {notice}
        </p>
      )}
      {list.length === 0 ? (
        <p className="muted">No raw overrides.</p>
      ) : (
        <ul className="override-list">
          {list.map((o) => (
            <li key={o.name} className="override">
              <code className="cvar-name">{o.name}</code>
              <span>
                = <code>{o.value}</code>
              </span>
              {running && o.live_value !== null && o.live_value !== o.value && (
                <span className="muted">
                  (now: <code>{o.live_value}</code>)
                </span>
              )}
              <span className="override-actions">
                <button
                  className="link"
                  disabled={disabled}
                  onClick={() => setEditing(o.name)}
                >
                  edit
                </button>
                <button
                  className="link"
                  disabled={disabled}
                  aria-label={`Remove ${o.name}`}
                  onClick={() => void remove(o.name)}
                >
                  remove
                </button>
              </span>
              {editing === o.name && (
                <OverrideEditor
                  name={o.name}
                  initial={o.value}
                  disabled={disabled}
                  onDone={(apply) => saved(o.name, apply)}
                  onCancel={() => setEditing(null)}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="override-add">
        <input
          type="text"
          aria-label="Cvar name"
          placeholder="any cvar name"
          value={newName}
          disabled={disabled}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button
          className="btn"
          disabled={disabled || newName.trim() === ""}
          onClick={() => setEditing(`new:${newName.trim()}`)}
        >
          Add override…
        </button>
      </div>
      {editing?.startsWith("new:") && (
        <OverrideEditor
          name={editing.slice(4)}
          initial=""
          disabled={disabled}
          onDone={(apply) => {
            saved(editing.slice(4), apply);
            setNewName("");
          }}
          onCancel={() => setEditing(null)}
        />
      )}

      <h2 className="spaced">Find a cvar</h2>
      <input
        type="search"
        className="cvar-search"
        aria-label="Search cvars"
        placeholder="search by name or description"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {results.error && (
        <div className="controls-error" role="alert">
          {results.error}
        </div>
      )}
      {page && (
        <>
          <p className="muted" role="status">
            {page.total} {page.total === 1 ? "cvar" : "cvars"}
            {running ? "" : " · live values appear while the server is running"}
          </p>
          <ul className="cvar-list">
            {page.items.map((c) => (
              <CvarRow
                key={c.name}
                cvar={c}
                running={running}
                disabled={disabled}
                editing={editing === c.name}
                onEdit={() => setEditing(c.name)}
                onCancel={() => setEditing(null)}
                onSaved={(apply) => saved(c.name, apply)}
              />
            ))}
          </ul>
          {page.items.length < page.total && (
            <button className="btn" onClick={() => setLimit((l) => l + PAGE)}>
              Show more
            </button>
          )}
        </>
      )}
    </div>
  );
}
