"use client";
import { CalendarClock, Flag, ExternalLink } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardBody } from "@/components/ui/card";
import { ImpactBadge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/primitives";
import { EconEvent } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";

const DAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export default function Calendar() {
  const ECON_EVENTS = useApi<EconEvent[]>("/api/events", [], (j) => j.items, POLL.events);
  const byDate = ECON_EVENTS.reduce<Record<string, EconEvent[]>>((acc, e) => {
    (acc[e.date] ??= []).push(e); return acc;
  }, {});

  const label = (d: string) => {
    const dt = new Date(d);
    const today = new Date().toISOString().slice(0, 10);
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    if (d === today) return "Today";
    if (d === tomorrow) return "Tomorrow";
    return `${DAY[dt.getDay()]}, ${dt.getDate()} ${dt.toLocaleString("en", { month: "short" })}`;
  };

  return (
    <div>
      <PageHeader eyebrow="Monitor" title="Economic Calendar"
        description="High-impact macro events across India, US and Europe — with forecasts and priors." />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-4">
        <div className="space-y-6 xl:col-span-3">
          {ECON_EVENTS.length === 0 ? (
            <Card><CardBody><EmptyState icon={<CalendarClock size={22} />} title="No events loaded"
              description="The calendar feed (holidays, expiry, earnings, AI-enriched macro events) is unreachable right now." /></CardBody></Card>
          ) : Object.entries(byDate).map(([date, events]) => (
            <div key={date}>
              <div className="mb-2.5 flex items-center gap-2">
                <CalendarClock size={15} className="text-accent" />
                <h3 className="text-[14px] font-semibold text-frost">{label(date)}</h3>
                <span className="text-[11px] text-muted">{events.length} events</span>
              </div>
              <Card>
                <CardBody className="p-0">
                  {events.map((e, i) => (
                    <div key={i} className="flex items-center gap-4 border-b border-line/50 px-4 py-3 last:border-0 hover:bg-raised/40">
                      <span className="flex h-6 w-11 items-center justify-center rounded-[5px] bg-void text-[10px] font-bold text-mist hairline">{e.country}</span>
                      <span className="flex-1 text-[13px] font-medium text-frost">{e.title}</span>
                      {e.url && (
                        <a href={e.url} target="_blank" rel="noreferrer" className="hidden items-center gap-1 text-[11px] text-accent hover:underline sm:flex">
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
              <div className="text-[11px] font-semibold uppercase tracking-wide text-accent">This Week</div>
              <div className="mt-2 flex items-center justify-between text-[12px]"><span className="text-muted">High impact</span><span className="font-semibold text-frost tnum">{ECON_EVENTS.filter((e) => e.impact === "high").length}</span></div>
              <div className="mt-1 flex items-center justify-between text-[12px]"><span className="text-muted">Total events</span><span className="font-semibold text-frost tnum">{ECON_EVENTS.length}</span></div>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
