"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, AlertTriangle, Loader2, KeyRound } from "lucide-react";
import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

// Upstox OAuth landing page (redirect_uri = /upstox/callback). Auto-exchanges
// the ?code=… for a fresh daily token, then bounces to the dashboard. Lands in
// ARTHA, never the old Streamlit app.
function Callback() {
  const sp = useSearchParams();
  const router = useRouter();
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("Exchanging authorization code…");

  useEffect(() => {
    const code = sp.get("code");
    if (!code) { setState("error"); setMessage("No authorization code found in the URL."); return; }
    fetch("/api/upstox/token", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    })
      .then((r) => r.json())
      .then((r) => {
        if (r?.ok) {
          setState("ok"); setMessage("Upstox authorized — live data is back online.");
          setTimeout(() => router.push("/"), 1800);
        } else {
          setState("error"); setMessage(r?.message ?? "Upstox rejected the code.");
        }
      })
      .catch(() => { setState("error"); setMessage("Could not reach the API."); });
  }, [sp, router]);

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-md items-center justify-center">
      <Card variant="elevated" className="w-full">
        <CardBody className="flex flex-col items-center gap-4 py-10 text-center">
          <span className={`flex h-14 w-14 items-center justify-center rounded-[var(--radius-lg)] hairline ${
            state === "ok" ? "bg-up-soft/50 text-up" : state === "error" ? "bg-down-soft/50 text-down" : "bg-elevated text-accent"}`}>
            {state === "working" ? <Loader2 size={24} className="animate-spin" /> : state === "ok" ? <CheckCircle2 size={24} /> : <AlertTriangle size={24} />}
          </span>
          <div>
            <h1 className="text-[17px] font-semibold text-frost">
              {state === "ok" ? "Authorized" : state === "error" ? "Authorization failed" : "Authorizing Upstox"}
            </h1>
            <p className="mt-1.5 text-[13px] text-muted">{message}</p>
          </div>
          {state === "error" && (
            <div className="flex gap-2">
              <Link href="/"><Button variant="secondary" size="sm">Dashboard</Button></Link>
              <Link href="/settings"><Button variant="primary" size="sm"><KeyRound size={13} />Retry in Settings</Button></Link>
            </div>
          )}
          {state === "ok" && <Link href="/"><Button variant="primary" size="sm">Go to Dashboard</Button></Link>}
        </CardBody>
      </Card>
    </div>
  );
}

export default function UpstoxCallbackPage() {
  return (
    <Suspense fallback={<div className="py-20 text-center text-muted">Loading…</div>}>
      <Callback />
    </Suspense>
  );
}
