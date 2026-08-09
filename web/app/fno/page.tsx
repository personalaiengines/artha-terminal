"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { LineChart, Activity, Gauge, ArrowUpRight } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { Segmented, LiveDot, EmptyState } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/badge";
import { TIMEFRAME_DAYS, type Timeframe } from "@/components/ui/candles";
import { KlineChart } from "@/components/widgets/kline-chart";
import { LevelLadder, KIND_COLOR } from "@/components/widgets/level-ladder";
import { PositionsPanel, usePositions, strikeOf } from "@/components/widgets/positions-panel";
import { FnoNarrative } from "@/components/widgets/fno-narrative";
import { PnlTracker } from "@/components/widgets/pnl-tracker";
import { useApi } from "@/lib/use-api";
import type { Candle, Plan } from "@/lib/fno-types";
import { useLivePrices } from "@/lib/use-live-prices";
import { POLL } from "@/lib/poll";
import { num, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// "What is the market doing?" — index structure and the decision surface.
// The option chain deliberately does NOT render here; it lives on /options and
// this page links to it (R1). Nothing on this page is duplicated there (R2).

const INDICES = ["NIFTY", "BANKNIFTY", "SENSEX"];
// The service key each switcher value resolves to, so the page can tell the
// payload it asked for from the one still on screen.
const INDEX_KEY: Record<string, string> = { NIFTY: "nifty50", BANKNIFTY: "banknifty", SENSEX: "sensex" };

// The four standard OI build-up quadrants (price change x OI change). These
// describe what the OI did — they are not instructions.
const QUADRANTS = [
  { key: "long_buildup", label: "Long build-up", hint: "price up · OI up" },
  { key: "short_buildup", label: "Short build-up", hint: "price down · OI up" },
  { key: "short_covering", label: "Short covering", hint: "price up · OI down" },
  { key: "long_unwinding", label: "Long unwinding", hint: "price down · OI down" },
] as const;

const QUAD_LABEL: Record<string, string> = Object.fromEntries(QUADRANTS.map((q) => [q.key, q.label]));

// Open interest is quoted in lakh of contracts across the desk. A missing
// measurement is an em dash, never 0 (R17).
const lakh = (n: number | null | undefined) =>
  typeof n === "number" && Number.isFinite(n) ? `${n >= 0 ? "+" : "−"}${(Math.abs(n) / 1e5).toFixed(1)}L` : "—";

const ordinal = (n: number) => {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
};

export default function FnO() {
  const [idx, setIdx] = useState("NIFTY");
  const [tf, setTf] = useState<Timeframe>("1Y");
  const live = useApi<Plan | null>(`/api/fno/${idx}`, null, (j) => (j.ok ? j : null), POLL.fno);
  const candles = useApi<Candle[]>(`/api/history?symbols=${idx}&days=${TIMEFRAME_DAYS[tf]}&ohlc=1`, [], (j) => j.candles ?? [], POLL.history);
  const book = usePositions();
  // The chain is server-cached for 120s and polled at 120s, so its `spot` was
  // up to four minutes behind the tape the dashboard renders live. Subscribe the
  // underlying to the same tick stream the index board uses — this hook must sit
  // above the early return below, like every other one on this page.
  const spotTick = useLivePrices([INDEX_KEY[idx]]);

  // One mapping, straight from the confluence engine — the chart and the ladder
  // draw the same zones in the same colours, with `crossed` marking the broken
  // ones and `basis` carried through verbatim into the chart tooltip (R4/R18).
  //
  // Memoised, and up here with every other hook rather than beside its use below
  // the early return: the tick subscription above re-renders this page several
  // times a second, and a fresh array identity is enough to make the chart tear
  // down and rebuild all ~19 level overlays on every one of those renders (R21).
  // The mapping itself is untouched.
  const chartLevels = useMemo(() => (live?.zones ?? []).map((z) => ({
    price: z.price, lo: z.lo, hi: z.hi,
    label: z.label,
    color: KIND_COLOR[z.kind] ?? "#f5a623",
    kind: z.kind, crossed: z.crossed, strength: z.strength, basis: z.basis, state: z.state,
  })), [live?.zones]);

  const header = (
    <PageHeader eyebrow="Derivatives" title="F&O · Market Structure"
      description="What the market is doing: the level map, where open interest moved, and volatility context. The strike-by-strike chain lives on Options."
      actions={<><Segmented value={idx} onChange={setIdx} options={INDICES.map((v) => ({ label: v, value: v }))} /><LiveDot label={live ? "LIVE" : "NO DATA"} /></>} />
  );

  // useApi keeps the previous payload until the next one lands, and a cold chain
  // fetch for a newly-selected index takes 10-20s. Rendering NIFTY levels under
  // a BANKNIFTY heading would be a fabricated read of a market nobody asked
  // about, so gate on the payload naming the index that is selected.
  if (!live || live.index !== INDEX_KEY[idx]) {
    return (
      <div>
        {header}
        <Card><CardBody><EmptyState icon={<Activity size={22} />}
          title={live ? `Loading the ${idx} chain…` : `No live option chain for ${idx}`}
          description={live
            ? "Pulling the option chain and rebuilding the level map for this index."
            : "Upstox may be unauthenticated, outside market hours, or unreachable."} /></CardBody></Card>
        {/* The tracker and the containment rate read ARTHA's own record, not
            the broker, so they are still worth showing on exactly the days the
            chain will not load. */}
        <div className="mt-6"><PnlTracker book={book} /></div>
      </div>
    );
  }

  const { atm, rows, pcr, maxPain, zones, structure } = live;
  // Ticks win over the cached chain when one has arrived. Only `spot` moves:
  // ATM, PCR and max pain are computed from the whole chain and stay on their
  // own refresh rather than being implied to be as fresh as the price.
  const tick = spotTick[INDEX_KEY[idx].toUpperCase()];
  const spot = tick?.price ?? live.spot;

  // Open contracts pinned onto the ladder at the strike parsed from their name.
  const markers = (book?.items ?? [])
    .map((p) => ({ price: strikeOf(p.symbol), label: p.symbol }))
    .filter((m): m is { price: number; label: string } => m.price != null);

  // R13/R17: a percentile of a short window is not a percentile. Say which of
  // the three states this is instead of printing a bare dash.
  const vixSub = live.vix == null
    ? "India VIX unavailable this session"
    : live.vixPctile != null
      ? `${ordinal(Math.round(live.vixPctile))} percentile of ${live.vixWindow} sessions${live.vixAsOf ? ` · to ${live.vixAsOf}` : ""}`
      : live.vixWindow >= 60
        ? `percentile unavailable for this reading (${live.vixWindow} sessions stored)`
        : `percentile unavailable — ${live.vixWindow} of the 60 sessions needed are stored`;

  const bu = live.buildupSummary;
  const movers = rows
    .flatMap((r) => [
      { strike: r.strike, side: "CALL" as const, oiChg: r.call.oiChg, buildup: r.call.buildup },
      { strike: r.strike, side: "PUT" as const, oiChg: r.put.oiChg, buildup: r.put.buildup },
    ])
    .sort((a, b) => Math.abs(b.oiChg) - Math.abs(a.oiChg))
    .slice(0, 6);

  const quadCell = (side: "call" | "put", q: typeof QUADRANTS[number]) => {
    const cell = bu?.[side]?.[q.key];
    return (
      <div key={q.key} className="rounded-[var(--radius-sm)] bg-void p-3 hairline">
        <div className="text-[11px] font-medium text-mist">{q.label}</div>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className="text-[18px] font-semibold text-frost tnum">{cell ? cell.legs : "—"}</span>
          <span className="text-[10.5px] text-muted">strikes</span>
        </div>
        {/* no legs in this quadrant is not an OI move of zero — print nothing to measure */}
        <div className={cn("text-[11.5px] tnum", trendClass(cell?.legs ? cell.oi_change : null))}>
          {cell?.legs ? lakh(cell.oi_change) : "—"} OI
        </div>
        <div className="mt-0.5 text-[10px] text-faint">{q.hint}</div>
      </div>
    );
  };

  return (
    <div>
      {header}

      {/* Metrics — index-level context only. Per-strike microstructure is on /options. */}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        {/* Say which of the two this number is. A live tick and a two-minute-old
            chain snapshot look identical on screen, and only one of them is
            worth acting on. */}
        <Card className="p-4"><Stat label="Spot" value={spot} decimals={2}
          sub={[tick ? "live tick" : "chain snapshot", live.expiry ? `expiry ${live.expiry}` : ""].filter(Boolean).join(" · ")} /></Card>
        <Card className="p-4"><Stat label="ATM Strike" value={atm} decimals={0} /></Card>
        <Card className="p-4"><Stat label="PCR (OI)" value={pcr} decimals={2} sub={live.biasLabel ?? undefined} /></Card>
        <Card className="p-4"><Stat label="Max Pain" value={maxPain} decimals={0} /></Card>
        <Card className="p-4 xl:col-span-2"><Stat label="India VIX" value={live.vix} decimals={2} sub={vixSub} /></Card>
      </div>

      {/* The only success figure in the app with a denominator behind it. */}

      {/* Chart + ladder are the centre of the page. */}
      <Card className="mb-6">
        <CardHeader icon={<LineChart size={16} />} title={`${idx} · price against the level map`}
          subtitle="Wheel or pinch to zoom, drag to pan. A level price traded through is drawn broken; each level's basis is spelled out in the map below."
          action={structure?.signal ? <Badge tone="neutral">{zones.length} zones</Badge> : null} />
        <CardBody className="pt-0">
          {candles.length > 0
            ? <KlineChart symbol={idx} liveKey={live.index} data={candles} levels={chartLevels} spot={spot} height={440} timeframe={tf} onTimeframe={setTf} />
            : <p className="py-10 text-center text-[12.5px] text-muted">No daily index history stored for {idx}.</p>}
        </CardBody>
      </Card>

      <div className="mb-6">
        <LevelLadder zones={zones} spot={spot} structure={structure} markers={markers} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader icon={<Gauge size={16} />} title="OI Build-Up"
            subtitle="Each leg classified by its own price change against its open-interest change"
            action={bu?.basis ? <Badge tone="neutral">basis · {bu.basis}</Badge> : null} />
          <CardBody className="pt-0 space-y-4">
            {!bu ? (
              <p className="py-6 text-center text-[12.5px] text-muted">No build-up classification for this session.</p>
            ) : (
              <>
                <div className="grid gap-4 md:grid-cols-2">
                  {(["call", "put"] as const).map((side) => (
                    <div key={side}>
                      <div className="mb-2 flex items-center gap-2">
                        <span className={cn("text-[11px] font-semibold uppercase tracking-wide", side === "call" ? "text-down" : "text-up")}>
                          {side === "call" ? "Calls" : "Puts"}
                        </span>
                        {bu.unclassified && (
                          <span className="text-[10.5px] text-faint">{bu.unclassified[side]} legs flat, not classified</span>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-2">{QUADRANTS.map((q) => quadCell(side, q))}</div>
                    </div>
                  ))}
                </div>

                <div>
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Biggest OI moves this session</div>
                  <ul className="divide-y divide-line overflow-hidden rounded-[var(--radius-sm)] hairline">
                    {movers.map((m) => (
                      <li key={`${m.strike}-${m.side}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[12px]">
                        <span className="font-semibold text-frost tnum">{num(m.strike, { decimals: 0 })}</span>
                        <Badge tone={m.side === "CALL" ? "down" : "up"}>{m.side}</Badge>
                        <span className={cn("tnum", trendClass(m.oiChg))}>{lakh(m.oiChg)} OI</span>
                        <span className="ml-auto text-[11px] text-mist">{m.buildup ? QUAD_LABEL[m.buildup] ?? m.buildup : "—"}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <p className="text-[11px] leading-snug text-faint">
                  Classification basis: <span className="text-muted">{live.buildupBasis ?? "unavailable"}</span> — each leg&apos;s own
                  change against its prior close, paired with its open-interest change. A leg whose price or OI did not
                  move is left unclassified rather than assigned a quadrant.
                </p>
              </>
            )}
          </CardBody>
        </Card>

        <div className="space-y-6">
          <PositionsPanel book={book} />

          <Card interactive>
            <Link href={`/options?index=${idx}${live.expiry ? `&expiry=${live.expiry}` : ""}`} className="block px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-[13px] font-semibold text-frost">Full option chain</h3>
                  <p className="mt-1 text-[11.5px] leading-snug text-muted">
                    Strike-by-strike OI, IV, Δ and the volatility surface for {idx}
                    {live.expiry ? ` · ${live.expiry}` : ""} — on the Options page, the one place the chain renders.
                  </p>
                </div>
                <ArrowUpRight size={16} className="mt-0.5 shrink-0 text-accent" />
              </div>
            </Link>
          </Card>
        </div>
      </div>

      <div className="mt-6">
        <PnlTracker book={book} />
      </div>

      <div className="mt-6">
        <FnoNarrative idx={idx} source="oi-read" />
      </div>
    </div>
  );
}
