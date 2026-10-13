import type { ReactElement } from "react";
import { Dashboard } from "./sections/Dashboard";
import { Console } from "./sections/Console";

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
  { path: "/console", label: "Console", element: <Console /> },
];
