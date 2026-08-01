"use client";
import { useEffect, useMemo } from "react";

// Tell the backend which symbols are on screen so it can refresh any that are
// stale and write them through to the DB.
//
// This replaces the nightly bulk crawl: instead of a cron fetching all 5000+
// symbols (mostly ones nobody ever opens, which is why coverage sat at ~1%),
// data is ingested when you actually look at it. Fire-and-forget — the page
// renders from the DB immediately and the refreshed values land on the next
// render. The backend bounds the fan-out so a page view can't trip yfinance's
// rate limit.
export function useEnsureFresh(symbols: string[]) {
  const key = useMemo(
    () => [...new Set(symbols.filter(Boolean))].sort().join(","),
    [symbols]
  );

  useEffect(() => {
    if (!key) return;
    fetch(`/api/ensure?symbols=${encodeURIComponent(key)}`).catch(() => {});
  }, [key]);
}
