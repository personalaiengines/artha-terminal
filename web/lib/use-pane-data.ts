"use client";
import { useEffect, useMemo, useState } from "react";
import { POLL } from "./poll";
import type { Candle, Plan } from "./fno-types";

// Daily bars and the level map for whatever instruments the Charts grid is
// showing — fetched once per DISTINCT symbol, not once per pane.
//
// Six panes over three indices is the design point, and three of them are
// normally the same instrument at different resolutions. Left to the panes,
// that is six /api/fno calls and six /api/history calls per cycle for three
// distinct answers. Hoisting the fetch to the page and keying it on the
// deduplicated symbol set makes it three of each (R20).
//
// Not `useApi` in a loop: pane count changes as the user adds and removes, and
// hooks cannot. One effect with a loop inside it is the smaller legal shape.

/** Content-derived key, as in use-live-prices: a freshly-mapped array every
 *  render would otherwise refetch on every render. */
function usePolled<T>(
  symbols: string[], url: (s: string) => string, pick: (json: any) => T | null, refreshMs: number
): Record<string, T> {
  const [bySymbol, setBySymbol] = useState<Record<string, T>>({});
  const key = useMemo(
    () => [...new Set(symbols.filter(Boolean))].sort().join(","), [symbols]
  );

  useEffect(() => {
    if (!key) return;
    let alive = true;
    const load = () => {
      for (const sym of key.split(",")) {
        fetch(url(sym))
          .then((r) => r.json())
          .then((j) => {
            // Same contract as useApi: a failed or ok:false answer leaves the
            // last good payload on screen rather than blanking a live pane.
            if (!alive || !j || j.ok === false) return;
            const next = pick(j);
            if (next != null) setBySymbol((prev) => ({ ...prev, [sym]: next }));
          })
          .catch(() => {});
      }
    };
    load();
    const onRefresh = () => load();
    window.addEventListener("artha:refresh", onRefresh);
    const id = setInterval(load, refreshMs);
    return () => {
      alive = false;
      window.removeEventListener("artha:refresh", onRefresh);
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, refreshMs]);

  // A symbol dropped from the grid keeps its entry: re-adding it paints the
  // last known bars immediately instead of an empty pane, and the map is
  // bounded by the three instruments this page can show.
  return bySymbol;
}

export function usePaneData(symbols: string[]): {
  candles: Record<string, Candle[]>;
  levels: Record<string, Plan | null>;
} {
  const candles = usePolled<Candle[]>(
    symbols,
    (s) => `/api/history?symbols=${s}&days=365&ohlc=1`,
    (j) => j.candles ?? null,
    POLL.history
  );
  const levels = usePolled<Plan>(symbols, (s) => `/api/fno/${s}`, (j) => j, POLL.fno);
  return { candles, levels };
}
