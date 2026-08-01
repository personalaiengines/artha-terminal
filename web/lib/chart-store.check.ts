// Runnable self-check for lib/chart-store.ts, same shape as the others:
//
//   cd web && npx tsc lib/chart-store.ts lib/chart-store.check.ts --outDir .checkout --module commonjs --target es2022 --strict && node .checkout/chart-store.check.js
//
// Prints "chart-store OK" and exits 0, or throws.

import { drawKey, isDrawing, prefsKey, readJson, toSaved, writeJson } from "./chart-store";

const ok = (cond: boolean, msg: string) => { if (!cond) throw new Error(msg); };

// --- what a drawing keeps, and what it must not ----------------------------
const saved = toSaved("segment", [
  { timestamp: 1_785_000_000_000, value: 24_400 } as any,
  { timestamp: 1_785_003_600_000, value: 24_500, dataIndex: 37 } as any,
]);
ok(saved.points.length === 2, "both anchored points are kept");
ok(!("dataIndex" in saved.points[1]), "dataIndex is a view position, never saved");
ok(saved.points[0].timestamp === 1_785_000_000_000 && saved.points[0].value === 24_400, "anchors survive verbatim");
// A horizontal line has a price and no time — still a drawing.
ok(toSaved("horizontalStraightLine", [{ value: 24_400 }]).points.length === 1, "a price-only point is anchored");
// A point with neither is not an anchor at all.
ok(toSaved("segment", [{} as any, { value: 1 }]).points.length === 1, "an empty point is dropped");

// --- storage read back is untrusted ----------------------------------------
ok(isDrawing(saved), "a round-tripped drawing validates");
ok(!isDrawing(null), "null is not a drawing");
ok(!isDrawing({ name: "segment", points: [] }), "a drawing with no points is rejected");
ok(!isDrawing({ name: "", points: [{ value: 1 }] }), "a nameless drawing is rejected");
ok(!isDrawing({ name: "segment", points: [{ nope: 1 }] }), "a point with no anchor is rejected");
ok(!isDrawing({ name: "segment", points: [null] }), "a null point is rejected");
ok(!isDrawing('{"name":"segment"}'), "a raw string is not a drawing");

// --- reads are total: no window, bad JSON, missing key all fall back --------
ok(readJson("anything", "fallback") === "fallback", "no window (this runner) falls back");
const g = globalThis as any;
const store = new Map<string, string>();
g.window = { localStorage: {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => { store.set(k, v); },
  removeItem: (k: string) => { store.delete(k); },
} };
writeJson(prefsKey(), { type: "area", hidden: ["Pivot R2"] });
ok(readJson<{ type: string }>(prefsKey(), { type: "candles" }).type === "area", "prefs round-trip");
store.set(drawKey("NIFTY"), "{ not json");
ok(readJson(drawKey("NIFTY"), []).length === 0, "corrupt JSON falls back instead of throwing");
store.set(drawKey("NIFTY"), "null");
ok(readJson(drawKey("NIFTY"), []).length === 0, "a stored null falls back");
ok(readJson(drawKey("BANKNIFTY"), []).length === 0, "a missing key falls back");
// A throwing localStorage (private mode, quota) must not take the chart down.
g.window.localStorage.setItem = () => { throw new Error("QuotaExceededError"); };
writeJson(prefsKey(), { type: "bars" });
ok(readJson<{ type: string }>(prefsKey(), { type: "x" }).type === "area", "a failed write leaves the old value, and does not throw");

console.log("chart-store OK");
