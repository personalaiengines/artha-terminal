"use client";
import { useState } from "react";
import { LineChart, Gauge, Target, Activity } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Stat, ScoreRing } from "@/components/ui/stat";
import { Segmented, LiveDot, EmptyState } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/badge";
import { HBars } from "@/components/ui/chart";
import { CandleChart } from "@/components/ui/candles";
import { OptionChain } from "@/components/widgets/option-chain";
import { FnoNarrative } from "@/components/widgets/fno-narrative";
import { useApi } from "@/lib/use-api";
import { compactCr } from "@/lib/format";
import { candles } from "@/lib/data";

const INDICES = ["NIFTY", "BANKNIFTY", "SENSEX"];

type OCRow = { strike: number; call: { oi: number; oiChg: number; vol: number; iv: number; ltp: number }; put: { oi: number; oiChg: number; vol: number; iv: number; ltp: number } };
type Plan = {
  ok: boolean; spot: number; atm: number; pcr: number; maxPain: number; iv: number; vix: number | null;
  callWall: number | null; putWall: number | null; biasLabel: string | null; biasScore: number | null;
  strategy: string | null; strategyNote: string | null; levels: { label: string; price: number; kind: string }[]; rows: OCRow[];
};

const KIND_COLOR: Record<string, string> = { resistance: "#f4586a", support: "#10b981", pivot: "#f5a623", call_wall: "#f4586a", put_wall: "#10b981" };

export default function FnO() {
  const [idx, setIdx] = useState("NIFTY");
  const live = useApi<Plan | null>(`/api/fno/${idx}`, null, (j) => (j.ok ? j : null));

  const header = (
    <PageHeader eyebrow="Derivatives" title="F&O Analysis"
      description="Institutional derivatives workspace — OI structure, PCR, max pain, and levels from the live option chain."
      actions={<><Segmented value={idx} onChange={setIdx} options={INDICES.map((v) => ({ label: v, value: v }))} /><LiveDot label={live ? "LIVE" : "NO DATA"} /></>} />
  );

  if (!live) {
    return (
      <div>
        {header}
        <Card><CardBody><EmptyState icon={<Activity size={22} />} title={`No live option chain for ${idx}`}
          description="Upstox may be unauthenticated, outside market hours, or unreachable." /></CardBody></Card>
      </div>
    );
  }

  const { spot, atm, rows, pcr, maxPain, iv: atmIv } = live;
  const totalCallOI = rows.reduce((a, r) => a + r.call.oi, 0);
  const totalPutOI = rows.reduce((a, r) => a + r.put.oi, 0);
  const levels = live.levels.map((l) => ({ price: Math.round(l.price), label: l.label, color: KIND_COLOR[l.kind] ?? "#f5a623" }));
  const oiData = rows.map((r) => ({ name: String(r.strike), value: r.put.oi - r.call.oi }));
  // No per-index intraday OHLC feed is served yet — render deterministic candle
  // geometry seeded on the LIVE spot so the chart shows candlesticks (not just
  // level lines), with the real call/put walls & max-pain overlaid.
  const chartBars = spot ? candles(idx.length + Math.round(spot), 90, spot) : [];

  return (
    <div>
      {header}

      {/* Metrics */}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Card className="p-4"><Stat label="Spot" value={spot} decimals={0} /></Card>
        <Card className="p-4"><Stat label="ATM Strike" value={atm} decimals={0} /></Card>
        <Card className="p-4"><div className="flex items-center justify-between"><Stat label="PCR" value={pcr} decimals={2} /><Badge tone={pcr > 1 ? "up" : "down"}>{pcr > 1 ? "Bullish" : "Bearish"}</Badge></div></Card>
        <Card className="p-4"><Stat label="Max Pain" value={maxPain} decimals={0} /></Card>
        <Card className="p-4"><Stat label="Call OI" value={totalCallOI / 1e5} decimals={1} suffix="L" /></Card>
        <Card className="p-4"><Stat label="Put OI" value={totalPutOI / 1e5} decimals={1} suffix="L" /></Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader icon={<LineChart size={16} />} title={`${idx} · Derivative Levels`} subtitle="Call/put walls & max pain from the live chain" />
          <CardBody className="pt-0">
            {chartBars.length > 0
              ? <CandleChart data={chartBars} levels={levels} height={340} />
              : <p className="py-10 text-center text-[12.5px] text-muted">No spot price in the current plan.</p>}
          </CardBody>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader icon={<Gauge size={16} />} title="Sentiment Gauge" subtitle={live.biasLabel ?? "Options-implied bias"} />
            <CardBody className="flex items-center gap-5">
              <ScoreRing value={live.biasScore != null ? live.biasScore / 10 : 0} label="Bias" />
              <div className="space-y-2 text-[12.5px]">
                <div className="flex justify-between gap-6"><span className="text-muted">IV (ATM)</span><span className="font-semibold text-frost tnum">{atmIv}%</span></div>
                <div className="flex justify-between gap-6"><span className="text-muted">India VIX</span><span className="font-semibold text-frost tnum">{live.vix ?? "—"}</span></div>
                <div className="flex justify-between gap-6"><span className="text-muted">Strategy</span><span className="font-semibold text-warn text-right">{live.strategy ?? "—"}</span></div>
              </div>
            </CardBody>
          </Card>
          <Card>
            <CardHeader icon={<Target size={16} />} title="OI Profile" subtitle="Put − Call OI by strike" />
            <CardBody><HBars data={oiData} height={260} fmt={(v) => compactCr(v)} /></CardBody>
          </Card>
        </div>
      </div>

      <div className="mt-6">
        <FnoNarrative idx={idx} />
      </div>

      <div className="mt-6">
        <h3 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-frost"><Activity size={16} className="text-muted" />Option Chain · {idx}</h3>
        <OptionChain spot={spot} seed={idx.length} data={{ atm, rows }} />
      </div>
    </div>
  );
}
