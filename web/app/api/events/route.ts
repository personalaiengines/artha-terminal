import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";
import { EconEvent } from "@/lib/data";

// Fallback only. Rows from the Forex Factory feed carry their own impact; the
// deterministic rows (holidays, expiry, earnings, AI macro) do not, so their
// `kind` decides it.
const impactFor = (kind = ""): EconEvent["impact"] =>
  /policy|rate|fomc|rbi|cpi|inflation|gdp|macro/i.test(kind) ? "high"
  : /holiday|expiry|schedule/i.test(kind) ? "low" : "medium";

const IMPACTS = new Set(["high", "medium", "low"]);

// Real service (services/market_events.py): global economic calendar (Forex
// Factory) + deterministic holidays/expiry/earnings + AI-enriched macro, each
// row with a source link. Shape is {india: [...], international: [...]}, not a
// flat `events` array.
export async function GET() {
  const live = await fromApi<{ india?: any[]; international?: any[] }>("/api/events", 14000);
  const raw = [...(live?.india ?? []), ...(live?.international ?? [])];
  if (!raw.length) return NextResponse.json({ ok: false, items: [] });
  // A fortnight of every market's releases is ~400 rows; the page filters by
  // impact rather than the feed being silently truncated to a couple of days.
  const items: EconEvent[] = raw.slice(0, 500).map((e: any) => ({
    date: (e.date ?? "").slice(0, 10),
    time: e.time_ist ?? "—",
    title: e.title ?? "Event",
    detail: e.detail ?? undefined,
    country: e.country ?? "—",
    impact: IMPACTS.has(e.impact) ? e.impact : impactFor(e.kind ?? ""),
    forecast: e.forecast ?? "—",
    prior: e.previous ?? "—",
    url: e.url ?? undefined,
  })).filter((e: EconEvent) => e.date)
    .sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
  return NextResponse.json({ ok: true, items });
}
