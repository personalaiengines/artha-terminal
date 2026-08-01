import { NextResponse } from "next/server";
import { sendApi } from "@/lib/api-server";

// Ad-hoc ETL trigger from the Settings page. The Python side queues the job and
// returns immediately (runs range from ~4s to several minutes), so this only
// needs a short timeout — progress is read back from /api/ingestion/status.
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const jobId = (body?.jobId ?? body?.job_id ?? "").toString().trim();
  if (!jobId) return NextResponse.json({ ok: false, error: "jobId required" }, { status: 400 });

  const res = await sendApi<any>("/api/ingestion/run", "POST", { job_id: jobId }, 15000);
  if (!res) return NextResponse.json({ ok: false, error: "api unreachable" }, { status: 502 });
  return NextResponse.json(res, { status: res.ok === false ? 409 : 200 });
}
