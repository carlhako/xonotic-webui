import { useRef, useState } from "react";
import { ApiCallError, api } from "../api/client";
import type { MapInfo, PackageInstalled } from "../api/client";
import { formatSize } from "../lib/size";
import { Dialog } from "./Dialog";

function errorText(e: unknown): string {
  return e instanceof ApiCallError ? e.message : String(e);
}

function duplicateNote(d: PackageInstalled["duplicates"][number]): string {
  const where = d.source === "game" ? `${d.package} (part of the game)` : d.package;
  return (
    `${d.map} has the same name as a map in ${where}; ` +
    (d.used ? "the uploaded one is used." : "the one already installed is still used.")
  );
}

/** The file picker for a new map package. Only `.pk3` is offered; the panel checks the
 *  file itself and its refusal is shown as it is worded. */
export function PackageUpload({
  disabled,
  onInstalled,
}: {
  disabled: boolean;
  onInstalled: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PackageInstalled | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.uploadPackage(file));
      onInstalled();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
      // the same file can be chosen again
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="package-upload">
      <label className={`btn${disabled || busy ? " btn-disabled" : ""}`}>
        {busy ? "Uploading…" : "Upload map package"}
        <input
          ref={input}
          type="file"
          accept=".pk3"
          className="visually-hidden"
          aria-label="Map package file"
          disabled={disabled || busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
          }}
        />
      </label>
      <span className="muted field-help">Only .pk3 files, up to 256 MB.</span>
      {result && (
        <div className="field-feedback" role="status">
          <p>
            Installed {result.name} ({formatSize(result.size)}) with{" "}
            {result.maps.length === 1 ? "the map" : "the maps"} {result.maps.join(", ")}.
          </p>
          {result.duplicates.map((d) => (
            <p key={d.map} className="upload-warning">
              {duplicateNote(d)}
            </p>
          ))}
          {result.restart_required && (
            <p className="upload-warning">
              The server is running and has not loaded this package: restart it to use the
              map{result.maps.length === 1 ? "" : "s"}.
            </p>
          )}
        </div>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** The "are you sure" popup before a package is removed: the file, every map in it and
 *  which of those are in the rotation. Nothing is deleted until it is confirmed. */
export function DeletePackageDialog({
  file,
  maps,
  inRotation,
  disabled,
  returnFocusTo,
  onClose,
  onDeleted,
}: {
  file: string;
  /** The panel is disconnected: nothing can be confirmed. */
  disabled: boolean;
  maps: MapInfo[];
  inRotation: (name: string) => boolean;
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const size = maps[0]?.package_size;
  const used = maps.filter((m) => inRotation(m.name));

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deletePackage(file);
      onDeleted();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Dialog title={`Delete ${file}?`} onClose={onClose} returnFocusTo={returnFocusTo}>
      <p>
        <strong>{file}</strong>
        {size !== undefined && <> ({formatSize(size)})</>} will be removed from the
        server. It contains {maps.length === 1 ? "this map" : `these ${maps.length} maps`}
        :
      </p>
      <ul className="delete-maps">
        {maps.map((m) => (
          <li key={m.name}>
            {m.title}
            {m.title !== m.name && <span className="muted"> ({m.name})</span>}
          </li>
        ))}
      </ul>
      {used.length > 0 && (
        <p className="field-error">
          In the rotation: {used.map((m) => m.name).join(", ")}. They will show as not
          installed there until you remove them.
        </p>
      )}
      <div className="controls-row">
        <button
          className="btn btn-danger"
          disabled={busy || disabled}
          onClick={() => void remove()}
        >
          {busy ? "Deleting…" : "Delete package"}
        </button>
        <button className="btn" disabled={busy} onClick={onClose}>
          Cancel
        </button>
      </div>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
