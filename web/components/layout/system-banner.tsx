"use client";
import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ExternalLink, KeyRound, X, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDataHealth } from "@/components/widgets/data-health";
import Link from "next/link";

type Status = {
  upstox: { status: string; loginUrl: string | null; name: string | null };
  llm: { openrouter: boolean; nvidia: boolean };
};

// Global health banner. Polls /api/system/status; when Upstox auth is expired or
// missing (or no LLM key exists) it shows an amber bar on EVERY page with a
// one-click authorize flow — no digging into Settings.
export function SystemBanner() {
  const [status, setStatus] = useState<Status | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [modal, setModal] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const load = useCallback(() => {
    fetch("/api/system/status").then((r) => r.json())
      .then((j) => { if (j?.ok) setStatus(j); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5 * 60 * 1000); // re-check every 5 min
    // Any page (e.g. Settings "Reconnect") can open the authorize modal, even
    // when the token is still valid, by dispatching this event.
    const open = () => { load(); setModal(true); };
    window.addEventListener("artha:authorize", open);
    return () => { clearInterval(id); window.removeEventListener("artha:authorize", open); };
  }, [load]);

  // Any feed serving last-known-good instead of live data. Surfaced here as
  // well as on the Alerts page so a stale number is never read as a live one.
  const health = useDataHealth();
  const staleIssue = health.issues.find((i) => !i.source.startsWith("upstox_portfolio"));

  const upstoxBad = status && ["expired", "missing", "error"].includes(status.upstox.status);
  const llmBad = status && !status.llm.openrouter && !status.llm.nvidia;
  const show = !dismissed && (upstoxBad || llmBad || !!staleIssue);

  const submit = async () => {
    if (!code.trim() || busy) return;
    setBusy(true); setResult(null);
    try {
      const r = await fetch("/api/upstox/token", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      }).then((x) => x.json());
      setResult({ ok: !!r.ok, message: r.message ?? (r.ok ? "Token saved." : "Failed.") });
      if (r.ok) {
        setCode("");
        // Re-read status immediately (the API dropped its Upstox caches on a
        // successful exchange) and pull every other hook forward, so the
        // banner can't keep announcing "expired" after a token that worked.
        load();
        window.dispatchEvent(new Event("artha:refresh"));
        setTimeout(() => { setModal(false); setResult(null); load(); }, 1400);
      }
    } catch {
      setResult({ ok: false, message: "Network error — is the API container running?" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <AnimatePresence>
        {show && (
          <motion.div
            initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-b border-warn/30 bg-warn-soft/40"
          >
            <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-3 px-4 py-2 md:px-6">
              <AlertTriangle size={15} className="shrink-0 text-warn" />
              <span className="text-[12.5px] font-medium text-frost">
                {upstoxBad
                  ? <>Upstox daily authorization {status!.upstox.status === "missing" ? "is not set up" : "has expired"} — live quotes, holdings and option chains are degraded.</>
                  : llmBad
                  ? <>No LLM API key configured — AI analysis is running on canned fallbacks.</>
                  : <>{staleIssue!.title} — showing the last known-good data until it recovers.</>}
              </span>
              {!upstoxBad && staleIssue && (
                <Link href="/alerts" className="text-[12px] font-medium text-warn underline underline-offset-2 hover:text-frost">
                  What's affected
                </Link>
              )}
              {upstoxBad && (
                <Button size="sm" variant="secondary" className="!h-7 border-warn/40 text-warn" onClick={() => setModal(true)}>
                  <KeyRound size={13} /> Authorize now
                </Button>
              )}
              <button onClick={() => setDismissed(true)} aria-label="Dismiss"
                className="ml-auto text-muted transition-colors hover:text-frost"><X size={15} /></button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Authorize modal */}
      <AnimatePresence>
        {modal && (
          <motion.div className="fixed inset-0 z-[110] flex items-center justify-center p-4"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="absolute inset-0 bg-abyss/70 backdrop-blur-sm" onClick={() => setModal(false)} />
            <motion.div
              initial={{ scale: 0.97, y: 8 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.97, y: 8 }}
              className="relative w-full max-w-lg rounded-[var(--radius-lg)] glass hairline-strong p-6 shadow-[var(--shadow-lg)]"
            >
              <div className="mb-1 flex items-center gap-2">
                <KeyRound size={17} className="text-warn" />
                <h2 className="text-[16px] font-semibold text-frost">Authorize Upstox</h2>
                <button onClick={() => setModal(false)} aria-label="Close" className="ml-auto text-muted hover:text-frost"><X size={16} /></button>
              </div>
              <p className="text-[12.5px] leading-relaxed text-muted">
                Upstox tokens expire daily (~03:30 IST). Two steps, ~20 seconds:
              </p>
              <ol className="mt-3 space-y-3 text-[13px] text-mist">
                <li className="flex gap-2.5">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-raised text-[11px] font-bold text-frost">1</span>
                  <span>
                    Log in to Upstox in a new tab.{" "}
                    {status?.upstox.loginUrl && (
                      <a href={status.upstox.loginUrl} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                        Open Upstox login <ExternalLink size={12} />
                      </a>
                    )}
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-raised text-[11px] font-bold text-frost">2</span>
                  <span>Upstox redirects back to ARTHA, which exchanges the code and finishes on its own — nothing to paste. Only if that page fails to load, copy the <b>whole URL</b> from the address bar into the box below.</span>
                </li>
              </ol>
              <div className="mt-4 flex gap-2">
                <input
                  value={code} onChange={(e) => setCode(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submit()}
                  placeholder="Paste redirect URL or code…"
                  className="h-10 flex-1 rounded-[var(--radius-sm)] bg-void px-3 text-[13px] text-frost hairline outline-none focus:border-accent/50"
                />
                <Button variant="primary" onClick={submit} disabled={!code.trim() || busy}>
                  {busy ? <Loader2 size={15} className="animate-spin" /> : "Save token"}
                </Button>
              </div>
              {result && (
                <div className={`mt-3 flex items-center gap-2 text-[12.5px] ${result.ok ? "text-up" : "text-down"}`}>
                  {result.ok ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />} {result.message}
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
