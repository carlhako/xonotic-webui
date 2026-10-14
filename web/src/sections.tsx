import type { ReactElement } from "react";
import { Dashboard } from "./sections/Dashboard";
import { Console } from "./sections/Console";
import { Maps } from "./sections/Maps";
import { Settings } from "./sections/Settings";
import { Panel } from "./sections/Panel";

export interface Section {
  path: string;
  label: string;
  element: ReactElement;
  /** `false` routes the section without listing it in the navigation. */
  nav?: boolean;
}

// The shell renders navigation and routes from this list: a new section is one entry
// here and no change to App.tsx (design D11).
export const sections: Section[] = [
  { path: "/", label: "Dashboard", element: <Dashboard /> },
  { path: "/maps", label: "Maps", element: <Maps /> },
  { path: "/settings", label: "Settings", element: <Settings /> },
  { path: "/console", label: "Console", element: <Console /> },
  // Reached from the header version badge, so it is routed but not listed in the navigation.
  { path: "/panel", label: "Panel", element: <Panel />, nav: false },
];
