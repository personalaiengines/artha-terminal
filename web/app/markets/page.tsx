"use client";
import { useRouter } from "next/navigation";
import { TrendingUp, TrendingDown, Activity, Gauge, Globe2, ArrowRightLeft } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { DeltaPill } from "@/components/ui/stat";
import { Sparkline } from "@/components/ui/sparkline";
import { LiveDot, Avatar } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/badge";
import { StockRow } from "@/components/widgets/stock-row";
import { series, Stock } from "@/lib/data";
import { moversFrom } from "@/lib/portfolio";
import { useApi } from "@/lib/use-api";
import { pct, trendClass, compactCr, inr, signed } from "@/lib/format";
import { cn } from "@/lib/utils";

// Sector heatmap aggregated from the (live) stock universe.
function sectors(stocks: Stock[]) {
  const map = new Map<string, { sum: number; n: number }>();
  stocks.forEach((s) => { const e = map.get(s.sector) ?? { sum: 0, n: 0 }; e.sum += s.changePct; e.n++; map.set(s.sector, e); });
  return [...map.entries()].map(([name, { sum, n }]) => ({ name, chg: sum / n, weight: n })).sort((a, b) => b.chg - a.chg);
}

type Pulse = { breadth?: { advancing: number; declining: number; total: number; pct: number }; sectors?: { name: string; chg: number; count: number }[] };

type Flows = { fiiNet: number | null; diiNet: number | null; fiiStance: string | null; diiStance: string | null; date: string | null };
type GlobalRow = { name: string; price: number | null; changePct: number | null; unit: string | null };

