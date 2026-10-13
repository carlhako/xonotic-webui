export function playersPhrase(n: number): string {
  return `${n} ${n === 1 ? "player" : "players"}`;
}

/** A copy of ``obj`` without ``key``. */
export function omit<T>(obj: Record<string, T>, key: string): Record<string, T> {
  const copy = { ...obj };
  delete copy[key];
  return copy;
}
