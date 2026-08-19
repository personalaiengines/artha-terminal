"use client";
import { useEffect, useState } from "react";
import { User, Plug, Palette, Bell, ShieldCheck, Check, AlertTriangle, KeyRound, Database, LogOut } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, Divider } from "@/components/ui/primitives";
import { EtlPanel } from "@/components/widgets/etl-panel";
import { ApiKeysPanel } from "@/components/widgets/api-keys-panel";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { cn } from "@/lib/utils";

type Me = { email: string; created_at: string; last_login_at: string | null };

type SysStatus = {
  upstox: { status: string; name: string | null; loginUrl: string | null; savedAt?: string | null };
  llm: { openrouter: boolean; nvidia: boolean };
};
const authorize = () => window.dispatchEvent(new Event("artha:authorize"));

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button onClick={() => onChange(!on)} role="switch" aria-checked={on}
      className={cn("relative h-6 w-11 rounded-full transition-colors ring-focus", on ? "bg-accent" : "bg-line")}>
      <span className={cn("absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform", on ? "translate-x-[22px]" : "translate-x-0.5")} />
    </button>
  );
}

function Row({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line/50 py-3.5 last:border-0">
      <div><div className="text-[13.5px] font-medium text-frost">{title}</div><div className="text-[12px] text-muted">{desc}</div></div>
      {children}
    </div>
  );
}

