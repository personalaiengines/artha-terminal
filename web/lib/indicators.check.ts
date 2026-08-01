// Runnable self-check for lib/indicators.ts. There is no JS test runner in this
// repo (no jest, no vitest, no `test` script) and adding one to assert four pure
// functions would cost more than the functions. `tsc` is already a dependency,
// so compile and run:
//
//   cd web && npx tsc lib/indicators.ts lib/indicators.check.ts --outDir .checkout --module commonjs --target es2022 --strict && node .checkout/indicators.check.js
//
// Prints "indicators OK" and exits 0, or throws.

import { bollinger, ema, rsi, vwap } from "./indicators";

const ok = (cond: boolean, msg: string) => { if (!cond) throw new Error(msg); };
const near = (a: number, b: number, eps = 1e-6) => Math.abs(a - b) < eps;

// --- too-short input renders NOTHING, never a partial line (T10) -------------
ok(ema([1, 2, 3], 20).length === 0, "ema: 3 bars, period 20 must give []");
ok(rsi(new Array(14).fill(1), 14).length === 0, "rsi: needs period+1 bars");
ok(rsi(new Array(15).fill(1), 14).length === 15, "rsi: period+1 bars is enough");
ok(bollinger([1, 2, 3], 20).mid.length === 0, "bollinger: 3 bars, period 20 must give []");

// --- EMA: SMA seed then the standard k = 2/(n+1) recurrence ------------------
const e = ema([2, 4, 6, 8], 2);
ok(e[0] === null, "ema: index 0 undefined for period 2");
ok(near(e[1] as number, 3), "ema: seed is the SMA of the first 2 (=3)");
ok(near(e[2] as number, 6 * (2 / 3) + 3 * (1 / 3)), "ema: recurrence at index 2");

// --- RSI: an unbroken rise is 100, an unbroken fall is 0 --------------------
const up = rsi(Array.from({ length: 30 }, (_, i) => 100 + i), 14);
ok(near(up[29] as number, 100), "rsi: monotonic rise must be 100");
const down = rsi(Array.from({ length: 30 }, (_, i) => 100 - i), 14);
ok(near(down[29] as number, 0), "rsi: monotonic fall must be 0");

// --- Bollinger: constant series has zero width, bands sit on the mean --------
const flat = bollinger(new Array(25).fill(50), 20);
ok(near(flat.mid[24] as number, 50) && near(flat.upper[24] as number, 50), "bollinger: flat series");
const bb = bollinger([1, 2, 3, 4, 5], 5, 2);
ok(near(bb.mid[4] as number, 3), "bollinger: mean of 1..5 is 3");
ok(near(bb.upper[4] as number, 3 + 2 * Math.sqrt(2)), "bollinger: population sd of 1..5 is sqrt(2)");

// --- VWAP: volume-weighted, and re-anchored at a session change --------------
const bars = [
  { high: 3, low: 1, close: 2, volume: 100 },   // typical 2
  { high: 6, low: 4, close: 5, volume: 300 },   // typical 5
  { high: 9, low: 7, close: 8, volume: 100 },   // typical 8 — new session
];
const v = vwap(bars, ["d1", "d1", "d2"]);
ok(near(v[0] as number, 2), "vwap: first bar is its own typical price");
ok(near(v[1] as number, (2 * 100 + 5 * 300) / 400), "vwap: weighted by volume");
ok(near(v[2] as number, 8), "vwap: re-anchors on a new session");
ok(vwap(bars.map((b) => ({ ...b, volume: 0 })), ["d1", "d1", "d1"]).length === 0,
  "vwap: zero volume (index bars) must render nothing, not a typical-price line");

console.log("indicators OK");
