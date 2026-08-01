// Indicator maths for the F&O chart. Pure functions over plain number arrays —
// no chart types in here, so they can be run and asserted on their own
// (see indicators.check.ts for the assertions and the exact command).
//
// Two honesty rules hold everywhere in this file (T10):
//   1. Fewer bars than the period ⇒ `[]`. Nothing renders. A short line drawn as
//      if it were the full indicator is a lie about the data.
//   2. Inside a returned array, `null` marks "not defined yet". The caller drops
//      those points rather than interpolating across them.

/** Exponential moving average, seeded with the SMA of the first `period` values
 *  (the conventional seed — the first defined point is at index `period - 1`). */
export function ema(values: number[], period: number): (number | null)[] {
  if (period < 1 || values.length < period) return [];
  const out: (number | null)[] = new Array(values.length).fill(null);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  let prev = seed / period;
  out[period - 1] = prev;
  const k = 2 / (period + 1);
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Wilder's RSI. Needs `period + 1` values (the first is consumed by the first
 *  delta), so the first defined point is at index `period`. */
export function rsi(values: number[], period = 14): (number | null)[] {
  if (period < 1 || values.length < period + 1) return [];
  const out: (number | null)[] = new Array(values.length).fill(null);
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  gain /= period; loss /= period;
  const rsiOf = (g: number, l: number) => (l === 0 ? 100 : 100 - 100 / (1 + g / l));
  out[period] = rsiOf(gain, loss);
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    gain = (gain * (period - 1) + Math.max(d, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = rsiOf(gain, loss);
  }
  return out;
}

/** Bollinger Bands: SMA ± `mult` population standard deviations. */
export function bollinger(values: number[], period = 20, mult = 2): {
  mid: (number | null)[]; upper: (number | null)[]; lower: (number | null)[];
} {
  const empty = { mid: [], upper: [], lower: [] };
  if (period < 2 || values.length < period) return empty;
  const mid: (number | null)[] = new Array(values.length).fill(null);
  const upper: (number | null)[] = new Array(values.length).fill(null);
  const lower: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i < period - 1) continue;
    const mean = sum / period;
    let sq = 0;
    for (let k = i - period + 1; k <= i; k++) sq += (values[k] - mean) ** 2;
    const sd = Math.sqrt(sq / period);
    mid[i] = mean;
    upper[i] = mean + mult * sd;
    lower[i] = mean - mult * sd;
  }
  return { mid, upper, lower };
}

export type OHLCV = { high: number; low: number; close: number; volume: number };

/** Volume-weighted average price, re-anchored every time `session[i]` changes
 *  (VWAP is a session statistic — carrying it across a day boundary is wrong).
 *
 *  Volume is real or there is no VWAP: index bars carry `volume: 0` because
 *  Upstox publishes no index volume, and a "VWAP" over zero volume is just the
 *  typical price wearing a different name. Zero total volume ⇒ `[]`. */
export function vwap(bars: OHLCV[], session: (string | number)[]): (number | null)[] {
  if (bars.length === 0 || !bars.some((b) => b.volume > 0)) return [];
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let pv = 0, vol = 0, cur = session[0];
  for (let i = 0; i < bars.length; i++) {
    if (session[i] !== cur) { cur = session[i]; pv = 0; vol = 0; }
    const tp = (bars[i].high + bars[i].low + bars[i].close) / 3;
    pv += tp * bars[i].volume;
    vol += bars[i].volume;
    out[i] = vol > 0 ? pv / vol : null;
  }
  return out;
}
