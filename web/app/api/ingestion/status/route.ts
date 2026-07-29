import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Ingestion job monitor for the Alerts page: last run (status/stats/error)
// and next scheduled run per ETL job.
export async function GET() {
  const s = await fromApi<{ jobs: any[] }>("/api/ingestion/status", 8000);
  if (!s) return NextResponse.json({ ok: false, jobs: [] });
  const jobs = (s.jobs ?? []).map((j) => ({
    id: j.id,
    name: j.name,
    running: !!j.running,
    nextRun: j.next_run ?? null,
    lastRun: j.last_run ? {
      startedAt: j.last_run.started_at,
      finishedAt: j.last_run.finished_at ?? null,
      status: j.last_run.status as "running" | "success" | "error",
      error: j.last_run.error ?? null,
      // Row counts etc. — the whole point of an ad-hoc run is seeing what it did.
      stats: j.last_run.stats ?? null,
    } : null,
  }));
  return NextResponse.json({ ok: true, jobs });
}
