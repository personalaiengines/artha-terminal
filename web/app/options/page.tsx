"use client";
import { useState } from "react";
import { Activity, Sigma } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { Segmented, LiveDot, EmptyState } from "@/components/ui/primitives";
import { HBars } from "@/components/ui/chart";
import { OptionChain, ChainLegend, type OCRow } from "@/components/widgets/option-chain";
import { IvSmile, IvTerm, type Term } from "@/components/widgets/iv-curves";
import { Payoff, type ConceptLeg } from "@/components/widgets/payoff";
import { FnoNarrative } from "@/components/widgets/fno-narrative";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { compactCr } from "@/lib/format";

// Only index option chains are wired (services/upstox.py FNO_UNDERLYINGS) —
// single-stock options aren't supported by the backend yet.
const UNDERLYINGS = ["NIFTY", "BANKNIFTY", "SENSEX"];

type Plan = {
  ok: boolean; spot: number; atm: number | null; iv: number | null;
  pcr: number | null; maxPain: number | null;
  rows: OCRow[]; expiry: string | null; expiries: string[];
  deltaOi: { call: number | null; put: number | null; legs_without_greeks: number } | null;
  buildupBasis: string | null;
  strategy: string | null; strategyNote: string | null;
  strategyAnchors: Record<string, number | null> | null; strategyLegs: ConceptLeg[];
};

export default function Options() {
  const [u, setU] = useState("NIFTY");
  // null = whatever the API picks as nearest. A selected expiry is a query
  // param on the same endpoint, so the whole plan recomputes for it.
  const [exp, setExp] = useState<string | null>(null);
  const live = useApi<Plan | null>(
    `/api/fno/${u}${exp ? `?expiry=${encodeURIComponent(exp)}` : ""}`,
    null, (j) => (j.ok ? j : null), POLL.fno);
  const term = useApi<Term>(`/api/fno/${u}/term`, {}, (j) => j, POLL.history);

  const switchIndex = (v: string) => { setU(v); setExp(null); };   // expiries differ per index

  const header = (
    <PageHeader eyebrow="Derivatives" title="Options Chain"
      description="Strike microstructure — the full chain, the IV surface and delta-weighted OI for any listed expiry."
      actions={<LiveDot label={live ? "LIVE" : "NO DATA"} />} />
  );

  if (!live) {
    return (
      <div>
        {header}
        <div className="mb-5"><Segmented value={u} onChange={switchIndex} options={UNDERLYINGS.map((v) => ({ label: v, value: v }))} /></div>
        <Card><CardBody><EmptyState icon={<Activity size={22} />} title={`No live option chain for ${u}`}
          description="Upstox may be unauthenticated, outside market hours, or unreachable." /></CardBody></Card>
      </div>
    );
  }

  const { spot, atm, rows, iv, deltaOi } = live;
  const expiries = live.expiries ?? [];
  // `live.expiry` is what the API actually priced. When it disagrees with the
  // selection, the selected expiry returned nothing and this is the previous
  // one — say so rather than labelling old strikes with the new date.
  const stale = exp !== null && live.expiry !== exp;

  // Delta ladder (R10): |delta| × OI per strike, per side. A leg whose greek
  // came back absent is EXCLUDED, never counted as delta 0 — the exclusions are
  // printed under the chart.
  const weight = (l: OCRow["call"]) => (l.delta == null ? null : Math.abs(l.delta) * l.oi);
  const top = [...rows]
    .sort((a, b) => Math.max(weight(b.call) ?? 0, weight(b.put) ?? 0) - Math.max(weight(a.call) ?? 0, weight(a.put) ?? 0))
    .slice(0, 10)
    .sort((a, b) => b.strike - a.strike);
  const ladder = (side: "call" | "put") => top
    .filter((r) => weight(r[side]) != null)
    .map((r) => ({ name: String(r.strike), value: Math.round(weight(r[side]) as number), color: side === "call" ? "var(--color-down)" : "var(--color-up)" }));

  return (
    <div>
      {header}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Segmented value={u} onChange={switchIndex} options={UNDERLYINGS.map((v) => ({ label: v, value: v }))} />
        <label className="ml-auto flex items-center gap-2 text-[12px] text-muted">
          Expiry
          <select value={live.expiry ?? ""} onChange={(e) => setExp(e.target.value)}
            className="rounded-[var(--radius-sm)] bg-void px-2 py-1 text-[12px] font-medium text-frost hairline tnum outline-none focus:ring-1 focus:ring-accent">
            {(expiries.length ? expiries : [live.expiry ?? ""]).map((d) => (
              <option key={d} value={d} className="bg-void">{d}</option>
            ))}
          </select>
          <span className="text-faint">{expiries.length} listed</span>
        </label>
      </div>

      {stale && (
        <p className="mb-4 text-[12px] text-warn">
          {exp} returned no priced chain. Everything below is {live.expiry ?? "the nearest expiry"} — no strike here belongs to {exp}.
        </p>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Card className="p-4"><Stat label="Spot" value={spot} decimals={0} /></Card>
        <Card className="p-4"><Stat label="ATM IV" value={iv} decimals={1} suffix="%" /></Card>
        <Card className="p-4"><Stat label="ATM Strike" value={atm} decimals={0} /></Card>
        <Card className="p-4"><Stat label="PCR (OI)" value={live.pcr} decimals={2} /></Card>
        <Card className="p-4"><Stat label="Strikes Loaded" value={rows.length} decimals={0} /></Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <div>
            <h3 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-frost">
              <Activity size={16} className="text-muted" />{u}{live.expiry ? ` · ${live.expiry}` : ""}
            </h3>
            <OptionChain spot={spot} data={{ atm, rows }} />
            <ChainLegend basis={live.buildupBasis} />
          </div>

          <Card>
            <CardHeader icon={<Sigma size={16} />} title="Delta-Weighted OI"
              subtitle="|Δ| × OI per strike — the exposure behind the open interest, not the contract count" />
            <CardBody>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-down">Calls · total {compactCr(deltaOi?.call)}</p>
                  {ladder("call").length
                    ? <HBars data={ladder("call")} height={220} fmt={(v) => compactCr(v)} />
                    : <p className="py-8 text-center text-[12px] text-muted">No call leg here carries a live delta.</p>}
                </div>
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-up">Puts · total {compactCr(deltaOi?.put)}</p>
                  {ladder("put").length
                    ? <HBars data={ladder("put")} height={220} fmt={(v) => compactCr(v)} />
                    : <p className="py-8 text-center text-[12px] text-muted">No put leg here carries a live delta.</p>}
                </div>
              </div>
              <p className="mt-2 text-[11px] text-muted">
                Top 10 strikes by exposure.{" "}
                {deltaOi?.legs_without_greeks
                  ? `${deltaOi.legs_without_greeks} legs without live greeks are excluded from both bars and both totals.`
                  : "Every leg in this chain carries a live delta."}
              </p>
            </CardBody>
          </Card>
        </div>

        <div className="space-y-6">
          <FnoNarrative idx={u} source="microstructure" />
          <IvSmile rows={rows} spot={spot} expiry={live.expiry} />
          <IvTerm term={term} listed={expiries.length} />
          <Payoff concept={{ name: live.strategy, note: live.strategyNote, anchors: live.strategyAnchors, legs: live.strategyLegs ?? [] }}
            rows={rows} spot={spot} />
        </div>
      </div>
    </div>
  );
}
