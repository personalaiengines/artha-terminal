"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Loader2, Check, AlertTriangle, RefreshCw, Clock, Database } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// Ad-hoc ETL control. Every ingestion job is listed with its last result and
// next scheduled run, and can be triggered on demand — the point being to prove
// or rule out ingestion when the data on screen looks wrong, without shelling
// into the container.

type Job = {
  id: string;
  name: string;
  running: boolean;
  nextRun: string | null;
  lastRun: {
    startedAt: string; finishedAt: string | null;
    status: "running" | "success" | "error";
    error: string | null; stats: Record<string, unknown> | null;
  } | null;
};

const when = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (Math.abs(mins) < 1) return "just now";
  if (mins > 0 && mins < 60) return `${mins}m ago`;
  if (mins < 0 && mins > -60) return `in ${-mins}m`;
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

const took = (j: Job) => {
  if (!j.lastRun?.finishedAt) return null;
  const ms = new Date(j.lastRun.finishedAt).getTime() - new Date(j.lastRun.startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return ms < 1000 ? `${ms}ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 60000)}m`;
};

// Stats shapes differ per job (rows/symbols/scored/errors...). Show whatever
// numbers came back rather than hardcoding keys that only some jobs emit.
const statLine = (stats: Record<string, unknown> | null) => {
  if (!stats) return null;
  const parts = Object.entries(stats)
    .filter(([k, v]) => typeof v === "number" && k !== "errors")
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`);
  const errs = typeof stats.errors === "number" && stats.errors > 0 ? `${stats.errors} errors` : null;
  return [...parts, errs].filter(Boolean).join(" · ") || null;
};

export function EtlPanel() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/ingestion/status", { cache: "no-store" }).then((x) => x.json());
      if (r?.ok) setJobs(r.jobs ?? []);
    } catch { /* transient — the next poll covers it */ }
    setLoading(false);
  }, []);

  // Poll fast while something is running, slowly when idle — a 4s job would
  // otherwise finish entirely between two 30s polls and never appear to run.
  useEffect(() => {
    load();
    const tick = () => {
      const busy = jobs.some((j) => j.running) || Object.values(pending).some(Boolean);
      timer.current = setTimeout(() => { load(); tick(); }, busy ? 2000 : 20000);
    };
    tick();
    return () => { if (timer.current) clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, jobs.some((j) => j.running), Object.values(pending).some(Boolean)]);

  const trigger = async (job: Job) => {
    setPending((p) => ({ ...p, [job.id]: true }));
    setNote(null);
    try {
      const r = await fetch("/api/ingestion/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jobId: job.id }),
      }).then((x) => x.json());
      setNote(r?.ok ? `Started ${job.name}` : `${job.name}: ${r?.error ?? "could not start"}`);
      await load();
    } catch {
      setNote(`${job.name}: could not reach the API`);
    } finally {
      setPending((p) => ({ ...p, [job.id]: false }));
    }
  };

  const runAll = async () => {
    for (const j of jobs) if (!j.running) await trigger(j);
  };

  const anyBusy = jobs.some((j) => j.running) || Object.values(pending).some(Boolean);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-xl text-[12px] text-muted">
          Run any ingestion job on demand to check whether stale data is an ingestion
          problem. Jobs run in the background — results and row counts appear below as
          they finish.
        </p>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
            <RefreshCw size={13} className={cn(loading && "animate-spin")} />Refresh
          </Button>
          <Button variant="secondary" size="sm" onClick={runAll} disabled={anyBusy || !jobs.length}>
            <Play size={13} />Run all
          </Button>
        </div>
      </div>

      {note && (
        <div className="rounded-[var(--radius-sm)] bg-void/60 px-3 py-2 text-[12px] text-mist hairline">{note}</div>
      )}

      {loading && !jobs.length && (
        <div className="py-8 text-center text-[12.5px] text-muted">Loading ingestion jobs…</div>
      )}

      <div className="space-y-2">
        {jobs.map((j) => {
          const busy = j.running || pending[j.id];
          const st = j.lastRun?.status;
          const stats = statLine(j.lastRun?.stats ?? null);
          const dur = took(j);
          return (
            <div key={j.id} className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] bg-void/40 p-3.5 hairline">
              <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-[9px]",
                busy ? "bg-accent-soft/60 text-accent"
                  : st === "success" ? "bg-up-soft/60 text-up"
                  : st === "error" ? "bg-down-soft/60 text-down"
                  : "bg-raised text-muted")}>
                {busy ? <Loader2 size={16} className="animate-spin" />
                  : st === "success" ? <Check size={16} />
                  : st === "error" ? <AlertTriangle size={16} />
                  : <Database size={15} />}
              </span>

              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-frost">{j.name}</div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-muted">
                  <span>Last: {j.lastRun ? when(j.lastRun.startedAt) : "never"}{dur ? ` · ${dur}` : ""}</span>
                  <span className="flex items-center gap-1"><Clock size={10} />Next: {when(j.nextRun)}</span>
                </div>
                {stats && <div className="mt-0.5 truncate text-[11.5px] text-mist tnum">{stats}</div>}
                {st === "error" && j.lastRun?.error && (
                  <div className="mt-0.5 line-clamp-2 text-[11.5px] text-down">{j.lastRun.error}</div>
                )}
              </div>

              <Badge tone={busy ? "accent" : st === "success" ? "up" : st === "error" ? "down" : "neutral"}>
                {busy ? "running" : st ?? "idle"}
              </Badge>

              <Button variant="secondary" size="sm" onClick={() => trigger(j)} disabled={busy}>
                {busy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                {busy ? "Running" : "Run now"}
              </Button>
            </div>
          );
        })}
      </div>

      <p className="pt-1 text-[11px] text-muted">
        Read-only ingestion — these jobs refresh market data only. No orders are ever placed.
      </p>
    </div>
  );
}
