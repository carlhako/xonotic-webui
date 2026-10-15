import { useCallback, useState } from "react";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null; // blocked or private mode: the page works without it
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // not remembered; nothing else depends on it
  }
}

/** A per-browser choice from a fixed set, kept in `localStorage` when it is available. */
export function useStoredChoice<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const stored = read(key);
    return allowed.find((a) => a === stored) ?? fallback;
  });
  const update = useCallback(
    (next: T) => {
      setValue(next);
      write(key, next);
    },
    [key],
  );
  return [value, update];
}
