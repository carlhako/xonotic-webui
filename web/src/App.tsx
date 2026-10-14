import { Link, NavLink, Route, Routes } from "react-router-dom";
import { sections } from "./sections";
import { ConnectionBanner } from "./components/ConnectionBanner";
import { StatusProvider, useStatus } from "./api/StatusContext";
import {
  PanelVersionProvider,
  upgradeInFlight,
  usePanelVersion,
} from "./api/usePanelVersion";

/** The running panel version in brackets beside the brand: green when no newer release is
 *  known, orange with "update available" when there is one, neutral when availability has
 *  never been established. In every state it opens the panel page (web-ui-shell). */
function VersionBadge() {
  const { info } = usePanelVersion();
  if (!info) return null;
  if (info.update_available) {
    return (
      <Link
        to="/panel"
        className="version-badge is-update"
        title={`xonotic-webui ${info.latest} is available`}
      >
        [{info.current} update available]
      </Link>
    );
  }
  // A failed check keeps the last successful result, which still answers whether this
  // install is current; only a panel that has never checked claims nothing.
  const known = info.latest !== null;
  return (
    <Link
      to="/panel"
      className={`version-badge${known ? " is-current" : ""}`}
      title={known ? "xonotic-webui is up to date" : "update availability unknown"}
    >
      [{info.current}]
    </Link>
  );
}

/** While a panel upgrade is in flight the page loses its connection and then reloads
 *  itself onto the new version; the banner says so on every page. */
function UpgradeBanner() {
  const { info } = usePanelVersion();
  if (!info || !upgradeInFlight(info) || !info.upgrade) return null;
  return (
    <div className="upgrade-banner" role="status">
      Upgrading xonotic-webui to {info.upgrade.to}. The panel and the game server restart
      while it installs, and this page reloads by itself when it is back.
    </div>
  );
}

function Shell() {
  const { connected } = useStatus();
  return (
    <div className="app">
      <header className="app-header">
        <span className="brand-group">
          <span className="brand">xonotic-webui</span>
          <VersionBadge />
        </span>
        <nav className="app-nav" aria-label="Sections">
          {sections
            .filter((s) => s.nav !== false)
            .map((s) => (
              <NavLink key={s.path} to={s.path} end={s.path === "/"}>
                {s.label}
              </NavLink>
            ))}
        </nav>
      </header>
      <UpgradeBanner />
      <ConnectionBanner connected={connected} />
      <main className="app-main">
        <Routes>
          {sections.map((s) => (
            <Route key={s.path} path={s.path} element={s.element} />
          ))}
        </Routes>
      </main>
    </div>
  );
}

export function App() {
  return (
    <StatusProvider>
      <PanelVersionProvider>
        <Shell />
      </PanelVersionProvider>
    </StatusProvider>
  );
}
