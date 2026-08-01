"use client";
import { useEffect, useMemo, useState } from "react";
import { Stock } from "@/lib/data";
import { useMarketWs } from "@/lib/use-ws";

// Live last-traded price for whatever symbols are on screen.
//
// Every equity price in this app comes from prices_daily, which the intraday
// ETL rewrites every 3 minutes — so during a live session the tables were up
// to 3 minutes stale while the index tape above them ticked in real time. This
// overlays the Upstox tick stream on top: the REST value is the baseline (and
// the only thing shown outside market hours), ticks take over while trading.
//
// Subscribing is cheap — one socket for the whole app, one message per symbol
// set — so any list can call this with the rows it renders.

export type LiveTick = { price: number; changePct: number | null; at: number };

export function useLivePrices(symbols: string[]): Record<string, LiveTick> {
  const [live, setLive] = useState<Record<string, LiveTick>>({});
  const { subscribe } = useMarketWs();

  // Content-derived key: a freshly-mapped array every render would otherwise
  // resubscribe on every render.
  const key = useMemo(
    () => [...new Set(symbols.filter(Boolean).map((s) => s.toUpperCase()))].sort().join(","),
    [symbols]
  );

  useEffect(() => {
    if (!key) return;
    const offs = key.split(",").map((sym) =>
      subscribe([sym], (t: any) => {
        if (t?.ltp == null) return;
        setLive((prev) => ({
          ...prev,
          [sym]: {
            price: t.ltp,
            // `close` on the tick is the previous close; without it we have a
            // live price but no honest day-change, so leave it null rather
            // than measure against the wrong baseline.
            changePct: t.close ? ((t.ltp - t.close) / t.close) * 100 : null,
            at: Date.now(),
          },
        }));
      })
    );
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return live;
}

/** Merge live ticks into a Stock list, leaving untouched rows as they are. */
export function withLivePrices(rows: Stock[], live: Record<string, LiveTick>): Stock[] {
  if (!rows.length) return rows;
  return rows.map((s) => {
    const t = live[s.symbol?.toUpperCase()];
    if (!t) return s;
    const changePct = t.changePct ?? s.changePct;
    return {
      ...s,
      price: t.price,
      changePct,
      change: changePct != null ? (t.price * changePct) / 100 : s.change,
      isLive: true,
    };
  });
}
