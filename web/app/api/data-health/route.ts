import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// What is not live right now, and what is being served instead. Read by the
// global banner and the Data Health card on the Alerts page.
export const dynamic = "force-dynamic";

export async function GET() {
  const h = await fromApi<{ live: boolean; issues: any[]; checked_ist: string }>(
    "/api/data-health", 8000
  );
  // A failed call is itself a liveness problem — say so rather than implying
  // everything is fine.
  if (!h) {
    return NextResponse.json({
      ok: true,
      live: false,
      issues: [{
        source: "api",
        severity: "error",
        title: "Cannot reach the ARTHA API",
        detail: "Nothing on screen is refreshing; every value is whatever the page last loaded.",
        lastGood: null,
        fix: "Check that the artha-api container is running.",
      }],
      checkedIst: null,
    });
  }

  return NextResponse.json({
    ok: true,
    live: !!h.live,
    issues: (h.issues ?? []).map((i) => ({
      source: i.source,
      severity: i.severity,
      title: i.title,
      detail: i.detail,
      lastGood: i.last_good ?? null,
      fix: i.fix ?? null,
    })),
    checkedIst: h.checked_ist ?? null,
  });
}
