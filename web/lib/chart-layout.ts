// Geometry decisions for the price chart, kept out of the component so they can
// be checked without a canvas (see chart-layout.test.ts).

/** How many INTRADAY bars the chart opens on, at most.
 *
 *  The opening view used to divide the pane by the whole series, so a 550-bar
 *  15m window rendered every candle 1.8px wide — a grey haze with no body, no
 *  wick and no colour worth reading. A trading chart opens on a workable window
 *  and lets you scroll back for the rest.
 *
 *  Daily bars are exempt: the 1M/3M/6M/1Y pills ARE the window the user asked
 *  for, and answering "1Y" with the last nine months would ignore the click. */
export const OPEN_BARS = 180;

/** Bar width that fills `width`, capped to OPEN_BARS candles when `cap` is set.
 *  Floors at 3px so a candle is still a candle; ceilings at 40 so a handful of
 *  bars do not become slabs. */
export function openBarSpace(width: number, count: number, cap: boolean): number {
  const target = Math.min(count + 4, cap ? OPEN_BARS : Infinity);
  return Math.min(40, Math.max(3, width / target));
}

/** Minimum vertical gap between two level names, in px — an 11px label plus air. */
export const LABEL_GAP = 18;

/** Roughly how wide one character of the 11px label font is, in px.
 *  Measured off the rendered labels rather than derived: the face is the canvas
 *  default sans at 11px and its mixed-case average lands just under 5.6. */
const CHAR_PX = 5.6;

/** How many characters a level name may use, for a pane this wide.
 *
 *  Capped at 45% of the pane so a compound name can never run across the candles
 *  it is annotating, and floored at 6 so something legible survives even in a
 *  pane narrow enough that nothing really fits. */
export function labelBudget(paneWidth: number): number {
  return Math.max(6, Math.floor((paneWidth * 0.45 - 12) / CHAR_PX));
}

/** A level's name, fitted to the room available.
 *
 *  Confluence labels are joins — "Prev Day Low + Prev Week High + Pivot S1" —
 *  which is the useful form at full width and unreadable in a 480px split pane,
 *  where it overran the canvas and was clipped mid-word. Degrades in steps, each
 *  one losing the least useful thing left:
 *
 *    1. the whole name, when it fits;
 *    2. the leading member plus a count — "Prev Day Low +2" — since the ladder
 *       below the chart names every member anyway;
 *    3. drop the BROKEN marker, because the line is already drawn dashed and the
 *       word is only the belt to that pair of braces;
 *    4. ellipsis, as the floor.
 */
export function shortLevelLabel(label: string, maxChars: number, broken = false): string {
  const MARK = " · BROKEN";
  const full = broken ? label + MARK : label;
  if (full.length <= maxChars) return full;

  const parts = label.split(" + ");
  const base = parts.length > 1 ? `${parts[0]} +${parts.length - 1}` : label;
  const marked = broken && base.length + MARK.length <= maxChars ? base + MARK : base;
  if (marked.length <= maxChars) return marked;

  return `${marked.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
}

export type Labelled = { label: string; strength?: number | null; y: number | null };

/** Which level lines get their name written on them.
 *
 *  Two levels 40 points apart on a 1,400-point pane are ~10px apart: close
 *  enough that their names overlap into an unreadable smear. That smear is what
 *  this pass moved OUT of the price axis, so recreating it in the pane would be
 *  no gain at all. Strongest wins the space; everything else keeps its line, and
 *  the Level Map below the chart names all of them regardless.
 *
 *  `reserved` holds y positions already spoken for — the OHLC legend at the top
 *  left, and SPOT, which always draws and so must claim its space before the
 *  contest rather than be written over.
 *
 *  A null `y` means the chart could not be measured yet; those are labelled
 *  rather than silently dropped, since showing every name beats showing none.
 */
export function pickLabels(levels: Labelled[], reserved: number[] = [], gap = LABEL_GAP): Set<string> {
  const taken = [...reserved];
  const out = new Set<string>();
  for (const l of [...levels].sort((a, b) => (b.strength ?? 0) - (a.strength ?? 0))) {
    if (l.y == null) { out.add(l.label); continue; }
    if (taken.some((t) => Math.abs(t - l.y!) < gap)) continue;
    taken.push(l.y);
    out.add(l.label);
  }
  return out;
}
