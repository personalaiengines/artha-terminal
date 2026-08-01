// Runnable self-check for lib/live-bar.ts, same shape as indicators.check.ts —
// no test runner in this repo, `tsc` is already a dependency:
//
//   cd web && npx tsc lib/live-bar.ts lib/live-bar.check.ts --outDir .checkout --module commonjs --target es2022 --strict && node .checkout/live-bar.check.js
//
// Prints "live-bar OK" and exits 0, or throws.

import { foldTick, inSession, istDate, tickTime, type Bar } from "./live-bar";

const ok = (cond: boolean, msg: string) => { if (!cond) throw new Error(msg); };

const MIN = 60_000;
// 2026-07-31 09:15 IST = 03:45 UTC.
const t0 = Date.parse("2026-07-31T03:45:00Z");
const bar: Bar = { timestamp: t0, open: 100, high: 102, low: 99, close: 101, volume: 5 };

// --- inside the bar: high/low extend, close follows, timestamp holds ---------
const a = foldTick(bar, 103, t0 + 30_000, 5 * MIN)!;
ok(a.timestamp === t0 && a.high === 103 && a.low === 99 && a.close === 103 && a.open === 100,
  "tick inside the bar must extend it, not move or reopen it");
ok(foldTick(bar, 98, t0 + 30_000, 5 * MIN)!.low === 98, "a new low must widen the bar");

// --- past the bar width: a new bar opens at the feed's own alignment ---------
const b = foldTick(bar, 105, t0 + 11 * MIN, 5 * MIN)!;
ok(b.timestamp === t0 + 10 * MIN, "new bar must land on a multiple of the step off the last bar");
ok(b.open === 105 && b.high === 105 && b.low === 105 && b.close === 105, "a fresh bar opens flat at the tick");
ok(b.volume === 0, "volume is not streamed — a bar opened from a tick carries 0, never the last bar's");

// 60m bars are IST-aligned (:15 past the UTC hour); flooring the clock would
// move them, stepping off the last bar does not.
const h0 = Date.parse("2026-07-31T04:15:00Z");
const h = foldTick({ ...bar, timestamp: h0 }, 105, h0 + 61 * MIN, 60 * MIN)!;
ok(new Date(h.timestamp).toISOString().endsWith("05:15:00.000Z"), "hourly bars must keep their :15 alignment");

// --- daily: never open tomorrow's bar from a tick (T10) ---------------------
const day = Date.parse("2026-07-31T00:00:00Z");   // stored at UTC midnight of the trading date
const d: Bar = { timestamp: day, open: 100, high: 102, low: 99, close: 101 };
ok(foldTick(d, 104, Date.parse("2026-07-31T09:00:00Z"), 0)!.close === 104,
  "a tick during the same IST day folds into that day's bar");
ok(foldTick(d, 104, Date.parse("2026-08-03T04:00:00Z"), 0) === null,
  "a tick on a later trading day must draw nothing — the daily bar comes from the store");
// 2026-07-31 23:00 UTC is already 2026-08-01 in IST.
ok(foldTick(d, 104, Date.parse("2026-07-31T23:00:00Z"), 0) === null,
  "the day boundary is IST, not UTC");

ok(istDate(Date.parse("2026-07-31T19:00:00Z")) === "2026-08-01", "istDate: after 18:30 UTC it is tomorrow in IST");
ok(foldTick(bar, Number.NaN, t0 + 1000, MIN) === null, "an unusable tick draws nothing");

// --- outside the session an intraday tick draws nothing (T10) ---------------
// 16:30 IST = 11:00 UTC, an hour after the close.
ok(foldTick(bar, 105, Date.parse("2026-07-31T11:00:00Z"), 5 * MIN) === null,
  "a tick after 15:30 IST must not open a bar on a closed market");
ok(foldTick(bar, 105, Date.parse("2026-07-31T02:00:00Z"), 5 * MIN) === null,
  "a tick before 09:15 IST must not open a bar either");
ok(inSession(Date.parse("2026-07-31T03:45:00Z")), "09:15 IST is in session");
ok(inSession(Date.parse("2026-07-31T10:00:00Z")), "15:30 IST is in session");
ok(!inSession(Date.parse("2026-07-31T10:01:00Z")), "15:31 IST is not");
// Daily bars are unaffected: their guard is the trading date, not the clock.
ok(foldTick(d, 104, Date.parse("2026-07-31T11:00:00Z"), 0)!.close === 104,
  "a daily bar still takes the closing print after 15:30");

// --- the exchange's clock wins over the browser's ---------------------------
ok(tickTime(t0 + 5000, t0) === t0 + 5000, "a sane ltt is used as-is");
ok(tickTime(undefined, t0) === t0, "no ltt falls back to now");
ok(tickTime(1, t0) === t0, "an ltt a decade off is ignored, not drawn");

console.log("live-bar OK");
