import { NavLink, Route, Routes } from "react-router-dom";
import { sections } from "./sections";
import { ConnectionBanner } from "./components/ConnectionBanner";
import { StatusProvider, useStatus } from "./api/StatusContext";

function Shell() {
  const { connected } = useStatus();
  return (
    <div className="app">
      <header className="app-header">
        <span className="brand">xonotic-webui</span>
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
      <Shell />
    </StatusProvider>
  );
}
