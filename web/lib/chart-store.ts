// Chart state that outlives a reload: what the user drew, and how they set the
// chart up. localStorage only — this is a per-browser preference, not book or
// position data, and nothing here is worth a round trip to the API.
//
// Versioned keys: a shape change reads nothing rather than half-reading an old
// value. Every read is total — a corrupt or absent entry returns the fallback,
// because a chart that throws on boot is worse than a chart that forgets.

const V = "v1";

export const prefsKey = () => `artha.chart.prefs.${V}`;
export const drawKey = (symbol: string) => `artha.chart.draw.${V}.${symbol}`;

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
