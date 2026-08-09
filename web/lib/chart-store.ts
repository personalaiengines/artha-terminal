// Chart state that outlives a reload: what the user drew, and how they set the
// chart up. localStorage only — this is a per-browser preference, not book or
// position data, and nothing here is worth a round trip to the API.
//
// Versioned keys: a shape change reads nothing rather than half-reading an old
// value. Every read is total — a corrupt or absent entry returns the fallback,
// because a chart that throws on boot is worse than a chart that forgets.

const V = "v1";

/** The saved setup, per chart scope. `v2` because the key gained the scope: one
 *  global prefs object was fine while the F&O page held the only chart, and is
 *  last-writer-wins the moment two charts share a page. Drawings stay on `v1` —
 *  their shape did not change and re-versioning them would orphan every saved
 *  trendline. */
export const prefsKey = (scope: string) => `artha.chart.prefs.v2.${scope}`;

const DRAW_PREFIX = `artha.chart.draw.${V}.`;
export const drawKey = (symbol: string) => `${DRAW_PREFIX}${symbol}`;

const LEGACY_PREFS_KEY = "artha.chart.prefs.v1";

/** Carry the pre-scoping setup into a scope, once. Only `"fno"` inherits it: the
 *  F&O chart is the one that wrote the global key, so it is the one whose saved
 *  setup that value describes. The v1 key is deliberately left behind — a
 *  rollback to a build without scopes must still find the setup it wrote. */
export function migrateLegacyPrefs(scope: string): void {
  if (scope !== "fno") return;
  if (readJson<unknown>(prefsKey(scope), null) != null) return;
  const legacy = readJson<unknown>(LEGACY_PREFS_KEY, null);
  if (legacy != null) writeJson(prefsKey(scope), legacy);
}

export type SavedPoint = { timestamp?: number; value?: number };
export type SavedDrawing = { name: string; points: SavedPoint[]; styles?: unknown };

export function readJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (raw == null) return fallback;
    const value = JSON.parse(raw);
    return value == null ? fallback : (value as T);
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota, private mode, storage disabled. The chart keeps working; it just
    // forgets — which is the old behaviour, not a new failure.
  }
}

export function remove(key: string): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(key); } catch { /* see writeJson */ }
}

// ---- drawings changed, told to everyone drawing the same symbol -------------
//
// Two charts on one symbol share drawKey(symbol) by design — a trendline belongs
// to the instrument, not to the window it is drawn in. What they had no way to do
// was hear about each other's writes, so the second pane showed the first pane's
// drawing only after a reload, and its own next save overwrote it.
//
// A `storage` event cannot fix that: the browser fires it in OTHER documents
// only, so six panes in one page never hear a thing. The channel has to be
// in-page; `storage` is kept below for the other-tab half it does cover.

type DrawListener = (token: string) => void;
const drawListeners = new Map<string, Set<DrawListener>>();

/** Called with the token of whoever wrote, so a chart can ignore its own echo. */
export function onDrawingsChanged(symbol: string, fn: DrawListener): () => void {
  let set = drawListeners.get(symbol);
  if (!set) { set = new Set(); drawListeners.set(symbol, set); }
  set.add(fn);
  return () => { set.delete(fn); };
}

const emitDrawings = (symbol: string, token: string) => {
  for (const fn of [...(drawListeners.get(symbol) ?? [])]) fn(token);
};

export function writeDrawings(symbol: string, saved: SavedDrawing[], token: string): void {
  writeJson(drawKey(symbol), saved);
  emitDrawings(symbol, token);
}

export function clearDrawings(symbol: string, token: string): void {
  remove(drawKey(symbol));
  emitDrawings(symbol, token);
}

// The cross-tab half. An empty token because no chart in THIS document wrote it,
// so every listener here reloads.
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (e) => {
    if (e.key?.startsWith(DRAW_PREFIX)) emitDrawings(e.key.slice(DRAW_PREFIX.length), "");
  });
}

/** A drawing, reduced to what actually anchors it. `dataIndex` is a position in
 *  the current view, not an anchor: saving it would pin a trendline to "the 40th
 *  bar on screen" and move it every time the window changes. Timestamp and price
 *  survive a resolution switch; that pair is the whole record. */
export function toSaved(name: string, points: SavedPoint[], styles?: unknown): SavedDrawing {
  return {
    name,
    points: points
      .filter((p) => Number.isFinite(p.timestamp) || Number.isFinite(p.value))
      .map((p) => ({
        ...(Number.isFinite(p.timestamp) ? { timestamp: p.timestamp } : {}),
        ...(Number.isFinite(p.value) ? { value: p.value } : {}),
      })),
    ...(styles ? { styles } : {}),
  };
}

/** Anything read back from storage is untrusted input — it was written by an
 *  older build, or edited by hand. A drawing with no name or no usable point is
 *  dropped rather than handed to the chart. */
export function isDrawing(x: unknown): x is SavedDrawing {
  if (typeof x !== "object" || x === null) return false;
  const d = x as SavedDrawing;
  return typeof d.name === "string" && d.name.length > 0
    && Array.isArray(d.points) && d.points.length > 0
    && d.points.every((p) => p != null && (Number.isFinite(p.timestamp) || Number.isFinite(p.value)));
}
