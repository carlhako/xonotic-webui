import { useState } from "react";
import { ApiCallError, api } from "../api/client";
import type { ApplyClass, Setting, SettingValue, SettingsView } from "../api/client";
import { useStatus } from "../api/StatusContext";
import { useLifecycle } from "../api/useLifecycle";
import { useResource } from "../api/useResource";
import { Confirm } from "../components/Confirm";
import { omit, playersPhrase } from "../lib/text";
import { applyMessage } from "../lib/apply";
import { RawCvars } from "./RawCvars";

const RAW_TAB = "raw";

/** What the field holds while being edited: text for text and number inputs, a boolean
 *  for switches, `null` for "use the default". */
type Edit = string | boolean | null;

function baseValue(s: Setting): SettingValue {
  return s.value ?? s.default;
}

function toDisplay(s: Setting, v: SettingValue): string | boolean {
  if (s.kind === "bool") return Boolean(v);
  return String(v);
}

function describe(s: Setting, v: SettingValue): string {
  if (s.kind === "bool") return v ? "on" : "off";
  const label = s.value_labels.find((l) => String(l.value) === String(v));
  if (label) return label.label;
  return v === "" ? "(empty)" : String(v);
}

/** Convert an edit to the value to send, or an error message to show on the field. */
function toWire(s: Setting, edit: string | boolean | null): SettingValue | null | Error {
  if (edit === null) return null;
  if (s.kind === "bool") return Boolean(edit);
  if (s.kind === "int" || s.kind === "float") {
    const text = String(edit).trim();
    const n = Number(text);
    if (text === "" || Number.isNaN(n)) return new Error(`${s.label} must be a number`);
    return n;
  }
  return String(edit);
}

function unitLabel(s: Setting, scoreUnit: string | null): string | null {
  if (s.unit === "minutes") return "minutes";
  if (s.unit === "score") return scoreUnit;
  return null;
}

