// Folding a live tick into the bar it belongs to. Pure, so it can be run and
// asserted on its own (see live-bar.check.ts for the assertions and the command).

export type Bar = { timestamp: number; open: number; high: number; low: number; close: number; volume?: number };

export const IST_MS = 5.5 * 3600 * 1000;

/** The IST calendar date a UTC epoch falls on. Daily bars are stored at UTC
 *  midnight of their trading date, so this reads them back unchanged. */
export const istDate = (ms: number) => new Date(ms + IST_MS).toISOString().slice(0, 10);

/** Minutes past IST midnight. */
export const istMinutes = (ms: number) => {
  const d = new Date(ms + IST_MS);
  return d.getUTCHours() * 60 + d.getUTCMinutes();
};

// The regular session, 09:15-15:30 IST. Outside it there is no bar to extend and
// none to open: a tick that arrives late (a reconnect replay, a stale frame) must
// not invent 22:00 candles on a market that closed at 15:30.
const OPEN_MIN = 9 * 60 + 15;
const CLOSE_MIN = 15 * 60 + 30;
export const inSession = (ms: number) => {
  const m = istMinutes(ms);
  return m >= OPEN_MIN && m <= CLOSE_MIN;
};

/** Whether a chart may still claim it is streaming.
 *
 *  The status used to be a boolean latched true by the first tick and reset only
 *  on a symbol or resolution change, so at 15:31 every chart on the page went on
 *  claiming a live tape all night. Recency is the only honest answer: inside the
 *  window it is streaming, outside it the caller shows when the last tick landed.
 *
 *  A `lastTickAt` ahead of `now` reads as live — the clock driving this is
 *  sampled, so it can lag a tick by a few seconds. */
export const isStreaming = (lastTickAt: number | null, now: number, windowMs = 15_000): boolean =>
  lastTickAt != null && now - lastTickAt <= windowMs;

/** The exchange's own timestamp for a tick when it carries one (`ltt`), else the
 *  browser clock. A clock that disagrees with the tape by more than a day is not
 *  a timestamp worth trusting, so it is ignored rather than drawn. */
export function tickTime(ltt: unknown, now: number): number {
  const t = Number(ltt);
  return Number.isFinite(t) && Math.abs(t - now) < 2 * 86400_000 ? t : now;
}

/**
 * The bar to hand the chart for a tick of `ltp` at `now`, or null when the tick
 * belongs to no bar we may draw.
 *
 * `step` is the bar width in ms, or 0 for daily bars. Two rules keep this from
 * fabricating data (T10):
 *   · a tick on a trading day after the last daily bar returns null — a new
 *     daily bar comes from the store, never from a tick;
 *   · a bar opened here carries volume 0, because the tape streams no volume.
 *     0 is the measurement, not a placeholder — the next poll replaces the bar
 *     with the exchange's own.
 */
export function foldTick(last: Bar, ltp: number, now: number, step: number): Bar | null {
  if (!Number.isFinite(ltp)) return null;
  // Intraday bars exist only inside the session. Outside it the last bar has
  // settled, and a late tick is not new information about it.
  if (step > 0 && !inSession(now)) return null;
  if (step > 0 && now - last.timestamp >= step) {
    // Step off the last bar rather than flooring the clock: IST hourly bars sit
    // 30 minutes off the UTC hour, so flooring would misalign them.
    const k = Math.floor((now - last.timestamp) / step);
    return { timestamp: last.timestamp + k * step, open: ltp, high: ltp, low: ltp, close: ltp, volume: 0 };
  }
  if (step === 0 && istDate(now) !== istDate(last.timestamp)) return null;
  return { ...last, high: Math.max(last.high, ltp), low: Math.min(last.low, ltp), close: ltp };
}