export default function Settings() {
  const [prefs, setPrefs] = useState({ reduceMotion: false, priceAlerts: true, aiAlerts: true, newsDigest: true, sound: false });
  const set = (k: keyof typeof prefs) => (v: boolean) => setPrefs((p) => ({ ...p, [k]: v }));

  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    fetch("/api/auth/me", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.ok) setMe(d.user); })
      .catch(() => {});
  }, []);

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }

  const sys = useApi<SysStatus | null>("/api/system/status", null, (j) => j as SysStatus, POLL.systemStatus);
  const upStatus = sys?.upstox.status ?? "unknown";
  const upOk = upStatus === "ok" || upStatus === "connected";
  const savedDate = sys?.upstox.savedAt ? new Date(sys.upstox.savedAt).toLocaleString("en-IN") : null;
  // Live connection rows built from the real /api/system/status payload.
  const CONNECTIONS = [
    { key: "upstox", name: "Upstox (Market Data & Holdings)", ok: upOk, canAuth: true,
      detail: upOk ? `Token valid${sys?.upstox.name ? ` · ${sys.upstox.name}` : ""}${savedDate ? ` · saved ${savedDate}` : ""}` : "Daily token expired or missing — click Reconnect" },
    { key: "openrouter", name: "OpenRouter (AI · primary)", ok: !!sys?.llm.openrouter, canAuth: false,
      detail: sys?.llm.openrouter ? "API key configured" : "No key — using NIM fallback" },
    { key: "nvidia", name: "NVIDIA NIM (AI · fallback)", ok: !!sys?.llm.nvidia, canAuth: false,
      detail: sys?.llm.nvidia ? "API key configured" : "No key configured" },
  ];

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader eyebrow="System" title="Settings"
        description="Manage your profile, data connections, appearance and notifications." />

      <Card>
        <CardBody className="pt-5">
          <Tabs tabs={[
            { id: "profile", label: "Profile", icon: <User size={14} /> },
            { id: "keys", label: "API Keys", icon: <KeyRound size={14} /> },
            { id: "conn", label: "Connections", icon: <Plug size={14} /> },
            { id: "data", label: "Data & Ingestion", icon: <Database size={14} /> },
            { id: "appear", label: "Appearance", icon: <Palette size={14} /> },
            { id: "notify", label: "Notifications", icon: <Bell size={14} /> },
            { id: "comp", label: "Compliance", icon: <ShieldCheck size={14} /> },
          ]}>
            {(active) => (
              <>
                {active === "profile" && (
                  <div className="max-w-md space-y-4">
                    <div className="flex items-center gap-4">
                      <div className="h-16 w-16 rounded-full bg-gradient-to-br from-accent to-ai" />
                      <div>
                        <div className="text-[15px] font-semibold text-frost">{me?.email ?? "…"}</div>
                        <div className="text-[12px] text-muted">
                          {me?.created_at ? `Member since ${new Date(me.created_at).toLocaleDateString("en-IN")}` : ""}
                        </div>
                      </div>
                    </div>
                    <Divider />
                    <label className="block"><span className="text-[12px] font-medium text-muted">Base currency</span>
                      <input defaultValue="INR (₹)" disabled className="mt-1.5 h-10 w-full rounded-[var(--radius-sm)] bg-void px-3 text-[13px] text-muted hairline outline-none" /></label>
                    <Divider />
                    <div>
                      <div className="text-[12.5px] font-medium text-frost">Session</div>
                      <p className="mt-1 text-[11.5px] leading-relaxed text-muted">
                        Signing out revokes this session on the server immediately — it does
                        not simply expire client-side.
                      </p>
                      <Button variant="secondary" size="sm" className="mt-2.5" onClick={signOut}>
                        <LogOut size={13} />Sign out
                      </Button>
                    </div>
                  </div>
                )}

                {active === "keys" && <ApiKeysPanel />}

                {active === "conn" && (
                  <div className="space-y-2.5">
                    {CONNECTIONS.map((c) => (
                      <div key={c.key} className="flex items-center gap-3 rounded-[var(--radius-md)] bg-void/40 p-3.5 hairline">
                        <span className={cn("flex h-9 w-9 items-center justify-center rounded-[9px]", c.ok ? "bg-up-soft/60 text-up" : "bg-warn-soft/60 text-warn")}>
                          {c.ok ? <Check size={16} /> : <AlertTriangle size={16} />}
                        </span>
                        <div className="min-w-0 flex-1"><div className="text-[13px] font-medium text-frost">{c.name}</div><div className="text-[11.5px] text-muted">{c.detail}</div></div>
                        <Badge tone={c.ok ? "up" : "warn"}>{c.ok ? "connected" : "action needed"}</Badge>
                        {c.canAuth && (
                          <Button variant={c.ok ? "secondary" : "primary"} size="sm" onClick={authorize}>
                            <KeyRound size={13} />{c.ok ? "Re-authorize" : "Reconnect"}
                          </Button>
                        )}
                      </div>
                    ))}
                    <p className="pt-1 text-[11px] text-muted">
                      This shows what is live right now. Add or replace a credential under
                      the <b className="text-mist">API Keys</b> tab — it takes effect on the
                      next request, no restart. Upstox holdings token expires daily (~03:30 IST).
                    </p>
                  </div>
                )}

                {active === "data" && <EtlPanel />}

                {active === "appear" && (
                  <div className="max-w-lg">
                    <Row title="Theme" desc="ARTHA is optimised for dark, low-fatigue trading sessions"><Badge tone="accent">Dark (default)</Badge></Row>
                    <Row title="Reduce motion" desc="Minimise animations and transitions"><Toggle on={prefs.reduceMotion} onChange={set("reduceMotion")} /></Row>
                    <Row title="Density" desc="Table row spacing"><Badge tone="neutral">Comfortable</Badge></Row>
                    <Row title="Number format" desc="Indian lakh/crore grouping"><Badge tone="neutral">₹ 1,00,000</Badge></Row>
                  </div>
                )}

                {active === "notify" && (
                  <div className="max-w-lg">
                    <Row title="Price alerts" desc="Notify when price thresholds are crossed"><Toggle on={prefs.priceAlerts} onChange={set("priceAlerts")} /></Row>
                    <Row title="AI rating changes" desc="When ARTHA upgrades or downgrades a holding"><Toggle on={prefs.aiAlerts} onChange={set("aiAlerts")} /></Row>
                    <Row title="Morning digest" desc="Daily AI market brief before open"><Toggle on={prefs.newsDigest} onChange={set("newsDigest")} /></Row>
                    <Row title="Alert sound" desc="Play a sound on triggered alerts"><Toggle on={prefs.sound} onChange={set("sound")} /></Row>
                  </div>
                )}

                {active === "comp" && (
                  <div className="max-w-2xl space-y-4">
                    <div className="rounded-[var(--radius-md)] bg-void/40 p-4 hairline">
                      <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-frost"><ShieldCheck size={15} className="text-up" />SEBI Compliance</div>
                      <p className="text-[12.5px] leading-relaxed text-muted">
                        ARTHA Terminal is for research and educational purposes only. The AI Score (0–10) is NOT a buy/sell recommendation.
                        Broker integration is read-only — no orders are ever placed. All data is sourced from public APIs and disclosures.
                        Consult a SEBI-registered investment advisor before making investment decisions.
                      </p>
                    </div>
                    <Row title="Read-only broker" desc="Order-placement APIs are never wired"><Badge tone="up">Enforced</Badge></Row>
                    <Row title="Persistent disclaimers" desc="Shown on all analytical views"><Badge tone="up">On</Badge></Row>
                  </div>
                )}
              </>
            )}
          </Tabs>
        </CardBody>
      </Card>
    </div>
  );
}
