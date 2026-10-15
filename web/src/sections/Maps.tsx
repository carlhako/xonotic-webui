import { useMemo, useState } from "react";
import { ApiCallError, api } from "../api/client";
import type { GametypesView, MapInfo, RotationView } from "../api/client";
import { useStatus } from "../api/StatusContext";
import { useFavourites } from "../api/useFavourites";
import { useResource } from "../api/useResource";
import { ActionStatus } from "../components/MatchActions";
import { Confirm } from "../components/Confirm";
import { FavouriteStar } from "../components/FavouriteStar";
import { DeletePackageDialog, PackageUpload } from "../components/MapPackages";
import { MapTable } from "../components/MapTable";
import { applyMessage } from "../lib/apply";
import { formatSize } from "../lib/size";
import { useStoredChoice } from "../lib/storage";
import { playersPhrase } from "../lib/text";

function errorText(e: unknown): string {
  return e instanceof ApiCallError ? e.message : String(e);
}

function gametypeName(view: GametypesView | null, id: string | null): string {
  if (!id) return "unknown";
  return view?.gametypes.find((g) => g.id === id)?.name ?? id;
}

function MapCard({
  map,
  names,
  canGo,
  disabled,
  inRotation,
  starred,
  onGo,
  onAdd,
  onToggleFavourite,
}: {
  map: MapInfo;
  names: Map<string, string>;
  canGo: boolean;
  disabled: boolean;
  inRotation: boolean;
  starred: boolean;
  onGo: () => void;
  onAdd: () => void;
  onToggleFavourite: () => void;
}) {
  return (
    <li className="map-card">
      {map.preview ? (
        <img
          className="map-preview"
          src={`/api/maps/${encodeURIComponent(map.name)}/preview`}
          alt=""
          loading="lazy"
        />
      ) : (
        <div className="map-preview map-preview-none" aria-hidden="true" />
      )}
      <div className="map-body">
        <div className="map-title-row">
          <div className="map-title">{map.title}</div>
          <FavouriteStar
            name={map.name}
            starred={starred}
            disabled={disabled}
            onToggle={onToggleFavourite}
          />
        </div>
        <div className="muted map-name">{map.name}</div>
        <div className="muted map-package">
          {map.package} · {formatSize(map.package_size)}
        </div>
        {map.pending_restart && (
          <div className="badge badge-warn map-pending">
            restart the server to use this map
          </div>
        )}
        <div className="map-badges">
          {map.gametypes.length === 0 ? (
            <span
              className="badge badge-warn"
              title="the map has no map information file"
            >
              unknown gametypes
            </span>
          ) : (
            map.gametypes.map((g) => (
              <span key={g} className="badge">
                {names.get(g) ?? g}
              </span>
            ))
          )}
        </div>
        <div className="controls-row">
          <button className="btn" disabled={disabled || !canGo} onClick={onGo}>
            Go to this map
          </button>
          <button className="btn" disabled={disabled || inRotation} onClick={onAdd}>
            {inRotation ? "In rotation" : "Add to rotation"}
          </button>
        </div>
      </div>
    </li>
  );
}

