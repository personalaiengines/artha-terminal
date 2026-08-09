import { describe, expect, it } from "vitest";
import {
  addPane, emptyLayout, movePane, nextPaneId, parseLayout, PRESETS, PRESET_ORDER,
  removePane, setPreset, setRes, setSymbol, type IndexSymbol, type Layout, type Pane,
} from "./chart-grid";

const pane = (id: string, symbol: IndexSymbol = "NIFTY", res = "15m"): Pane =>
  ({ id, symbol, res: res as Pane["res"] });
const layout = (preset: Layout["preset"], ...panes: Pane[]): Layout => ({ preset, panes });
const symbols = (l: Layout) => l.panes.map((p) => p.symbol);
const ids = (l: Layout) => l.panes.map((p) => p.id);

describe("PRESETS", () => {
  it("holds the pane counts the preset control advertises", () => {
    expect(PRESET_ORDER.map((p) => PRESETS[p].panes)).toEqual([1, 2, 2, 3, 4, 6]);
  });

  it("spans the first cell of preset 3, which is what makes it 1-over-2", () => {
    expect(PRESETS["3"].cls).toContain("first-child]:col-span-2");
  });

  it("stacks to one column below xl in every preset (R4)", () => {
    for (const p of PRESET_ORDER) expect(PRESETS[p].cls).toContain("grid-cols-1");
  });
});

describe("nextPaneId", () => {
  it("never reuses an id after a removal — the prefs scope keys off it", () => {
    const l = removePane(layout("3", pane("p1"), pane("p2"), pane("p3")), "p2");
    expect(ids(l)).toEqual(["p1", "p3"]);
    expect(nextPaneId(l.panes)).toBe("p4");
  });

  it("starts at p1 and ignores ids it did not mint", () => {
    expect(nextPaneId([])).toBe("p1");
    expect(nextPaneId([pane("legacy"), pane("p7")])).toBe("p8");
  });
});

describe("addPane", () => {
  it("grows into the smallest preset that fits the new pane", () => {
    const one = emptyLayout();
    expect(one.panes).toHaveLength(1);
    const two = addPane(one);
    expect(two.preset).toBe("2H");
    expect(ids(two)).toEqual(["p1", "p2"]);
    expect(addPane(two).preset).toBe("3");
  });

  it("keeps a preset that still has room", () => {
    const l = addPane(layout("6", pane("p1"), pane("p2")));
    expect(l.preset).toBe("6");
    expect(l.panes).toHaveLength(3);
  });

  it("is a no-op at six, so the page can disable the control (R3)", () => {
    const full = layout("6", ...["p1", "p2", "p3", "p4", "p5", "p6"].map((id) => pane(id)));
    expect(addPane(full)).toBe(full);
  });
});

describe("removePane", () => {
  it("leaves the last pane alone — a Charts page with no chart is not a state", () => {
    const one = layout("1", pane("p1"));
    expect(removePane(one, "p1")).toBe(one);
  });

  it("ignores an id that is not on the page", () => {
    const l = layout("2H", pane("p1"), pane("p2"));
    expect(removePane(l, "p9")).toBe(l);
  });
});

describe("setSymbol / setRes", () => {
  it("touches only the named pane, and lets one index sit in two panes (R11)", () => {
    let l = layout("2H", pane("p1", "NIFTY", "15m"), pane("p2", "BANKNIFTY", "1h"));
    l = setSymbol(l, "p2", "NIFTY");
    l = setRes(l, "p2", "1D");
    expect(symbols(l)).toEqual(["NIFTY", "NIFTY"]);
    expect(l.panes.map((p) => p.res)).toEqual(["15m", "1D"]);
  });
});

describe("movePane", () => {
  it("carries the pane's id with it, so its settings move too (R10)", () => {
    const l = movePane(layout("3", pane("p1", "NIFTY"), pane("p2", "SENSEX"), pane("p3")), "p1", 1);
    expect(ids(l)).toEqual(["p2", "p1", "p3"]);
    expect(symbols(l)).toEqual(["SENSEX", "NIFTY", "NIFTY"]);
  });

  it("is a no-op at both ends", () => {
    const l = layout("2H", pane("p1"), pane("p2"));
    expect(movePane(l, "p1", -1)).toBe(l);
    expect(movePane(l, "p2", 1)).toBe(l);
    expect(movePane(l, "nope", 1)).toBe(l);
  });
});