export default function Markets() {
  const router = useRouter();
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);
  const pulse = useApi<Pulse | null>("/api/pulse", null, (j) => j);
  const liveMovers = useApi<{ gainers: Stock[]; losers: Stock[]; volume: Stock[] } | null>("/api/movers", null, (j) => (j.ok ? j : null));
  const flows = useApi<Flows | null>("/api/flows", null, (j) => (j.ok ? j : null));
  const globalBoard = useApi<{ indices: GlobalRow[]; commodities: GlobalRow[] } | null>("/api/global", null, (j) => (j.ok ? j : null));
  const movers = liveMovers ?? moversFrom(universe);
  const indices = globalBoard?.indices ?? [];
  const secs = pulse?.sectors?.length
    ? pulse.sectors.map((s) => ({ name: s.name, chg: s.chg, weight: s.count }))
    : sectors(universe);
  return (
    <div>
      <PageHeader eyebrow="Live · NSE / BSE" title="Market Overview"
        description="Indices, breadth, sector rotation and the day's movers — one live tape."
        actions={<LiveDot />} />

      {/* Indices — real global board */}
      {indices.length > 0 && (
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {indices.slice(0, 6).map((idx, i) => (
            <Card key={idx.name} delay={i * 0.04} interactive className="p-4">
              <div className="flex items-center justify-between"><span className="text-[11px] font-semibold uppercase tracking-wide text-muted">{idx.name}</span><DeltaPill pct={idx.changePct ?? 0} /></div>
              <div className="mt-1.5 text-[18px] font-semibold text-frost tnum">{idx.price != null ? idx.price.toLocaleString("en-IN") : "—"}</div>
              <Sparkline data={series(idx.name.charCodeAt(0) + idx.name.length, 40, idx.price || 100, 0.006)} width={180} height={30} positive={(idx.changePct ?? 0) >= 0} />
            </Card>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Sector heatmap */}
        <Card className="xl:col-span-2">
          <CardHeader icon={<Gauge size={16} />} title="Sector Rotation" subtitle="Average performance by sector today" />
          <CardBody>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {secs.map((s) => {
                const intensity = Math.min(1, Math.abs(s.chg) / 3);
                const bg = s.chg >= 0
                  ? `color-mix(in oklab, var(--color-up) ${18 + intensity * 40}%, var(--color-elevated))`
                  : `color-mix(in oklab, var(--color-down) ${18 + intensity * 40}%, var(--color-elevated))`;
                return (
                  <div key={s.name} className="rounded-[var(--radius-md)] p-3 hairline" style={{ background: bg }}>
                    <div className="text-[12px] font-semibold text-frost truncate">{s.name}</div>
                    <div className={cn("mt-1 text-[16px] font-bold tnum", trendClass(s.chg))}>{pct(s.chg)}</div>
                    <div className="text-[10px] text-muted">{s.weight} stocks</div>
                  </div>
                );
              })}
            </div>
          </CardBody>
        </Card>

        {/* Breadth */}
        <Card>
          <CardHeader icon={<Activity size={16} />} title="Market Breadth" />
          <CardBody className="space-y-4">
            {(() => {
              const b = pulse?.breadth;
              const adv = b?.advancing ?? 0, dec = b?.declining ?? 0;
              const tot = b?.total ?? 0, unch = Math.max(0, tot - adv - dec);
              const ratio = dec ? (adv / dec) : 0;
              const rows: [string, number, string][] = [["Advances", adv, "up"], ["Declines", dec, "down"], ["Unchanged", unch, "neutral"]];
              return <>
                {rows.map(([k, v, t]) => (
                  <div key={k}>
                    <div className="mb-1 flex justify-between text-[12px]"><span className="text-muted">{k}</span><span className="font-semibold text-frost tnum">{v.toLocaleString("en-IN")}</span></div>
                    <div className="h-1.5 rounded-full bg-line overflow-hidden"><div className={cn("h-full rounded-full", t === "up" ? "bg-up" : t === "down" ? "bg-down" : "bg-muted")} style={{ width: `${v / (tot || 1) * 100}%` }} /></div>
                  </div>
                ))}
                <div className="rounded-[var(--radius-md)] bg-void/40 p-3 hairline">
                  <div className="flex items-center justify-between text-[12px]"><span className="text-muted">Adv/Dec Ratio</span><span className={cn("font-bold tnum", ratio >= 1 ? "text-up" : "text-down")}>{ratio.toFixed(2)}</span></div>
                </div>
              </>;
            })()}
          </CardBody>
        </Card>
      </div>

      {/* Movers */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card><CardHeader icon={<TrendingUp size={16} className="text-up" />} title="Top Gainers" /><CardBody className="space-y-0.5">{movers.gainers.map((s) => <StockRow key={s.symbol} stock={s} spark={false} />)}</CardBody></Card>
        <Card><CardHeader icon={<TrendingDown size={16} className="text-down" />} title="Top Losers" /><CardBody className="space-y-0.5">{movers.losers.map((s) => <StockRow key={s.symbol} stock={s} spark={false} />)}</CardBody></Card>
        <Card>
          <CardHeader icon={<Activity size={16} />} title="Most Active" subtitle="By volume" />
          <CardBody className="space-y-1">
            {movers.volume.map((s) => (
              <div key={s.symbol} onClick={() => router.push(`/stocks/${s.symbol}`)} className="flex cursor-pointer items-center gap-3 rounded-[var(--radius-sm)] px-2.5 py-2 hover:bg-raised/60">
                <Avatar symbol={s.symbol} size={30} />
                <div><div className="text-[13px] font-semibold text-frost">{s.symbol}</div><div className="text-[11px] text-muted tnum">{compactCr(s.volume)} vol</div></div>
                <div className="ml-auto text-right"><div className="text-[13px] font-semibold text-frost tnum">{inr(s.price)}</div><div className={cn("text-[11px] tnum", trendClass(s.changePct))}>{pct(s.changePct)}</div></div>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      {/* Institutional flows + global board */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader icon={<ArrowRightLeft size={16} />} title="Institutional Flows" subtitle={flows?.date ? `Net cash · ${flows.date}` : "FII / DII net (₹ Cr)"} />
          <CardBody className="space-y-3">
            {[["FII", flows?.fiiNet, flows?.fiiStance], ["DII", flows?.diiNet, flows?.diiStance]].map(([k, net, stance]) => {
              const n = (net as number | null | undefined);
              return (
                <div key={k as string} className="flex items-center justify-between rounded-[var(--radius-sm)] bg-void/40 p-3 hairline">
                  <span className="text-[12px] font-semibold text-muted">{k as string}</span>
                  <span className={cn("text-[15px] font-bold tnum", n == null ? "text-muted" : n >= 0 ? "text-up" : "text-down")}>{n == null ? "—" : `₹${signed(n, 0)} Cr`}</span>
                  {stance ? <Badge tone={(n ?? 0) >= 0 ? "up" : "down"}>{stance as string}</Badge> : <Badge tone="neutral">—</Badge>}
                </div>
              );
            })}
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader icon={<Globe2 size={16} />} title="Global Markets" subtitle="World indices & commodities" action={globalBoard ? <LiveDot /> : null} />
          <CardBody>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {[...(globalBoard?.indices ?? []), ...(globalBoard?.commodities ?? [])].slice(0, 8).map((g) => (
                <div key={g.name} className="rounded-[var(--radius-md)] bg-void/40 p-3 hairline">
                  <div className="text-[11px] font-medium text-muted truncate">{g.name}</div>
                  <div className="mt-1 text-[14px] font-semibold text-frost tnum">{g.price != null ? g.price.toLocaleString("en-IN") : "—"}</div>
                  <div className={cn("text-[11px] tnum", trendClass(g.changePct ?? 0))}>{g.changePct != null ? pct(g.changePct) : "—"}</div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
