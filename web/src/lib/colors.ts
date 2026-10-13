// Xonotic colour codes (design D10). The grammar matches the engine's text renderer
// (darkplaces gl_draw.c) and the backend's strip_colors (src/xonotic_webui/colors.py):
//
//   ^0 .. ^9   a palette colour
//   ^xRGB      three hex digits (case-insensitive), each a 4-bit channel
//   ^^         one literal caret
//
// Anything else, including `^x` followed by fewer than three hex digits and a trailing
// lone `^`, is an ordinary character.

export interface ColorSegment {
  text: string;
  /** A CSS colour, or null for the default text colour. */
  color: string | null;
}

// The engine's table: black red green yellow blue cyan magenta white, then ^8 half
// transparent white and ^9 half-brightness grey.
const PALETTE = [
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
];

const HEX3 = /^[0-9a-fA-F]{3}$/;

function rgbFromHex3(hex: string): string {
  const [r, g, b] = [...hex].map((c) => parseInt(c, 16) * 17);
  return `rgb(${r}, ${g}, ${b})`;
}

/** Split `input` into runs of text sharing one colour. */
export function parseColors(input: string): ColorSegment[] {
  const segments: ColorSegment[] = [];
  let color: string | null = null;
  let buffer = "";

  const flush = () => {
    if (buffer !== "") {
      segments.push({ text: buffer, color });
      buffer = "";
    }
  };

  let i = 0;
  while (i < input.length) {
    const ch = input[i];
    if (ch === "^" && i + 1 < input.length) {
      const next = input[i + 1];
      if (next >= "0" && next <= "9") {
        flush();
        color = PALETTE[Number(next)];
        i += 2;
        continue;
      }
      if (next === "x" && HEX3.test(input.slice(i + 2, i + 5))) {
        flush();
        color = rgbFromHex3(input.slice(i + 2, i + 5));
        i += 5;
        continue;
      }
      if (next === "^") {
        buffer += "^";
        i += 2;
        continue;
      }
    }
    buffer += ch;
    i += 1;
  }
  flush();
  return segments;
}

/** The text with every colour code removed. */
export function stripColors(input: string): string {
  return parseColors(input)
    .map((s) => s.text)
    .join("");
}