describe("setPreset", () => {
  it("keeps panes 1-2 on 4 → 2H and reports what it would drop (R7)", () => {
    const four = layout("4", pane("p1", "NIFTY"), pane("p2", "BANKNIFTY"), pane("p3", "SENSEX"), pane("p4", "NIFTY"));
    const { layout: next, dropped } = setPreset(four, "2H");
    expect(ids(next)).toEqual(["p1", "p2"]);
    expect(symbols(next)).toEqual(["NIFTY", "BANKNIFTY"]);
    expect(ids({ preset: "4", panes: dropped })).toEqual(["p3", "p4"]);
  });

  it("pads on the way up so every preset renders the count it advertises", () => {
    const { layout: next, dropped } = setPreset(layout("1", pane("p1")), "6");
    expect(next.panes).toHaveLength(6);
    expect(ids(next)).toEqual(["p1", "p2", "p3", "p4", "p5", "p6"]);
    expect(dropped).toEqual([]);
  });
});

describe("parseLayout", () => {
  it("survives junk rather than taking the page down with it (R33)", () => {
    for (const junk of ["{{{", null, undefined, 7, "", [], { panes: "x" }, { panes: [] }]) {
      const { layout: l } = parseLayout(junk);
      expect(l.panes).toHaveLength(1);
      expect(l.panes[0]).toEqual({ id: "p1", symbol: "NIFTY", res: "15m" });
    }
  });

  it("says nothing on a first visit, where there is no saved layout to lose", () => {
    expect(parseLayout(null).dropped).toEqual([]);
    expect(parseLayout(undefined).dropped).toEqual([]);
  });

  it("reports an unreadable saved value rather than silently starting over", () => {
    expect(parseLayout("{{{").dropped).toHaveLength(1);
    expect(parseLayout(7).dropped).toHaveLength(1);
  });

  it("restores a good layout unchanged, with nothing to report", () => {
    const saved = { preset: "2H", panes: [pane("p1", "SENSEX", "1D"), pane("p2", "BANKNIFTY", "5m")] };
    expect(parseLayout(JSON.stringify(saved))).toEqual({ layout: saved, dropped: [] });
  });

  it("drops the pane whose symbol is not one of the three, keeps the rest, and names it (R31)", () => {
    const { layout: l, dropped } = parseLayout({
      preset: "2H", panes: [{ id: "p1", symbol: "RELIANCE", res: "1D" }, pane("p2", "SENSEX")],
    });
    expect(ids(l)).toEqual(["p2"]);
    expect(symbols(l)).toEqual(["SENSEX"]);
    expect(dropped).toHaveLength(1);
    expect(dropped[0]).toContain("RELIANCE");
    expect(dropped[0]).toContain("NIFTY, BANKNIFTY, SENSEX");
  });

  it("drops a repeated id, which would give two panes one prefs scope", () => {
    const { layout: l, dropped } = parseLayout({ preset: "2H", panes: [pane("p1", "NIFTY"), pane("p1", "SENSEX")] });
    expect(ids(l)).toEqual(["p1"]);
    expect(symbols(l)).toEqual(["NIFTY"]);
    expect(dropped).toHaveLength(1);
    expect(dropped[0]).toContain("p1");
  });

  it("keeps a pane whose resolution went bad, at the default resolution and without a notice", () => {
    const { layout: l, dropped } = parseLayout({ preset: "1", panes: [{ id: "p1", symbol: "NIFTY", res: "4h" }] });
    expect(l.panes[0]).toEqual({ id: "p1", symbol: "NIFTY", res: "15m" });
    expect(dropped).toEqual([]);
  });

  it("truncates to what the preset holds, says which preset did it, and infers an unknown one", () => {
    const three = [pane("p1"), pane("p2"), pane("p3")];
    const { layout: l, dropped } = parseLayout({ preset: "2H", panes: three });
    expect(l.panes).toHaveLength(2);
    expect(dropped).toHaveLength(1);
    expect(dropped[0]).toContain("p3");
    expect(dropped[0]).toContain("2H");
    expect(parseLayout({ preset: "grid", panes: three }).layout.preset).toBe("3");
  });

  it("keeps every reason when nothing at all survives", () => {
    const { layout: l, dropped } = parseLayout({
      preset: "2H", panes: [{ id: "p1", symbol: "RELIANCE" }, null, { symbol: "NIFTY" }],
    });
    expect(l).toEqual(emptyLayout());
    expect(dropped).toHaveLength(3);
  });
});
