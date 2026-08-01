"use client";
import { useEffect, useState, useMemo } from "react";

// Real trailing closes for a set of symbols, for table sparklines.
//
// These used to come from lib/data.ts::series(seed) — a seeded random walk
// where the seed was derived from the symbol's own characters. That made every
// sparkline a fixed picture of the ticker's spelling: it never moved, never
// matched the price, and looked like live data. This fetches the actual closes
// from prices_daily instead, and returns nothing for symbols with no history
// so the caller can render a dash rather than invent a shape.
export function useSparklines(symbols: string[], days = 30) {
  const [series, setSeries] = useState<Record<string, number[]>>({});

  // Stable key so we refetch on content change, not identity change — a
  // freshly-mapped array every render would otherwise loop forever.
  const key = useMemo(
    () => [...new Set(symbols.filter(Boolean))].sort().join(","),
    [symbols]
  );

  useEffect(() => {
    if (!key) { setSeries({}); return; }
    let alive = true;
    fetch(`/api/history?symbols=${encodeURIComponent(key)}&days=${days}`)
      .then((r) => r.json())
      .then((j) => { if (alive && j?.ok) setSeries(j.series ?? {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, [key, days]);

  return series;
}