function GametypePanel({
  view,
  maps,
  running,
  humans,
  disabled,
  reload,
  go,
}: {
  view: GametypesView;
  maps: MapInfo[];
  running: boolean;
  humans: number;
  disabled: boolean;
  reload: () => void;
  go: (map: string) => Promise<void>;
}) {
  const offered = view.gametypes.filter((g) => g.offered);
  const current = view.selected ?? view.effective ?? offered[0]?.id ?? "";
  const [choice, setChoice] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [target, setTarget] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const shown = choice ?? current;
  const playable = maps.filter((m) => m.gametypes.includes(shown));
  const changed = shown !== (view.selected ?? view.effective);

  async function atNextMap() {
    setError(null);
    try {
      const result = await api.selectGametype(shown);
      setMessage(
        `${gametypeName(view, shown)}: ${applyMessage(result.apply, running).toLowerCase()}`,
      );
      setChoice(null);
      reload();
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function switchNow() {
    setConfirming(false);
    setError(null);
    try {
      await api.selectGametype(shown);
      await go(target);
      setMessage(`Switching to ${gametypeName(view, shown)} on ${target}`);
      setSwitching(false);
      setChoice(null);
      reload();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className="panel">
      <h2>Gametype</h2>
      <div className="controls-row">
        <select
          aria-label="Gametype"
          value={shown}
          disabled={disabled}
          onChange={(e) => {
            setChoice(e.target.value);
            setTarget("");
          }}
        >
          {offered.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} ({g.map_count} {g.map_count === 1 ? "map" : "maps"})
            </option>
          ))}
        </select>
        <button
          className="btn btn-save"
          disabled={disabled || !changed}
          onClick={() => void atNextMap()}
        >
          Use at next map
        </button>
        <button
          className="btn"
          disabled={disabled || !running || offered.length === 0}
          onClick={() => setSwitching((s) => !s)}
        >
          Switch now…
        </button>
      </div>
      <p className="muted field-help">
        Only gametypes that at least one installed map supports are offered. The current
        match is played as <strong>{gametypeName(view, view.running)}</strong>
        {view.running !== view.effective && (
          <>
            ; the next map as <strong>{gametypeName(view, view.effective)}</strong>
          </>
        )}
        .
      </p>

      {switching && (
        <div className="switch-now">
          <label htmlFor="switch-map">Map to switch to</label>
          <select
            id="switch-map"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">Choose a map…</option>
            {playable.map((m) => (
              <option key={m.name} value={m.name}>
                {m.title}
              </option>
            ))}
          </select>
          <button
            className="btn btn-danger"
            disabled={disabled || target === ""}
            onClick={() => (humans > 0 ? setConfirming(true) : void switchNow())}
          >
            Switch and go
          </button>
        </div>
      )}
      {confirming && (
        <Confirm
          confirmLabel="Switch anyway"
          onConfirm={() => void switchNow()}
          onCancel={() => setConfirming(false)}
        >
          Switch to {gametypeName(view, shown)} on {target}?{" "}
          <strong>
            {playersPhrase(humans)} {humans === 1 ? "is" : "are"} in the match.
          </strong>
        </Confirm>
      )}

      {message && (
        <p className="field-feedback" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function RotationPanel({
  rotation,
  names,
  gametypes,
  disabled,
  running,
  pendingAdd,
  reload,
}: {
  rotation: RotationView;
  names: Map<string, string>;
  gametypes: GametypesView | null;
  disabled: boolean;
  running: boolean;
  pendingAdd: string[];
  reload: () => void;
}) {
  const [draft, setDraft] = useState<string[] | null>(null);
  const [shuffle, setShuffle] = useState<boolean | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Maps added from the grid join the list being edited.
  const list = useMemo(() => {
    const base = draft ?? rotation.maps.map((m) => m.name);
    const extra = pendingAdd.filter((n) => !base.includes(n));
    return [...base, ...extra];
  }, [draft, rotation.maps, pendingAdd]);

  const shuffleShown = shuffle ?? rotation.shuffle ?? true;
  const info = new Map(rotation.maps.map((m) => [m.name, m]));
  const dirty =
    draft !== null ||
    pendingAdd.length > 0 ||
    (shuffle !== null && shuffle !== (rotation.shuffle ?? true));

  function move(i: number, by: number) {
    const next = [...list];
    const j = i + by;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setDraft(next);
  }

  async function save() {
    setError(null);
    try {
      const explicit = shuffle !== null || rotation.shuffle !== null;
      const result = await api.saveRotation(list, explicit ? shuffleShown : null);
      setMessage(`Rotation saved: ${applyMessage(result.apply, running).toLowerCase()}`);
      setDraft(null);
      setShuffle(null);
      reload();
    } catch (e) {
      setError(errorText(e));
    }
  }

  const gametype = gametypeName(gametypes, rotation.gametype);

  return (
    <div className="panel">
      <h2>Rotation</h2>
      {list.length === 0 ? (
        <p className="muted">
          No rotation: the server plays every map that supports the gametype.
        </p>
      ) : (
        <ol className="rotation-list">
          {list.map((name, i) => {
            const item = info.get(name);
            const known = item !== undefined;
            const supported = item?.supported;
            return (
              <li key={name} className="rotation-item">
                <span className="rotation-name">{item?.title ?? name}</span>
                {known && !item.installed && (
                  <span className="badge badge-warn">not installed</span>
                )}
                {supported === false && (
                  <span className="badge badge-warn">does not support {gametype}</span>
                )}
                <span className="override-actions">
                  <button
                    className="link"
                    aria-label={`Move ${name} up`}
                    disabled={disabled || i === 0}
                    onClick={() => move(i, -1)}
                  >
                    up
                  </button>
                  <button
                    className="link"
                    aria-label={`Move ${name} down`}
                    disabled={disabled || i === list.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    down
                  </button>
                  <button
                    className="link"
                    aria-label={`Remove ${name} from the rotation`}
                    disabled={disabled}
                    onClick={() => setDraft(list.filter((n) => n !== name))}
                  >
                    remove
                  </button>
                </span>
              </li>
            );
          })}
        </ol>
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={shuffleShown}
          disabled={disabled}
          onChange={(e) => setShuffle(e.target.checked)}
        />
        Shuffle
      </label>
      <p className="muted field-help">
        {names.size > 0 &&
          "Maps that cannot be played in the selected gametype are left out of the rotation."}
      </p>
      <div className="controls-row">
        <button
          className="btn btn-save"
          disabled={disabled || !dirty}
          onClick={() => void save()}
        >
          Save rotation
        </button>
        <button
          className="btn"
          disabled={disabled || list.length === 0}
          onClick={() => setDraft([])}
        >
          Clear (all maps)
        </button>
      </div>
      {message && (
        <p className="field-feedback" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function Maps() {
  const { status, connected } = useStatus();
  // A restart changes which packages the game has loaded (`pending_restart`).
  const maps = useResource(() => api.maps(), [status?.state]);
  const gametypes = useResource(() => api.gametypes(), [status?.gametype, status?.state]);
  const rotation = useResource(() => api.rotation(), [status?.state]);

  const favourites = useFavourites();
  const [view, setView] = useStoredChoice(
    "xonotic-webui.maps.view",
    ["cards", "files"] as const,
    "cards",
  );
  const [favouritesOnly, setFavouritesOnly] = useStoredChoice(
    "xonotic-webui.maps.favourites-only",
    ["off", "on"] as const,
    "off",
  );
  const [deleting, setDeleting] = useState<{
    file: string;
    trigger: HTMLElement | null;
  } | null>(null);
  const [filter, setFilter] = useState("");
  const [pendingAdd, setPendingAdd] = useState<string[]>([]);
  const [going, setGoing] = useState<MapInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  const disabled = !connected;
  const running = status?.state === "running";
  const humans = status?.human_count ?? 0;
  const busy = status?.action?.state === "pending";
  const names = useMemo(
    () => new Map((gametypes.data?.gametypes ?? []).map((g) => [g.id, g.name])),
    [gametypes.data],
  );
  const effective = gametypes.data?.effective ?? null;

  const all = maps.data?.maps ?? [];
  const starredShown = favouritesOnly === "on";
  const shown = all
    .filter((m) => !filter || m.gametypes.includes(filter))
    .filter((m) => !starredShown || favourites.has(m.name));
  // a favourite of a map that is not installed is kept but never listed
  const anyStarred = all.some((m) => favourites.has(m.name));
  const inRotation = new Set([
    ...(rotation.data?.maps.map((m) => m.name) ?? []),
    ...pendingAdd,
  ]);

  async function go(name: string) {
    setError(null);
    await api.gotoMap(name);
  }

  async function goWithErrors(name: string) {
    setGoing(null);
    try {
      await go(name);
    } catch (e) {
      setError(errorText(e));
    }
  }

  // The same rule for both views: only a running server, an idle action slot, a map
  // the game has loaded, and a map the gametype supports.
  const canGo = (m: MapInfo) =>
    running &&
    !busy &&
    !m.pending_restart &&
    (effective === null ? m.gametypes.length > 0 : m.gametypes.includes(effective));
  const onGo = (m: MapInfo) => (humans > 0 ? setGoing(m) : void goWithErrors(m.name));
  const onAdd = (m: MapInfo) => setPendingAdd((p) => [...p, m.name]);

  const loadError = maps.error ?? gametypes.error ?? rotation.error;
  const deletingMaps = deleting
    ? all.filter((m) => m.package === deleting.file && m.source === "user")
    : [];

  return (
    <section className="section maps">
      <h1>Maps</h1>

      {loadError && (
        <div className="controls-error" role="alert">
          {loadError}
        </div>
      )}
      <ActionStatus action={status?.action} />
      {(error ?? favourites.error) && (
        <div className="controls-error" role="alert">
          {error ?? favourites.error}
        </div>
      )}
      {going && (
        <Confirm
          confirmLabel="Go anyway"
          onConfirm={() => void goWithErrors(going.name)}
          onCancel={() => setGoing(null)}
        >
          Go to {going.title}? The match ends now.{" "}
          <strong>
            {playersPhrase(humans)} {humans === 1 ? "is" : "are"} in the match.
          </strong>
        </Confirm>
      )}

      {gametypes.data && (
        <GametypePanel
          view={gametypes.data}
          maps={all}
          running={running}
          humans={humans}
          disabled={disabled || busy}
          reload={gametypes.reload}
          go={go}
        />
      )}

      {rotation.data && (
        <RotationPanel
          rotation={rotation.data}
          names={names}
          gametypes={gametypes.data}
          disabled={disabled}
          running={running}
          pendingAdd={pendingAdd}
          reload={() => {
            setPendingAdd([]);
            rotation.reload();
          }}
        />
      )}

      <div className="panel">
        <div className="map-filter">
          <h2>Installed maps</h2>
          <div className="map-toolbar">
            <div className="view-switch" role="group" aria-label="View">
              <button
                className="btn"
                aria-pressed={view === "cards"}
                onClick={() => setView("cards")}
              >
                Cards
              </button>
              <button
                className="btn"
                aria-pressed={view === "files"}
                onClick={() => setView("files")}
              >
                Files
              </button>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={starredShown}
                onChange={(e) => setFavouritesOnly(e.target.checked ? "on" : "off")}
              />
              Favourites only
            </label>
            <select
              aria-label="Show maps for"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="">All gametypes</option>
              {(gametypes.data?.gametypes ?? [])
                .filter((g) => g.offered)
                .map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
            </select>
          </div>
        </div>
        {view === "files" && (
          <PackageUpload disabled={disabled} onInstalled={maps.reload} />
        )}
        {!maps.data && !maps.error && <p className="muted">Loading…</p>}
        {maps.data && shown.length === 0 && (
          <p className="muted">
            {starredShown && !anyStarred
              ? "No favourites yet. Star a map with the ☆ button to add it here."
              : "No maps match."}
          </p>
        )}
        {view === "cards" ? (
          <ul className="map-grid">
            {shown.map((m) => (
              <MapCard
                key={m.name}
                map={m}
                names={names}
                canGo={canGo(m)}
                disabled={disabled}
                inRotation={inRotation.has(m.name)}
                starred={favourites.has(m.name)}
                onGo={() => onGo(m)}
                onAdd={() => onAdd(m)}
                onToggleFavourite={() => void favourites.toggle(m.name)}
              />
            ))}
          </ul>
        ) : (
          shown.length > 0 && (
            <MapTable
              maps={shown}
              actions={{
                canGo,
                inRotation: (name) => inRotation.has(name),
                isFavourite: favourites.has,
                disabled,
                onGo,
                onAdd,
                onToggleFavourite: (name) => void favourites.toggle(name),
                onDelete: (m, trigger) => setDeleting({ file: m.package, trigger }),
              }}
            />
          )
        )}
      </div>

      {deleting && (
        <DeletePackageDialog
          file={deleting.file}
          maps={deletingMaps}
          inRotation={(name) => inRotation.has(name)}
          disabled={disabled}
          returnFocusTo={deleting.trigger}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            maps.reload();
            rotation.reload();
          }}
        />
      )}
    </section>
  );
}
