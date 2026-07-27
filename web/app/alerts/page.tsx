"use client";
import { useEffect, useState } from "react";
import { Bell, Plus, DollarSign, BarChart3, Sparkles, Newspaper, Activity, Trash2, X, Database, CheckCircle2, XCircle, Loader2, CircleDashed } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Segmented, Avatar, EmptyState, LiveDot } from "@/components/ui/primitives";
import { Alert, Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { timeAgo, timeUntil } from "@/lib/format";
import { cn } from "@/lib/utils";

const ICON = { price: DollarSign, volume: BarChart3, ai: Sparkles, news: Newspaper, technical: Activity };
const STATUS_TONE = { active: "accent", triggered: "up", paused: "neutral" } as const;
const TYPES: Alert["type"][] = ["price", "volume", "technical", "ai", "news"];

type IngestionJob = {
  id: string; name: string; nextRun: string | null;
  lastRun: { startedAt: string; finishedAt: string | null; status: "running" | "success" | "error"; error: string | null } | null;
};
const JOB_STATUS: Record<string, { icon: typeof CheckCircle2; tone: "up" | "down" | "accent" | "neutral"; label: string }> = {
  success: { icon: CheckCircle2, tone: "up", label: "Success" },
  error: { icon: XCircle, tone: "down", label: "Failed" },
  running: { icon: Loader2, tone: "accent", label: "Running" },
};

function IngestionMonitor() {
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => fetch("/api/ingestion/status").then((r) => r.json())
      .then((j) => { if (alive && j?.ok) setJobs(j.jobs ?? []); }).catch(() => {});
    load();
    const id = setInterval(load, 5 * 60 * 1000); // ETL runs on hour/day cadence — no need to poll faster
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (jobs.length === 0) return null;

  return (
    <Card variant="elevated" className="mb-6">
      <CardBody className="pt-5">
        <div className="mb-3 flex items-center gap-2">
          <Database size={15} className="text-accent" />
          <h3 className="text-[14px] font-semibold text-frost">Data Ingestion</h3>
          <span className="text-[11px] text-muted">Symbols · Prices · Fundamentals · Metrics — nightly ETL health</span>
        </div>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {jobs.map((j) => {
            const st = j.lastRun ? JOB_STATUS[j.lastRun.status] : null;
            const Icon = st?.icon ?? CircleDashed;
            return (
              <div key={j.id} className="rounded-[var(--radius-sm)] hairline bg-void p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[12.5px] font-medium text-frost">{j.name}</span>
                  <Badge tone={st?.tone ?? "neutral"}>
                    <Icon size={10} className={cn(j.lastRun?.status === "running" && "animate-spin")} />
                    {st?.label ?? "Never run"}
                  </Badge>
                </div>
                <div className="mt-1.5 flex items-center justify-between text-[11px] text-muted">
                  <span>{j.lastRun ? `Last: ${timeAgo(j.lastRun.finishedAt ?? j.lastRun.startedAt)}` : "No run yet"}</span>
                  <span>{j.nextRun ? `Next: ${timeUntil(j.nextRun)}` : "Not scheduled"}</span>
                </div>
                {j.lastRun?.status === "error" && j.lastRun.error && (
                  <p className="mt-1.5 truncate text-[10.5px] text-down" title={j.lastRun.error}>{j.lastRun.error}</p>
                )}
              </div>
            );
          })}
        </div>
      </CardBody>
    </Card>
  );
}

export default function Alerts() {
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);
  const [filter, setFilter] = useState("all");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [live, setLive] = useState(false);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ symbol: "", type: "price" as Alert["type"], condition: "" });

  const load = async () => {
    try {
      const j = await fetch("/api/alerts").then((r) => r.json());
      if (j?.ok) { setAlerts(j.items); setLive(true); }
    } catch {}
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { if (!form.symbol && universe.length) setForm((f) => ({ ...f, symbol: universe[0].symbol })); }, [universe]);

  const create = async () => {
    if (!form.condition.trim() || !form.symbol) return;
    // optimistic
    const temp: Alert = { id: `tmp-${Date.now()}`, ...form, status: "active", created: new Date().toISOString() };
    setAlerts((a) => [temp, ...a]);
    setOpen(false); setForm((f) => ({ symbol: f.symbol, type: "price", condition: "" }));
    try {
      const r = await fetch("/api/alerts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(temp) }).then((x) => x.json());
      if (r?.ok) load();
    } catch {}
  };

  const remove = async (id: string) => {
    setAlerts((a) => a.filter((x) => x.id !== id));
    try { await fetch(`/api/alerts/${id}`, { method: "DELETE" }); } catch {}
  };

  const rows = alerts.filter((a) => filter === "all" || a.status === filter);
  const counts = { active: alerts.filter((a) => a.status === "active").length, triggered: alerts.filter((a) => a.status === "triggered").length };

  return (
    <div>
      <PageHeader eyebrow="Monitor" title="Alerts"
        description="Price, volume, technical, AI-rating and news triggers — saved and monitored."
        actions={<>{live && <LiveDot />}<Button variant="primary" size="sm" onClick={() => setOpen((v) => !v)}><Plus size={14} />New Alert</Button></>} />

      <IngestionMonitor />

      {/* Create form */}
      {open && (
        <Card variant="elevated" className="mb-5">
          <CardBody className="pt-5">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-[14px] font-semibold text-frost">Create Alert</h3>
              <button onClick={() => setOpen(false)} className="text-muted hover:text-frost" aria-label="Close"><X size={16} /></button>
            </div>
            <div className="grid gap-3 sm:grid-cols-[160px_160px_1fr_auto]">
              <select value={form.symbol} onChange={(e) => setForm((f) => ({ ...f, symbol: e.target.value }))}
                className="h-10 rounded-[var(--radius-sm)] bg-void px-3 text-[13px] text-frost hairline outline-none focus:border-accent/50">
                {universe.map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol}</option>)}
              </select>
              <select value={form.type} onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as Alert["type"] }))}
                className="h-10 rounded-[var(--radius-sm)] bg-void px-3 text-[13px] text-frost hairline outline-none focus:border-accent/50 capitalize">
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <input value={form.condition} onChange={(e) => setForm((f) => ({ ...f, condition: e.target.value }))}
                placeholder="e.g. Price crosses above ₹3,000" onKeyDown={(e) => e.key === "Enter" && create()}
                className="h-10 rounded-[var(--radius-sm)] bg-void px-3 text-[13px] text-frost hairline outline-none focus:border-accent/50" />
              <Button variant="primary" size="md" onClick={create} disabled={!form.condition.trim() || !form.symbol}>Create</Button>
            </div>
          </CardBody>
        </Card>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card className="p-4"><div className="text-[11px] uppercase tracking-wide text-muted">Active</div><div className="mt-1 text-[22px] font-bold text-accent tnum">{counts.active}</div></Card>
        <Card className="p-4"><div className="text-[11px] uppercase tracking-wide text-muted">Triggered</div><div className="mt-1 text-[22px] font-bold text-up tnum">{counts.triggered}</div></Card>
        <Card className="p-4"><div className="text-[11px] uppercase tracking-wide text-muted">Total</div><div className="mt-1 text-[22px] font-bold text-frost tnum">{alerts.length}</div></Card>
        <Card className="p-4"><div className="text-[11px] uppercase tracking-wide text-muted">Symbols</div><div className="mt-1 text-[22px] font-bold text-frost tnum">{new Set(alerts.map((a) => a.symbol)).size}</div></Card>
      </div>

      <div className="mb-4"><Segmented value={filter} onChange={setFilter} options={[
        { label: "All", value: "all" }, { label: "Active", value: "active" },
        { label: "Triggered", value: "triggered" }, { label: "Paused", value: "paused" },
      ]} /></div>

      {rows.length === 0 ? (
        <Card><CardBody><EmptyState icon={<Bell size={22} />} title="No alerts here" description="Create an alert to get notified on price, volume, technical or AI-rating changes." action={<Button variant="primary" size="sm" onClick={() => setOpen(true)}><Plus size={14} />New Alert</Button>} /></CardBody></Card>
      ) : (
        <div className="space-y-2.5">
          {rows.map((a) => { const Icon = ICON[a.type] ?? Bell; return (
            <Card key={a.id} className="flex items-center gap-4 p-4">
              <span className={cn("flex h-10 w-10 items-center justify-center rounded-[10px]",
                a.type === "ai" ? "bg-ai-soft text-ai" : "bg-void text-accent hairline")}><Icon size={17} /></span>
              <Avatar symbol={a.symbol} size={32} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><span className="text-[13px] font-semibold text-frost">{a.symbol}</span><Badge tone="neutral">{a.type}</Badge></div>
                <p className="mt-0.5 text-[12.5px] text-mist">{a.condition}</p>
                <p className="mt-0.5 text-[11px] text-muted">Created {timeAgo(a.created)}</p>
              </div>
              <Badge tone={STATUS_TONE[a.status]}>{a.status}</Badge>
              <button onClick={() => remove(a.id)} className="text-faint transition-colors hover:text-down" aria-label="Delete alert"><Trash2 size={15} /></button>
            </Card>
          ); })}
        </div>
      )}
    </div>
  );
}