function Field({
  setting,
  edit,
  error,
  feedback,
  running,
  scoreUnit,
  disabled,
  onChange,
}: {
  setting: Setting;
  edit: Edit | undefined;
  error?: string;
  feedback?: ApplyClass;
  running: boolean;
  scoreUnit: string | null;
  disabled: boolean;
  onChange: (value: Edit) => void;
}) {
  const id = `setting-${setting.key}`;
  const edited = edit !== undefined;
  const shown: string | boolean =
    edit === null
      ? toDisplay(setting, setting.default)
      : edit === undefined
        ? toDisplay(setting, baseValue(setting))
        : edit;
  const resetting = edit === null;
  const hasSaved = setting.value !== null;
  const unit = unitLabel(setting, scoreUnit);

  let control;
  if (setting.kind === "bool") {
    control = (
      <input
        id={id}
        type="checkbox"
        role="switch"
        checked={Boolean(shown)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  } else if (setting.kind === "choice") {
    control = (
      <select
        id={id}
        value={String(shown)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {setting.choices.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
    );
  } else {
    const numeric = setting.kind === "int" || setting.kind === "float";
    control = (
      <input
        id={id}
        type={numeric ? "number" : "text"}
        inputMode={numeric ? "numeric" : undefined}
        min={numeric ? (setting.min ?? undefined) : undefined}
        max={numeric ? (setting.max ?? undefined) : undefined}
        maxLength={setting.max_length ?? undefined}
        value={String(shown)}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={`${id}-help`}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  const labelled =
    (setting.kind === "int" || setting.kind === "float") &&
    setting.value_labels.find((l) => String(l.value) === String(shown));

  return (
    <div className={`field${error ? " has-error" : ""}`}>
      <div className="field-head">
        <label htmlFor={id}>{setting.label}</label>
        {setting.server_cfg && (
          <span
            className="badge badge-warn"
            title="server.cfg also sets this; the panel's value wins"
          >
            also set in server.cfg
          </span>
        )}
      </div>
      <div className="field-control">
        {control}
        {unit && <span className="muted">{unit}</span>}
        {labelled && <span className="muted">{labelled.label}</span>}
        {(hasSaved || edited) && !resetting && (
          <button
            type="button"
            className="link"
            disabled={disabled}
            onClick={() => onChange(null)}
          >
            use default
          </button>
        )}
        {resetting && <span className="muted">default will be used</span>}
      </div>
      <p className="field-help muted" id={`${id}-help`}>
        {setting.help}
      </p>
      <p className="field-meta muted">
        default: {describe(setting, setting.default)}
        {running && setting.live_value !== null && (
          <>
            {" "}
            · on the server now:{" "}
            <code>{setting.live_value === "" ? "(empty)" : setting.live_value}</code>
          </>
        )}
      </p>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      {feedback && !error && (
        <p className="field-feedback" role="status">
          {applyMessage(feedback, running)}
        </p>
      )}
    </div>
  );
}

function SettingsPanel({
  view,
  group,
  disabled,
  reload,
}: {
  view: SettingsView;
  group: string;
  disabled: boolean;
  reload: () => void;
}) {
  const { status } = useStatus();
  const { run } = useLifecycle();
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, ApplyClass>>({});
  const [saving, setSaving] = useState(false);
  const [restartFor, setRestartFor] = useState<string[]>([]);
  const [confirmingRestart, setConfirmingRestart] = useState(false);

  const settings = view.settings.filter((s) => s.group === group);
  const dirty = settings.filter((s) => edits[s.key] !== undefined);
  const humans = status?.human_count ?? 0;

  function change(key: string, value: Edit) {
    setEdits((e) => ({ ...e, [key]: value }));
    setFeedback((f) => omit(f, key));
    setErrors((e) => omit(e, key));
  }

  async function save() {
    const changes: Record<string, SettingValue | null> = {};
    const problems: Record<string, string> = {};
    for (const s of dirty) {
      const wire = toWire(s, edits[s.key] as Edit);
      if (wire instanceof Error) problems[s.key] = wire.message;
      else changes[s.key] = wire;
    }
    setErrors(problems);
    setGeneral(null);
    if (Object.keys(problems).length > 0 || Object.keys(changes).length === 0) return;
    setSaving(true);
    try {
      const result = await api.saveSettings(changes);
      setFeedback((f) => ({ ...f, ...result.applied }));
      setEdits((e) => {
        const next = { ...e };
        for (const key of Object.keys(changes)) delete next[key];
        return next;
      });
      const needing = Object.entries(result.applied)
        .filter(([, apply]) => apply === "next_start")
        .map(([key]) => key);
      setRestartFor(view.running ? needing : []);
      reload();
    } catch (e) {
      if (
        e instanceof ApiCallError &&
        e.field &&
        settings.some((s) => s.key === e.field)
      ) {
        setErrors({ [e.field]: e.message });
      } else {
        setGeneral(e instanceof ApiCallError ? e.message : String(e));
      }
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    setEdits({});
    setErrors({});
    setGeneral(null);
  }

  function restart() {
    if (humans > 0) {
      setConfirmingRestart(true);
      return;
    }
    void doRestart();
  }

  async function doRestart() {
    setConfirmingRestart(false);
    setRestartFor([]);
    await run("restart");
  }

  const labelFor = (key: string) =>
    view.settings.find((s) => s.key === key)?.label ?? key;

  return (
    <div className="panel settings-panel">
      {settings.map((s) => (
        <Field
          key={s.key}
          setting={s}
          edit={edits[s.key]}
          error={errors[s.key]}
          feedback={feedback[s.key]}
          running={view.running}
          scoreUnit={view.score_unit}
          disabled={disabled}
          onChange={(v) => change(s.key, v)}
        />
      ))}

      <div className="controls-row">
        <button
          className="btn btn-save"
          disabled={disabled || saving || dirty.length === 0}
          onClick={() => void save()}
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
        <button
          className="btn"
          disabled={disabled || saving || dirty.length === 0}
          onClick={discard}
        >
          Discard
        </button>
      </div>

      {general && (
        <div className="controls-error" role="alert">
          {general}
        </div>
      )}

      {restartFor.length > 0 && !confirmingRestart && (
        <div className="panel is-warn" role="status">
          <p>
            <strong>Restart the server to apply</strong>{" "}
            {restartFor.map(labelFor).join(", ")}.
          </p>
          <div className="controls-row">
            <button className="btn" disabled={disabled} onClick={restart}>
              Restart now
            </button>
            <button className="btn" onClick={() => setRestartFor([])}>
              Later
            </button>
          </div>
        </div>
      )}
      {confirmingRestart && (
        <Confirm
          confirmLabel="Restart anyway"
          onConfirm={() => void doRestart()}
          onCancel={() => setConfirmingRestart(false)}
        >
          Restart the server?{" "}
          <strong>{playersPhrase(humans)} will be disconnected.</strong>
        </Confirm>
      )}
    </div>
  );
}

export function Settings() {
  const { status, connected } = useStatus();
  const resource = useResource(() => api.settings(), [status?.state]);
  const [tab, setTab] = useState<string>("identity");
  const view = resource.data;
  const disabled = !connected;

  return (
    <section className="section settings">
      <h1>Settings</h1>
      <p className="muted intro">
        Saved here, applied to the server, and kept across restarts. They take precedence
        over <code>server.cfg</code>, which the panel never edits.
      </p>

      {resource.error && (
        <div className="controls-error" role="alert">
          {resource.error}
        </div>
      )}
      {!view && !resource.error && <p className="muted">Loading…</p>}

      {view && (
        <>
          {!view.running && (
            <p className="muted" role="status">
              The server is stopped: changes are saved and applied when it starts.
            </p>
          )}
          <div className="tabs" role="tablist" aria-label="Settings groups">
            {view.groups.map((g) => (
              <button
                key={g.id}
                role="tab"
                aria-selected={tab === g.id}
                className={`tab${tab === g.id ? " is-active" : ""}`}
                onClick={() => setTab(g.id)}
              >
                {g.label}
              </button>
            ))}
            <button
              role="tab"
              aria-selected={tab === RAW_TAB}
              className={`tab${tab === RAW_TAB ? " is-active" : ""}`}
              onClick={() => setTab(RAW_TAB)}
            >
              Raw cvars
            </button>
          </div>

          {tab === RAW_TAB ? (
            <RawCvars running={view.running} disabled={disabled} />
          ) : (
            <SettingsPanel
              key={tab}
              view={view}
              group={tab}
              disabled={disabled}
              reload={resource.reload}
            />
          )}
        </>
      )}
    </section>
  );
}
