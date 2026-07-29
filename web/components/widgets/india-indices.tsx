"use client";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { DeltaPill } from "@/components/ui/stat";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { useMarketWs } from "@/lib/use-ws";
import { changeText, trendClass } from "@/lib/format";
import { useUI } from "@/components/layout/ui-store";
import { cn } from "@/lib/utils";

// Indian index board — Nifty / Sensex / Bank Nifty / Midcap / VIX, plus Gift
// Nifty (the overnight lead indicator). The dashboard previously rendered the
// *global* board here (S&P, Nasdaq, FTSE), which is the wrong home board for
// an Indian equities terminal.
//
// Two layers of liveness, because neither alone is enough:
//   - REST poll every 30s: carries the session state (open/closed, holiday
//     aware via exchange calendars) and works with no Upstox token at all.
//   - WS ticks: sub-second level updates while the market is actually open.

export type IndexRow = {
  key: string; name: string;
  price: number | null; changePct: number | null;
  state: "open" | "closed"; note: string; localTime: string;
};

// Gift Nifty isn't in the backend's INDEX_KEYS map, so it subscribes by its
// full Upstox instrument key; the rest resolve server-side from these names.
const WS_KEY: Record<string, string> = {
  giftnifty: "GLOBAL_INDEX|SGX NIFTY",
};

export function useIndiaIndices(): IndexRow[] {
  const rows = useApi<IndexRow[]>("/api/indices", [], (j) => j.indices, POLL.indices);
  const [live, setLive] = useState<Record<string, { price: number; changePct: number | null }>>({});
  const { subscribe } = useMarketWs();

  const keys = rows.map((r) => r.key).join(",");
  useEffect(() => {
    if (!keys) return;
    // One subscription per index: the tick handler is called with the tick
    // only, so the index it belongs to has to come from the closure.
    const offs = keys.split(",").map((k) =>
      subscribe([WS_KEY[k] ?? k], (t: any) => {
        if (t?.ltp == null) return;
        setLive((prev) => ({
          ...prev,
          [k]: {
            price: t.ltp,
            changePct: t.close ? ((t.ltp - t.close) / t.close) * 100 : null,
          },
        }));
      })
    );
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys]);

  return rows.map((r) => {
    const t = live[r.key];
    if (!t) return r;
    // Keep the REST change% when the tick carries no previous close (Upstox
    // sends cp=0 on some index feeds) rather than blanking a good number.
    return { ...r, price: t.price, changePct: t.changePct ?? r.changePct };
  });
}

function SessionDot({ state }: { state: IndexRow["state"] }) {
  const open = state === "open";
  return (
    <span
      className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", open ? "bg-up" : "bg-faint")}
      title={open ? "Market open" : "Market closed"}
      aria-label={open ? "Market open" : "Market closed"}
    />
  );
}

/** Session badge for the board as a whole — NSE/BSE share one session. */
export function SessionBadge({ rows }: { rows: IndexRow[] }) {
  const nse = rows.find((r) => r.key !== "giftnifty");
  if (!nse) return null;
  const open = nse.state === "open";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
        open ? "bg-up/10 text-up" : "bg-raised text-muted"
      )}
    >
      <SessionDot state={nse.state} />
      {open ? "Market open" : "Market closed"}
      <span className="font-normal normal-case tracking-normal text-muted">· {nse.note}</span>
    </span>
  );
}

/** Scrolling tape of every index. Pauses on hover.
 *  `bare` drops the card chrome for use inside the topbar. */
export function IndexTicker({ variant = "card" }: { variant?: "card" | "bare" }) {
  const rows = useIndiaIndices();
  const { changeMode } = useUI();
  if (rows.length === 0) return null;

  const item = (r: IndexRow, i: number) => {
    const abs = r.price != null && r.changePct != null ? (r.price * r.changePct) / 100 : null;
    return (
      <span key={`${r.key}-${i}`} className="flex items-center gap-2 whitespace-nowrap px-4 text-[12.5px]">
        <SessionDot state={r.state} />
        <span className="font-medium text-mist">{r.name}</span>
        <span className="font-semibold text-frost tnum">
          {r.price != null ? r.price.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"}
        </span>
        <span className={cn("font-medium tnum", trendClass(r.changePct ?? 0))}>
          {r.changePct != null ? changeText(r.changePct, abs, changeMode) : "—"}
        </span>
        <span className="text-faint">|</span>
      </span>
    );
  };

  return (
    <div
      className={cn(
        "marquee overflow-hidden",
        variant === "card" && "mb-4 rounded-[var(--radius-md)] bg-elevated py-2 hairline"
      )}
      aria-label="Live Indian index prices"
    >
      <div className="marquee-track">
        {/* Rendered twice — the CSS translates by -50% for a seamless loop. */}
        {rows.map(item)}
        {rows.map((r, i) => item(r, i + rows.length))}
      </div>
    </div>
  );
}

/** Card grid of the same board, with per-index session state. */
export function IndexStrip() {
  const rows = useIndiaIndices();
  if (rows.length === 0) return null;

  return (
    <div className="mb-6">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[13px] font-semibold uppercase tracking-wide text-muted">Indian Markets</h3>
        <SessionBadge rows={rows} />
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        {rows.slice(0, 6).map((r, i) => {
          const abs = r.price != null && r.changePct != null ? (r.price * r.changePct) / 100 : null;
          return (
            <Card key={r.key} delay={i * 0.04} interactive className="p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5">
                  <SessionDot state={r.state} />
                  <span className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted">{r.name}</span>
                </span>
                {r.changePct != null && <DeltaPill value={abs} pct={r.changePct} />}
              </div>
              <div className="mt-1.5 text-[19px] font-semibold text-frost tnum">
                {r.price != null ? r.price.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"}
              </div>
              <div className="mt-0.5 truncate text-[10.5px] text-faint" title={r.note}>
                {r.state === "open" ? "Live" : "Closed"} · {r.note}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
