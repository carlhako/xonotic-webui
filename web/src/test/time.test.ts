import { afterEach, describe, expect, it } from "vitest";
import { formatClock, formatTimestamp } from "../lib/time";

const ISO = "2026-03-01T23:30:00+00:00";
const original = process.env.TZ;

afterEach(() => {
  if (original === undefined) delete process.env.TZ;
  else process.env.TZ = original;
});

describe("timestamps (8.8)", () => {
  it("formats in the browser's local timezone, not a server one", () => {
    // 23:30 UTC is 15:30 on 1 March in Los Angeles (PST) and 08:30 on 2 March in Tokyo.
    // Locale-agnostic: the field order and 12/24 hour style depend on the browser.
    process.env.TZ = "America/Los_Angeles";
    const la = formatTimestamp(ISO);
    process.env.TZ = "Asia/Tokyo";
    const tokyo = formatTimestamp(ISO);

    expect(la).toMatch(/\b1\b/);
    expect(la).toMatch(/0?3:30:00/);
    expect(la).not.toMatch(/\b2\b/);
    expect(tokyo).toMatch(/\b2\b/);
    expect(tokyo).toMatch(/0?8:30:00/);
    expect(la).not.toEqual(tokyo);
  });

  it("names the timezone so the reader knows which clock it is", () => {
    process.env.TZ = "America/Los_Angeles";
    expect(formatTimestamp(ISO)).toMatch(/PST|GMT-8/);
  });

  it("returns an unparseable value unchanged", () => {
    expect(formatTimestamp("not a date")).toBe("not a date");
  });
});

describe("formatClock", () => {
  it("shows minutes and zero-padded seconds", () => {
    expect(formatClock(400)).toBe("6:40");
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(9)).toBe("0:09");
    expect(formatClock(0)).toBe("0:00");
  });

  it("adds hours from an hour up", () => {
    expect(formatClock(3600)).toBe("1:00:00");
    expect(formatClock(3725)).toBe("1:02:05");
  });

  it("never goes negative or fractional", () => {
    expect(formatClock(-5)).toBe("0:00");
    expect(formatClock(59.6)).toBe("1:00");
  });
});
