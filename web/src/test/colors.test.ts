import { describe, expect, it } from "vitest";
import { parseColors, stripColors } from "../lib/colors";

// Real names captured from a live 0.8.6 server (tests/fixtures/xonotic/ in the repo) and
// the edge cases from design D10. The same table is asserted by the backend's tests.
const STRIP_CASES: [string, string][] = [
  ["plain", "plain"],
  ["^1Red^7 Name", "Red Name"],
  ["^xf80Orange^7", "Orange"],
  ["^1Red^xf80Orange^7 Pl:ay^^er", "RedOrange Pl:ay^er"],
  ["^xf0fMagic^7Name", "MagicName"],
  ["V6 ^4Blue^7", "V6 Blue"],
  ["a^^b", "a^b"],
  ["^^1not-a-colour", "^1not-a-colour"],
  ["^x12 short", "^x12 short"],
  ["^xGGG", "^xGGG"],
  ["^x1234", "4"],
  ["trailing^", "trailing^"],
  ["^", "^"],
  ["", ""],
  ["[BOT]Resurrection", "[BOT]Resurrection"],
];

describe("colour codes (8.7)", () => {
  it.each(STRIP_CASES)("strips %j to %j", (raw, plain) => {
    expect(stripColors(raw)).toBe(plain);
  });

  it("never leaves a code character in rendered text", () => {
    const text = "^1Red^xf80Orange^7 Pl:ay^^er";
    const joined = parseColors(text)
      .map((s) => s.text)
      .join("");
    expect(joined).not.toMatch(/\^[0-9x]/);
  });

  it("colours runs: palette, then ^xRGB, then back to white", () => {
    expect(parseColors("^1Red^xf80Orange^7 Pl:ay^^er")).toEqual([
      { text: "Red", color: "#ff0000" },
      { text: "Orange", color: "rgb(255, 136, 0)" },
      { text: " Pl:ay^er", color: "#ffffff" },
    ]);
  });

  it("uses the engine's palette for every digit", () => {
    const colours = [..."0123456789"].map((d) => parseColors(`^${d}x`)[0].color);
    expect(colours).toEqual([
      "#000000",
      "#ff0000",
      "#00ff00",
      "#ffff00",
      "#0000ff",
      "#00ffff",
      "#ff00ff",
      "#ffffff",
      "rgba(255, 255, 255, 0.5)",
      "#808080",
    ]);
  });

  it("treats hex digits case-insensitively and scales each channel by 17", () => {
    expect(parseColors("^xFfF.")[0].color).toBe("rgb(255, 255, 255)");
    expect(parseColors("^x048.")[0].color).toBe("rgb(0, 68, 136)");
  });

  it("shows a literal caret for an escaped caret and keeps text after it uncoloured", () => {
    expect(parseColors("^^1")).toEqual([{ text: "^1", color: null }]);
  });

  it("leaves text before any code in the default colour", () => {
    expect(parseColors("hi ^1there")).toEqual([
      { text: "hi ", color: null },
      { text: "there", color: "#ff0000" },
    ]);
  });
});
