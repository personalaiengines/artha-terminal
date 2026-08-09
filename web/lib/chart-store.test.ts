import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearDrawings, drawKey, migrateLegacyPrefs, onDrawingsChanged, prefsKey, readJson, writeDrawings,
  writeJson, type SavedDrawing,
} from "./chart-store";

// vitest runs in node and readJson/writeJson no-op without a window, so the
// whole DOM this module needs is one Map behind a localStorage shape.
const store = new Map<string, string>();
const LEGACY = "artha.chart.prefs.v1";

beforeEach(() => {
  store.clear();
  (globalThis as { window?: unknown }).window = {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, v); },
      removeItem: (k: string) => { store.delete(k); },
    },
  };
});
afterEach(() => { delete (globalThis as { window?: unknown }).window; });

const prefs = (scope: string) => readJson<{ type?: string } | null>(prefsKey(scope), null);

describe("prefsKey", () => {
  it("keeps two scopes apart whichever is written first", () => {
    writeJson(prefsKey("charts.p1"), { type: "area" });
    writeJson(prefsKey("fno"), { type: "bars" });
    writeJson(prefsKey("charts.p2"), { type: "hollow" });
    expect(prefs("charts.p1")?.type).toBe("area");
    expect(prefs("fno")?.type).toBe("bars");
    expect(prefs("charts.p2")?.type).toBe("hollow");
  });
});

describe("migrateLegacyPrefs", () => {
  it("hands the old global setup to the F&O chart that wrote it", () => {
    store.set(LEGACY, JSON.stringify({ type: "area", hidden: ["Pivot R2"] }));
    migrateLegacyPrefs("fno");
    expect(prefs("fno")).toEqual({ type: "area", hidden: ["Pivot R2"] });
    expect(store.has(prefsKey("fno"))).toBe(true);
  });

  it("leaves the v1 key in place, so a rollback still finds the setup", () => {
    store.set(LEGACY, JSON.stringify({ type: "area" }));
    migrateLegacyPrefs("fno");
    expect(store.get(LEGACY)).toBe(JSON.stringify({ type: "area" }));
  });

  it("starts every other scope from defaults", () => {
    store.set(LEGACY, JSON.stringify({ type: "area" }));
    migrateLegacyPrefs("charts.p1");
    expect(prefs("charts.p1")).toBeNull();
    expect(store.has(prefsKey("charts.p1"))).toBe(false);
  });

  it("runs once — a scope already written is never overwritten", () => {
    store.set(LEGACY, JSON.stringify({ type: "area" }));
    writeJson(prefsKey("fno"), { type: "candles" });
    migrateLegacyPrefs("fno");
    expect(prefs("fno")?.type).toBe("candles");
  });

  it("is a no-op with nothing to migrate", () => {
    migrateLegacyPrefs("fno");
    expect(store.size).toBe(0);
  });

  it("does not migrate a corrupt v1 value over the defaults", () => {
    store.set(LEGACY, "{ not json");
    migrateLegacyPrefs("fno");
    expect(store.has(prefsKey("fno"))).toBe(false);
  });
});

describe("onDrawingsChanged", () => {
  const line: SavedDrawing[] = [{ name: "segment", points: [{ timestamp: 1, value: 2 }] }];

  it("tells the other chart on this symbol, and writes what it says it wrote", () => {
    const heard = vi.fn();
    const off = onDrawingsChanged("NIFTY", heard);
    writeDrawings("NIFTY", line, "paneA");
    expect(heard).toHaveBeenCalledWith("paneA");
    expect(readJson(drawKey("NIFTY"), [])).toEqual(line);
    off();
  });

  it("lets a chart skip its own echo, and never fires for another symbol", () => {
    const nifty = vi.fn();
    const bank = vi.fn();
    const offN = onDrawingsChanged("NIFTY", nifty);
    const offB = onDrawingsChanged("BANKNIFTY", bank);
    writeDrawings("NIFTY", line, "paneA");
    expect(nifty.mock.calls).toEqual([["paneA"]]);   // paneA compares and ignores
    expect(bank).not.toHaveBeenCalled();
    offN(); offB();
  });

  it("fires on a clear as well as a write — an emptied chart must empty the other", () => {
    const heard = vi.fn();
    const off = onDrawingsChanged("NIFTY", heard);
    writeDrawings("NIFTY", line, "paneA");
    clearDrawings("NIFTY", "paneB");
    expect(heard).toHaveBeenLastCalledWith("paneB");
    expect(store.has(drawKey("NIFTY"))).toBe(false);
    off();
  });

  it("stops after unsubscribe, so a removed pane is not kept alive by the map", () => {
    const heard = vi.fn();
    onDrawingsChanged("NIFTY", heard)();
    writeDrawings("NIFTY", line, "paneA");
    expect(heard).not.toHaveBeenCalled();
  });
});
