"use client";
import { AlertTriangle, CheckCircle2, ShieldAlert, RefreshCw } from "lucide-react";
import { Card, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

// Which upstreams are not live, since when, and what is being shown instead.
//
// The app deliberately serves the last known-good value when a feed is down —
// a real stale number beats a blank or an invented one — but that is only
// honest if the staleness is visible. This is where it's visible.

export type HealthIssue = {
  source: string;
  severity: "warn" | "error";
  title: string;
  detail: string;
  lastGood: string | null;
  fix: string | null;
};
export type Health = { live: boolean; issues: HealthIssue[]; checkedIst: string | null };

export function useDataHealth(): Health {
  return useApi<Health>(
    "/api/data-health",
    { live: true, issues: [], checkedIst: null },
    (j) => ({ live: !!j.live, issues: j.issues ?? [], checkedIst: j.checkedIst ?? null }),
    POLL.dataHealth
  );
}

/** "Out of date · 2h ago" chip for a panel serving a last-known-good payload. */
export function StaleBadge({ asOf }: { asOf: string | null }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-warn-soft/40 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-warn"
      title={asOf
        ? `Upstream unreachable — showing data last confirmed good at ${asOf}`
        : "Upstream unreachable — showing the last data that was confirmed good"}
    >
      <AlertTriangle size={10} />
      Out of date{asOf ? ` · ${timeAgo(asOf)}` : ""}
    </span>
  );
}

export function DataHealthCard() {
  const { live, issues, checkedIst } = useDataHealth();

  return (
    <Card variant="elevated" className="mb-6">
      <CardBody className="pt-5">
        <div className="mb-3 flex items-center gap-2">
          <ShieldAlert size={15} className={live ? "text-up" : "text-warn"} />
          <h3 className="text-[14px] font-semibold text-frost">Data Health</h3>
          <span className="text-[11px] text-muted">
            Which feeds are live, and what is being served when they are not
          </span>
          {checkedIst && (
            <span className="ml-auto text-[11px] text-faint">checked {timeAgo(checkedIst)}</span>
          )}
        </div>

        {live ? (
          <div className="flex items-center gap-2 rounded-[var(--radius-sm)] bg-void p-3 hairline">
            <CheckCircle2 size={14} className="text-up" />
            <span className="text-[12.5px] text-mist">
              All data sources are live. Prices, index membership and portfolio are current.
            </span>
          </div>
        ) : (
          <div className="space-y-2.5">
            {issues.map((i) => (
              <div key={i.source}
                className={cn("rounded-[var(--radius-sm)] p-3 hairline",
                  i.severity === "error" ? "bg-down-soft/20" : "bg-warn-soft/20")}>
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-frost">
                    <AlertTriangle size={13} className={i.severity === "error" ? "text-down" : "text-warn"} />
                    {i.title}
                  </span>
                  <Badge tone={i.severity === "error" ? "down" : "warn"}>
                    {i.severity === "error" ? "Not live" : "Stale"}
                  </Badge>
                </div>
                <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted">{i.detail}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                  <span className="text-faint">
                    Last good data: {i.lastGood ? timeAgo(i.lastGood) : "never"}
                  </span>
                  {i.fix && (
                    <span className="flex items-center gap-1 text-mist">
                      <RefreshCw size={10} />{i.fix}
                    </span>
                  )}
                </div>
              </div>
            ))}
            <p className="text-[11px] text-faint">
              Values from these sources keep showing their last known-good reading and will
              refresh automatically once the cause is fixed.
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
