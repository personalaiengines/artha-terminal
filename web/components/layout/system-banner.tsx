"use client";
import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ExternalLink, KeyRound, X, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

type Status = {
  upstox: { status: string; login_url: string | null; name: string | null };
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

  const upstoxBad = status && ["expired", "missing", "error"].includes(status.upstox.status);
  const llmBad = status && !status.llm.openrouter && !status.llm.nvidia;
  const show = !dismissed && (upstoxBad || llmBad);

  const submit = async () => {
    if (!code.trim() || busy) return;
    setBusy(true); setResult(null);
    try {
      const r = await fetch("/api/upstox/token", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      }).then((x) => x.json());
      setResult({ ok: !!r.ok, message: r.message ?? (r.ok ? "Token saved." : "Failed.") });
      if (r.ok) { setCode(""); setTimeout(() => { setModal(false); setResult(null); load(); }, 1400); }
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
                  : <>No LLM API key configured — AI analysis is running on canned fallbacks.</>}
              </span>
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
                    {status?.upstox.login_url && (
                      <a href={status.upstox.login_url} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                        Open Upstox login <ExternalLink size={12} />
                      </a>
                    )}
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-raised text-[11px] font-bold text-frost">2</span>
                  <span>After login the browser redirects to a URL containing <code className="rounded bg-void px-1 text-[11px]">?code=…</code>. The page may show <i>“can’t connect”</i> — that’s expected; the code is still in the address bar. Copy the <b>whole URL</b> (or just the code) and paste it below.</span>
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
