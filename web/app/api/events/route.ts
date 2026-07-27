import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";
import { EconEvent } from "@/lib/data";

const impactFor = (kind = ""): EconEvent["impact"] =>
  /policy|rate|fomc|rbi|cpi|inflation|gdp|macro-ai/i.test(kind) ? "high"
  : /holiday|expiry|schedule/i.test(kind) ? "low" : "medium";

const REGION_LABEL: Record<string, string> = { india: "IN", international: "INTL" };

// Real service (services/market_events.py): deterministic holidays/expiry/
// earnings + NIM-AI-enriched macro events, grounded with a source link. Shape
// is {india: [...], international: [...]}, not a flat `events` array.
export async function GET() {
  const live = await fromApi<{ india?: any[]; international?: any[] }>("/api/events", 14000);
  const raw = [...(live?.india ?? []), ...(live?.international ?? [])];
  if (!raw.length) return NextResponse.json({ ok: false, items: [] });
  const items: EconEvent[] = raw.slice(0, 40).map((e: any) => ({
    date: (e.date ?? "").slice(0, 10),
    time: "—",
    title: e.detail ? `${e.title} — ${e.detail}` : (e.title ?? "Event"),
    country: REGION_LABEL[e.region] ?? (e.region ?? "—"),
    impact: impactFor(e.kind ?? ""),
    forecast: "—",
    prior: "—",
    url: e.url ?? undefined,
  })).filter((e: EconEvent) => e.date)
    .sort((a, b) => a.date.localeCompare(b.date));
  return NextResponse.json({ ok: true, items });
}
