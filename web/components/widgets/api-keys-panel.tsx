"use client";

import { useEffect, useState } from "react";
import { Check, AlertCircle, Loader2, Trash2, KeyRound, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Settings → API Keys. The U4 requirement: add, replace and remove any
 * credential from the UI, wired to the real application — .env stops being
 * the only way to supply one.
 *
 * Every key is tested against its real provider (POST /api/auth/test-key)
 * before Save is enabled — same discipline as the registration wizard, same
 * endpoint, so the two can never drift into different validation rules.
 *
 * A saved key is never shown again. The list from /api/auth/me carries
 * provider NAMES only, so "already configured" is the only state this page
 * can render for a stored credential — there is no value to redisplay, by
 * design (see services/auth.py: a key that left the server once is a key
 * that can leak).
 */

type Group = { label: string; providers: { env: string; name: string; note?: string }[] };

const GROUPS: Group[] = [
  {
    label: "Broker",
    providers: [
      { env: "UPSTOX_ANALYTICS_TOKEN", name: "Upstox analytics token", note: "Drives market data · valid ~1yr" },
      { env: "UPSTOX_CLIENT_ID", name: "Upstox client ID" },
      { env: "UPSTOX_CLIENT_SECRET", name: "Upstox client secret" },
    ],
  },
  {
    label: "AI analyst",
    providers: [
      { env: "GROQ_API_KEY", name: "Groq", note: "Fastest — leads the router" },
      { env: "GOOGLE_API_KEY", name: "Gemini" },
      { env: "OPENROUTER_API_KEY", name: "OpenRouter" },
      { env: "NVIDIA_API_KEY", name: "NVIDIA NIM" },
      { env: "SAMBANOVA_API_KEY", name: "SambaNova" },
      { env: "GITHUB_MODELS_TOKEN", name: "GitHub Models" },
      { env: "ANTHROPIC_API_KEY", name: "Anthropic", note: "Paid, opt-in" },
    ],
  },
  {
    label: "News & search",
    providers: [
      { env: "FINNHUB_API_KEY", name: "Finnhub" },
      { env: "SERPAPI_KEY", name: "SerpAPI" },
      { env: "JINA_API_KEY", name: "Jina" },
      { env: "SEARXNG_URL", name: "SearxNG URL" },
    ],
  },
];

type Verdict = { state: "idle" | "busy" | "ok" | "bad"; msg?: string };

function KeyRow({ env, name, note, stored, onChanged }: {
  env: string; name: string; note?: string; stored: boolean; onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [value, setValue] = useState("");
  const [verdict, setVerdict] = useState<Verdict>({ state: "idle" });
  const [busy, setBusy] = useState(false);

  async function test() {
    if (!value.trim()) return setVerdict({ state: "bad", msg: "Enter a key first" });
    setVerdict({ state: "busy", msg: "Calling the provider…" });
    try {
      const res = await fetch("/api/auth/test-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: env, key: value.trim() }),
      });
      const b = await res.json().catch(() => null);
      setVerdict(b?.ok ? { state: "ok", msg: b.detail ?? "Verified" }
                        : { state: "bad", msg: b?.error ?? b?.detail ?? "Rejected" });
    } catch {
      setVerdict({ state: "bad", msg: "Could not reach the terminal" });
    }
  }

  async function save() {
    setBusy(true);
    try {
      const res = await fetch("/api/auth/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: env, key: value.trim() }),
      });
      if ((await res.json().catch(() => null))?.ok) {
        setValue("");
        setVerdict({ state: "idle" });
        setExpanded(false);
        onChanged();
      }
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      const res = await fetch(`/api/auth/keys/${env}`, { method: "DELETE" });
      if ((await res.json().catch(() => null))?.ok) onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-[var(--radius-md)] bg-void/40 hairline">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 p-3.5 text-left"
      >
        <span className={`flex h-8 w-8 items-center justify-center rounded-[8px] ${stored ? "bg-up-soft/60 text-up" : "bg-line/60 text-faint"}`}>
          {stored ? <Check size={14} /> : <KeyRound size={14} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium text-frost">{name}</div>
          <div className="text-[11.5px] text-muted">
            {stored ? "Configured" : "Not set"}{note ? ` · ${note}` : ""}
          </div>
        </div>
        <ChevronDown size={15} className={`text-faint transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="border-t border-line/60 p-3.5">
          {stored && (
            <div className="mb-3 flex items-center justify-between rounded-[var(--radius-sm)] bg-void px-3 py-2 text-[12px] text-muted">
              <span>A key is already stored for this provider. Saving a new one replaces it.</span>
              <button
                onClick={remove}
                disabled={busy}
                className="flex shrink-0 items-center gap-1.5 text-down hover:underline"
              >
                <Trash2 size={12} />Remove
              </button>
            </div>
          )}
          <div className="flex gap-2">
            <input
              value={value}
              onChange={(e) => { setValue(e.target.value); setVerdict({ state: "idle" }); }}
              placeholder={stored ? "Paste a new value to replace it" : "Paste key"}
              className="h-10 flex-1 rounded-[var(--radius-sm)] bg-void px-3 font-mono text-[12.5px] text-frost hairline outline-none focus:border-accent/50"
            />
            <Button variant="secondary" size="sm" onClick={test} disabled={verdict.state === "busy"}>
              Test
            </Button>
            <Button variant="primary" size="sm" onClick={save} disabled={verdict.state !== "ok" || busy}>
              Save
            </Button>
          </div>
          {verdict.state !== "idle" && (
            <div className={`mt-2 flex items-center gap-2 font-mono text-[11.5px] ${
              verdict.state === "ok" ? "text-up" : verdict.state === "bad" ? "text-down" : "text-muted"
            }`}>
              {verdict.state === "busy" && <Loader2 size={12} className="animate-spin" />}
              {verdict.state === "ok" && <Check size={12} />}
              {verdict.state === "bad" && <AlertCircle size={12} />}
              <span>{verdict.msg}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ApiKeysPanel() {
  const [stored, setStored] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);

  function refresh() {
    fetch("/api/auth/me", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.ok) setStored(new Set(d.keys ?? [])); })
      .finally(() => setLoaded(true));
  }
  useEffect(refresh, []);

  return (
    <div className="space-y-6">
      <p className="text-[12.5px] leading-relaxed text-muted">
        Every key is tested against its real provider before it is saved. Once saved, a
        key never travels back to your browser — this page can only tell you a credential
        is configured, never show it again.
      </p>
      {loaded && GROUPS.map((g) => (
        <div key={g.label}>
          <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-faint">
            {g.label}
          </div>
          <div className="space-y-2">
            {g.providers.map((p) => (
              <KeyRow key={p.env} {...p} stored={stored.has(p.env)} onChanged={refresh} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
