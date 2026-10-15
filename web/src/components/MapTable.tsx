import type { MapInfo } from "../api/client";
import { formatSize } from "../lib/size";
import { FavouriteStar } from "./FavouriteStar";

export interface MapRowActions {
  canGo: (map: MapInfo) => boolean;
  inRotation: (name: string) => boolean;
  isFavourite: (name: string) => boolean;
  /** Everything is off while the panel is disconnected. */
  disabled: boolean;
  onGo: (map: MapInfo) => void;
  onAdd: (map: MapInfo) => void;
  onToggleFavourite: (name: string) => void;
  onDelete: (map: MapInfo, trigger: HTMLElement) => void;
}

/** One row per installed map: no preview image, the package it comes from and its size.
 *  It shares `canGo`, `onGo` and `onAdd` with the card view, so the two cannot disagree. */
export function MapTable({ maps, actions }: { maps: MapInfo[]; actions: MapRowActions }) {
  return (
    <div className="table-scroll">
      <table className="data-table map-table" aria-label="Installed map files">
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">Favourite</span>
            </th>
            <th scope="col">Map</th>
            <th scope="col">Package</th>
            <th scope="col" className="num">
              Size
            </th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {maps.map((m) => {
            const user = m.source === "user";
            const inRotation = actions.inRotation(m.name);
            return (
              <tr key={m.name}>
                <td>
                  <FavouriteStar
                    name={m.name}
                    starred={actions.isFavourite(m.name)}
                    disabled={actions.disabled}
                    onToggle={() => actions.onToggleFavourite(m.name)}
                  />
                </td>
                <td>
                  <span className="map-title">{m.title}</span>
                  {m.title !== m.name && (
                    <span className="muted map-name"> {m.name}</span>
                  )}
                  {m.pending_restart && (
                    <span className="badge badge-warn">
                      restart the server to use this map
                    </span>
                  )}
                </td>
                <td>
                  <span className="mono">{m.package}</span>
                  <span className="badge badge-source">{user ? "user" : "game"}</span>
                </td>
                <td className="num">{formatSize(m.package_size)}</td>
                <td>
                  <span className="row-actions">
                    <button
                      className="btn"
                      disabled={actions.disabled || !actions.canGo(m)}
                      onClick={() => actions.onGo(m)}
                    >
                      Go to this map
                    </button>
                    <button
                      className="btn"
                      disabled={actions.disabled || inRotation}
                      onClick={() => actions.onAdd(m)}
                    >
                      {inRotation ? "In rotation" : "Add to rotation"}
                    </button>
                    {user &&
                      (actions.disabled ? (
                        <button className="btn" disabled>
                          Download
                        </button>
                      ) : (
                        <a
                          className="btn"
                          href={`/api/packages/${encodeURIComponent(m.package)}`}
                          download={m.package}
                        >
                          Download
                        </a>
                      ))}
                    {user && (
                      <button
                        className="btn btn-danger"
                        disabled={actions.disabled}
                        onClick={(e) => actions.onDelete(m, e.currentTarget)}
                      >
                        Delete
                      </button>
                    )}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
