// Coalescing identical GETs across components that poll on their own timers.
//
// Every chart on a page polls /api/udf/history for its own (symbol, resolution).
// Six panes over three instruments meant six requests a minute where three would
// do, and nothing lined the timers up — they drift, so the requests arrive
// scattered rather than together. Keying on the URL fixes both: a pane on another
// resolution is a different key and fetches normally.

type Entry = { at: number; promise: Promise<unknown> };

const cache = new Map<string, Entry>();

/**
 * `fetch(url)` parsed as JSON, shared with every caller that asks for the same
 * URL within `ttlMs` — the in-flight promise while one is running, its result
 * after.
 *
 * A rejection is dropped rather than cached: a cached failure would freeze every
 * caller on that URL for the length of the TTL, which on a 55s window is a pane
 * showing a stale error for a minute after the network came back.
 */
export function getOnce<T = unknown>(url: string, ttlMs: number): Promise<T> {
  const now = Date.now();
  const hit = cache.get(url);
  if (hit && now - hit.at <= ttlMs) return hit.promise as Promise<T>;

  const promise = fetch(url).then((r) => r.json());
  cache.set(url, { at: now, promise });
  promise.catch(() => {
    // Only if it is still the entry we put there — a later caller may have
    // replaced it after the TTL expired.
    if (cache.get(url)?.promise === promise) cache.delete(url);
  });
  return promise as Promise<T>;
}
