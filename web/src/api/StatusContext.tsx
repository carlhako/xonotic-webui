import { createContext, useContext, type ReactNode } from "react";
import { useServerStatus, type ServerStatus } from "./status";

// One status subscription for the whole app: the shell's connection banner and every
// section read the same live state from here rather than each opening its own stream.
const StatusContext = createContext<ServerStatus | null>(null);

export function StatusProvider({ children }: { children: ReactNode }) {
  const value = useServerStatus();
  return <StatusContext.Provider value={value}>{children}</StatusContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useStatus(): ServerStatus {
  const ctx = useContext(StatusContext);
  if (ctx === null) throw new Error("useStatus must be used within <StatusProvider>");
  return ctx;
}
