"use client";
import { useEffect, useState } from "react";

// Empty-state-first live data. Renders `fallback` instantly (so the page is
// never blank or broken), then swaps in live data once the route handler
// answers ok. A failed or ok:false response is ignored — the fallback stays.
// `pick` extracts the shape.
// `refreshMs` re-fetches on an interval — for anything that moves while the
// user is looking at it (index levels, session state). Omit it and the fetch
// stays one-shot, which is right for everything else.
export function useApi<T>(
  path: string, fallback: T, pick: (json: any) => T = (j) => j, refreshMs = 0
): T {
  const [data, setData] = useState<T>(fallback);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(path)
        .then((r) => r.json())
        .then((j) => {
          if (!alive || !j || j.ok === false) return;
          const next = pick(j);
          if (next !== undefined && next !== null) setData(next);
        })
        .catch(() => {});
    load();
    // Anything that changes server state (authorizing Upstox, triggering an
    // ETL) can dispatch `artha:refresh` to pull every hook forward instead of
    // leaving the UI reporting the old state until its next tick.
    const onRefresh = () => load();
    window.addEventListener("artha:refresh", onRefresh);

    const id = refreshMs ? setInterval(load, refreshMs) : undefined;
    return () => {
      alive = false;
      window.removeEventListener("artha:refresh", onRefresh);
      if (id) clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, refreshMs]);
  return data;
}
