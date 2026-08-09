import { describe, it, expect } from "vitest";
import { LABEL_GAP, OPEN_BARS, labelBudget, openBarSpace, pickLabels, shortLevelLabel } from "./chart-layout";

const lv = (label: string, strength: number, y: number | null) => ({ label, strength, y });

describe("openBarSpace", () => {
  it("caps a long intraday series so candles stay candles", () => {
    // 550 15m bars in a 1000px pane used to give 1.8px per candle.
    const capped = openBarSpace(1000, 550, true);
    expect(capped).toBeCloseTo(1000 / OPEN_BARS);
    expect(capped).toBeGreaterThan(5);
  });

  it("still stretches a short series across the whole pane", () => {
    // 22 daily bars: fill the width rather than huddle in one corner.
    expect(openBarSpace(1000, 22, true)).toBeCloseTo(1000 / 26);
  });

  it("shows a whole daily range, because the range pill asked for it", () => {
    // 250 bars = the 1Y pill. Answering with the last 180 would ignore the click.
    expect(openBarSpace(1000, 250, false)).toBeCloseTo(1000 / 254);
    expect(openBarSpace(1000, 250, true)).toBeCloseTo(1000 / OPEN_BARS);
  });

  it("opens a narrow pane on fewer bars rather than a haze", () => {
    // A 2x2 grid at 1440px gives 480px panes: the 3px floor bites before
    // OPEN_BARS does, so the pane opens on 160 bars and scrolls back for the
    // rest. At 360px it is 120 bars — the width the page stops tiling and
    // stacks instead, because below this the level labels stop fitting.
    expect(openBarSpace(480, 550, true)).toBe(3);
    expect(480 / openBarSpace(480, 550, true)).toBe(160);
    expect(openBarSpace(360, 550, true)).toBe(3);
    expect(360 / openBarSpace(360, 550, true)).toBe(120);
  });

  it("clamps to a readable range at both ends", () => {
    expect(openBarSpace(10, 500, true)).toBe(3);     // never a sub-pixel candle
    expect(openBarSpace(4000, 2, false)).toBe(40);   // never a slab
  });
});

describe("pickLabels", () => {
  it("gives the space to the stronger of two levels that would collide", () => {
    const out = pickLabels([lv("weak", 20, 100), lv("strong", 80, 108)]);
    expect(out.has("strong")).toBe(true);
    expect(out.has("weak")).toBe(false);
  });

  it("labels both once they are a label apart", () => {
    const out = pickLabels([lv("a", 20, 100), lv("b", 80, 100 + LABEL_GAP)]);
    expect(out).toEqual(new Set(["a", "b"]));
  });

  it("keeps names clear of reserved bands", () => {
    // The OHLC legend at y=16 and SPOT at y=200 are already spoken for.
    const out = pickLabels([lv("top", 90, 20), lv("atSpot", 90, 205), lv("clear", 10, 300)], [16, 200]);
    expect(out.has("top")).toBe(false);
    expect(out.has("atSpot")).toBe(false);
    expect(out.has("clear")).toBe(true);
  });

  it("labels everything when the chart cannot be measured yet", () => {
    // Every name beats no name — a null y is 'unknown', not 'off screen'.
    const out = pickLabels([lv("a", 1, null), lv("b", 2, null)]);
    expect(out).toEqual(new Set(["a", "b"]));
  });

  it("treats a missing strength as the weakest, not as an error", () => {
    const out = pickLabels([{ label: "none", y: 100 }, lv("some", 1, 105)]);
    expect(out).toEqual(new Set(["some"]));
  });

  it("does not reorder or mutate its input", () => {
    const input = [lv("a", 1, 100), lv("b", 9, 108)];
    const copy = JSON.parse(JSON.stringify(input));
    pickLabels(input);
    expect(input).toEqual(copy);
  });
});

describe("labelBudget", () => {
  it("never lets a name cross more than 45% of the pane", () => {
    // The complaint that motivated this: a compound name written at a full-width
    // pane's budget ran across the candles in a 480px split pane.
    for (const w of [360, 480, 704, 1400]) {
      expect(labelBudget(w) * 5.6).toBeLessThanOrEqual(w * 0.45);
    }
  });

  it("stays legible in a pane too narrow for anything", () => {
    expect(labelBudget(0)).toBe(6);
    expect(labelBudget(40)).toBe(6);
  });

  it("grows with the pane", () => {
    expect(labelBudget(1400)).toBeGreaterThan(labelBudget(480));
  });
});

describe("shortLevelLabel", () => {
  const LONG = "Prev Day Low + Prev Week High + Pivot S1";

  it("leaves a name alone when it fits", () => {
    expect(shortLevelLabel("Pivot R1", 40)).toBe("Pivot R1");
    expect(shortLevelLabel(LONG, 60)).toBe(LONG);
  });

  it("collapses a confluence to its lead member plus a count", () => {
    // The ladder under the chart names every member, so the count is a pointer,
    // not a loss.
    expect(shortLevelLabel(LONG, 20)).toBe("Prev Day Low +2");
    expect(shortLevelLabel("Camarilla H3 + Prev Day High", 20)).toBe("Camarilla H3 +1");
  });

  it("keeps the BROKEN marker when there is room for it", () => {
    expect(shortLevelLabel("Pivot S2", 40, true)).toBe("Pivot S2 · BROKEN");
    expect(shortLevelLabel(LONG, 26, true)).toBe("Prev Day Low +2 · BROKEN");
  });

  it("drops BROKEN before it truncates the name", () => {
    // The line is already drawn dashed, so the word is the first thing worth
    // losing — a half-spelled instrument name is worse than a redundant one.
    expect(shortLevelLabel(LONG, 16, true)).toBe("Prev Day Low +2");
  });

  it("ellipsises as the floor, and respects the budget exactly", () => {
    const out = shortLevelLabel("Exp-Move Upper", 10);
    expect(out).toBe("Exp-Move…");
    expect(out.length).toBeLessThanOrEqual(10);
  });

  it("never exceeds its budget, for any level name this app produces", () => {
    const names = [
      "Call OI Wall", "Put OI Wall", "Max Pain", "Exp-Move Upper", "Exp-Move Lower",
      "CPR Top", "CPR Bottom", "Camarilla H3", "Camarilla L3", "Pivot R2", "Pivot S2",
      LONG, "Pivot P + CPR Top + Prev Day Close", "Camarilla L3 + Max Pain + CPR Bottom",
    ];
    for (const n of names) {
      for (const w of [360, 480, 704, 1400]) {
        for (const broken of [false, true]) {
          const b = labelBudget(w);
          expect(shortLevelLabel(n, b, broken).length).toBeLessThanOrEqual(b);
        }
      }
    }
  });
});
