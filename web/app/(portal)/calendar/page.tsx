"use client";
import { useMemo, useState } from "react";
import { CalendarClock, Flag, ExternalLink } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardBody } from "@/components/ui/card";
import { ImpactBadge } from "@/components/ui/badge";
import { EmptyState, Segmented } from "@/components/ui/primitives";
import { EconEvent } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";

const DAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const RANK: Record<EconEvent["impact"], number> = { high: 3, medium: 2, low: 1 };
const FILTERS = [
  { label: "All", value: "low" as const },
  { label: "Medium+", value: "medium" as const },
  { label: "High only", value: "high" as const },
];

// The API hands back plain YYYY-MM-DD strings already resolved to IST, so
// "today" must be IST too — on a machine west of India the browser's own
// calendar date is still yesterday, which labels the current session
// "Tomorrow" and drops the Today block entirely. en-CA formats as YYYY-MM-DD.
const istDay = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
});

function dayLabel(d: string) {
  if (d === istDay.format(Date.now())) return "Today";
  if (d === istDay.format(Date.now() + 86400000)) return "Tomorrow";
  // Build from the parts, not `new Date(d)` — that parses bare YYYY-MM-DD as
  // UTC midnight and shifts the weekday for negative-offset viewers.
  const [y, m, day] = d.split("-").map(Number);
  return `${DAY[new Date(y, m - 1, day).getDay()]}, ${day} ${MONTH[m - 1]}`;
}

export default function Calendar() {
  const events = useApi<EconEvent[]>("/api/events", [], (j) => j.items, POLL.events);
  const [minImpact, setMinImpact] = useState<EconEvent["impact"]>("medium");
  const [country, setCountry] = useState("all");

  const countries = useMemo(
    () => [...new Set(events.map((e) => e.country))].sort(),
    [events]
  );

  const shown = useMemo(
    () => events.filter(
      (e) => RANK[e.impact] >= RANK[minImpact] && (country === "all" || e.country === country)
    ),
    [events, minImpact, country]
  );

  const byDate = useMemo(
    () => shown.reduce<Record<string, EconEvent[]>>((acc, e) => {
      (acc[e.date] ??= []).push(e); return acc;
    }, {}),
    [shown]
  );

  return (
    <div>
      <PageHeader eyebrow="Monitor" title="Economic Calendar"
        description="Every scheduled release across the major markets — India, US, Europe, UK, Japan, China, Australia, Canada — with impact, forecast and prior. Times in IST." />

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Segmented options={FILTERS} value={minImpact} onChange={setMinImpact} size="sm" />
        <select
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          aria-label="Filter by market"
          className="rounded-[var(--radius-sm)] bg-void px-3 py-1.5 text-[12px] text-mist hairline"
        >
          <option value="all">All markets</option>
          {countries.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <span className="text-[11px] text-muted tnum">{shown.length} of {events.length} events</span>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-4">
        <div className="space-y-6 xl:col-span-3">
          {shown.length === 0 ? (
            <Card><CardBody><EmptyState icon={<CalendarClock size={22} />}
              title={events.length ? "No events match this filter" : "No events loaded"}
              description={events.length
                ? "Widen the impact filter or pick a different market."
                : "The calendar feed (global economic releases, holidays, expiry, earnings) is unreachable right now."} /></CardBody></Card>
          ) : Object.entries(byDate).map(([date, rows]) => (
            <div key={date}>
              <div className="mb-2.5 flex items-center gap-2">
                <CalendarClock size={15} className="text-accent" />
                <h3 className="text-[14px] font-semibold text-frost">{dayLabel(date)}</h3>
                <span className="text-[11px] text-muted">{rows.length} events</span>
              </div>
              <Card>
                <CardBody className="p-0">
                  {rows.map((e, i) => (
                    <div key={i} className="flex items-center gap-3 border-b border-line/50 px-4 py-3 last:border-0 hover:bg-raised/40">
                      <span className="w-11 shrink-0 text-[11px] text-muted tnum">{e.time}</span>
                      <span className="flex h-6 w-11 shrink-0 items-center justify-center rounded-[5px] bg-void text-[10px] font-bold text-mist hairline">{e.country}</span>
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-frost">{e.title}</span>
                      <span className="hidden w-40 shrink-0 justify-end gap-3 text-[11px] tnum md:flex">
                        <span className="text-muted">F <span className="text-mist">{e.forecast || "—"}</span></span>
                        <span className="text-muted">P <span className="text-mist">{e.prior || "—"}</span></span>
                      </span>
                      {e.url && (
                        <a href={e.url} target="_blank" rel="noreferrer" aria-label={`Source for ${e.title}`}
                          className="hidden shrink-0 items-center gap-1 text-[11px] text-accent hover:underline sm:flex">
                          Source <ExternalLink size={11} />
                        </a>
                      )}
                      <ImpactBadge impact={e.impact} />
                    </div>
                  ))}
                </CardBody>
              </Card>
            </div>
          ))}
        </div>

        <Card>
          <CardBody className="pt-5">
            <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-frost"><Flag size={15} className="text-muted" />Impact Legend</div>
            <div className="space-y-3 text-[12px]">
              <div className="flex items-center gap-2"><ImpactBadge impact="high" /><span className="text-muted">Market-moving — expect volatility</span></div>
              <div className="flex items-center gap-2"><ImpactBadge impact="medium" /><span className="text-muted">Notable — sector-specific</span></div>
              <div className="flex items-center gap-2"><ImpactBadge impact="low" /><span className="text-muted">Minor — informational</span></div>
            </div>
            <div className="mt-5 rounded-[var(--radius-md)] bg-void/40 p-3 hairline">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-accent">Next 14 Days</div>
              <div className="mt-2 flex items-center justify-between text-[12px]"><span className="text-muted">High impact</span><span className="font-semibold text-frost tnum">{events.filter((e) => e.impact === "high").length}</span></div>
              <div className="mt-1 flex items-center justify-between text-[12px]"><span className="text-muted">Markets covered</span><span className="font-semibold text-frost tnum">{countries.length}</span></div>
              <div className="mt-1 flex items-center justify-between text-[12px]"><span className="text-muted">Total events</span><span className="font-semibold text-frost tnum">{events.length}</span></div>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
