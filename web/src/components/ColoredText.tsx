import { parseColors } from "../lib/colors";

/** Text with Xonotic colour codes rendered as colour; the code characters are never
 *  shown. Pair with the `.xon-text` class, whose dark ground keeps every colour legible. */
export function ColoredText({ text }: { text: string }) {
  return (
    <>
      {parseColors(text).map((seg, i) =>
        seg.color ? (
          <span key={i} style={{ color: seg.color }}>
            {seg.text}
          </span>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </>
  );
}
