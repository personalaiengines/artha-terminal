"use client";
import { useState } from "react";
import { Layers, Activity } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { Segmented, LiveDot, EmptyState } from "@/components/ui/primitives";
import { HBars } from "@/components/ui/chart";
import { OptionChain } from "@/components/widgets/option-chain";
import { FnoNarrative } from "@/components/widgets/fno-narrative";
import { useApi } from "@/lib/use-api";

// Only index option chains are wired (services/upstox.py FNO_UNDERLYINGS) —
// single-stock options aren't supported by the backend yet.
const UNDERLYINGS = ["NIFTY", "BANKNIFTY", "SENSEX"];

type OCRow = { strike: number; call: { oi: number; oiChg: number; vol: number; iv: number; ltp: number }; put: { oi: number; oiChg: number; vol: number; iv: number; ltp: number } };
type Plan = { ok: boolean; spot: number; atm: number; iv: number; rows: OCRow[]; expiry: string | null };

export default function Options() {
  const [u, setU] = useState("NIFTY");
  const live = useApi<Plan | null>(`/api/fno/${u}`, null, (j) => (j.ok ? j : null));

  const header = (
    <PageHeader eyebrow="Derivatives" title="Options Chain"
      description="Full chain with OI heat and IV skew for the nearest expiry."
      actions={<LiveDot label={live ? "LIVE" : "NO DATA"} />} />
  );

  if (!live) {
    return (
      <div>
        {header}
        <div className="mb-5"><Segmented value={u} onChange={setU} options={UNDERLYINGS.map((v) => ({ label: v, value: v }))} /></div>
        <Card><CardBody><EmptyState icon={<Activity size={22} />} title={`No live option chain for ${u}`}
          description="Upstox may be unauthenticated, outside market hours, or unreachable." /></CardBody></Card>
      </div>
    );
  }

  const { spot, atm, rows, iv } = live;
  const ivSkew = rows.map((r) => ({ name: String(r.strike), value: +(r.call.iv - r.put.iv).toFixed(1), color: r.call.iv >= r.put.iv ? "var(--color-down)" : "var(--color-up)" }));

  return (
    <div>
      {header}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Segmented value={u} onChange={setU} options={UNDERLYINGS.map((v) => ({ label: v, value: v }))} />
        {live.expiry && <span className="ml-auto text-[12px] text-muted">Expiry <span className="font-medium text-frost">{live.expiry}</span></span>}
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card className="p-4"><Stat label="Spot" value={spot} decimals={0} /></Card>
        <Card className="p-4"><Stat label="ATM IV" value={iv} decimals={1} suffix="%" /></Card>
        <Card className="p-4"><Stat label="ATM Strike" value={atm} decimals={0} /></Card>
        <Card className="p-4"><Stat label="Strikes Loaded" value={rows.length} decimals={0} /></Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <h3 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-frost"><Activity size={16} className="text-muted" />{u}{live.expiry ? ` · ${live.expiry}` : ""}</h3>
          <OptionChain spot={spot} seed={u.length} data={{ atm, rows }} />
        </div>
        <div className="space-y-6">
          <FnoNarrative idx={u} />
          <Card>
            <CardHeader icon={<Layers size={16} />} title="IV Skew" subtitle="Call IV − Put IV by strike" />
            <CardBody><HBars data={ivSkew} height={260} fmt={(v) => `${v}%`} /></CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
