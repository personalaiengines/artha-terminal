"use client";
import { useMemo } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { KlineChart, type ResLabel } from "@/components/widgets/kline-chart";
import { zonesToLevels } from "@/components/widgets/level-ladder";
import { INDEX_SYMBOLS, type IndexSymbol, type Pane } from "@/lib/chart-grid";
import type { Candle, Plan } from "@/lib/fno-types";
import type { LiveTick } from "@/lib/use-live-prices";
import { num, pct, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// One cell of the Charts grid: which instrument, its price, its place in the
// grid — and below that, the same KlineChart the F&O page draws, in fill mode.
//
// Nothing about the chart is re-implemented here. Levels, drawings, indicators,
// the keyboard map and the expand-to-window behaviour are all the component's
// own, per instance: `onKeyDown` is bound to the pane's own role="application"
// div and every key it answers to mutates that instance's state, so a shortcut
// pressed in one pane cannot reach another (R38), and F/Esc is its existing
// `expanded`, already fixed inset-0 (R40).

/** The name the tick socket knows each index by. Same map the F&O page uses;
 *  the page above needs it too, to subscribe once per distinct instrument. */
export const INDEX_KEY: Record<IndexSymbol, string> = {
  NIFTY: "nifty50", BANKNIFTY: "banknifty", SENSEX: "sensex",
};

/** One array shared by every pane still waiting on its bars: the page's `?? []`
 *  mints a fresh one per render, which would re-run the chart's data effect on
 *  every tick for a pane that has nothing to draw yet. */
const NO_CANDLES: Candle[] = [];

function IconBtn({ onClick, disabled, label, children }: {
  onClick: () => void; disabled?: boolean; label: string; children: React.ReactNode;
}) {
  return (
    <button onClick={onClick} disabled={disabled} title={label} aria-label={label}
      className={cn("rounded-[6px] p-1 transition-colors",
        disabled ? "text-faint opacity-40" : "text-muted hover:bg-raised hover:text-frost")}>
      {children}
    </button>
  );
}

export function ChartPane({
  pane, tick, candles, plan, canLeft, canRight, canRemove,
  onSymbol, onRes, onMove, onRemove,
}: {
  pane: Pane;
  /** the live tick for this pane's instrument, if one has arrived */
  tick?: LiveTick;
  candles: Candle[];
  /** the /api/fno payload for this instrument — null until the chain answers */
  plan: Plan | null;
  canLeft: boolean;
  canRight: boolean;
  canRemove: boolean;
  onSymbol: (s: IndexSymbol) => void;
  onRes: (r: ResLabel) => void;
  onMove: (dir: -1 | 1) => void;
  onRemove: () => void;
}) {
  // The tape wins over the chain snapshot when a tick has arrived; otherwise the
  // chain's own spot, which is what the level map was computed against. Never a
  // number this page made up.
  const spot = tick?.price ?? plan?.spot ?? null;
  // Memoised on the payload the levels are derived from, and that is the whole
  // point of R21: this pane re-renders on every tick (the header prices come off
  // the tape), and a fresh array here fails the chart's levels effect identity
  // check — 19 removeOverlay + 19 createOverlay + 19 convertToPixel per tick per
  // pane, which is the churn splitting SPOT out of the group was meant to end.
  const levels = useMemo(() => (plan ? zonesToLevels(plan.zones) : []), [plan]);

  return (
    <Card className="flex h-full min-w-0 flex-col p-2">
      {/* 28px of header, and it holds the three things worth a glance: which
          instrument, what it costs, and where this pane sits in the grid. */}
      <div className="mb-1.5 flex h-7 shrink-0 items-center gap-1.5">
        {/* Three plain buttons, not ui/primitives' Segmented: that one hardcodes
            framer-motion's layoutId="seg", so six of them on a page share one
            highlight and it flies between panes on every click. */}
        <div className="inline-flex shrink-0 items-center gap-0.5 rounded-[var(--radius-sm)] bg-void p-0.5 hairline">
          {INDEX_SYMBOLS.map((s) => (
            <button key={s} onClick={() => onSymbol(s)} aria-pressed={s === pane.symbol}
              className={cn("rounded-[6px] px-1.5 py-0.5 text-[10.5px] font-medium transition-colors",
                s === pane.symbol ? "bg-raised text-frost hairline" : "text-muted hover:text-mist")}>
              {s}
            </button>
          ))}
        </div>

        <span className="truncate text-[12.5px] font-semibold text-frost tnum"
          title={tick ? "live tick" : "option-chain snapshot"}>
          {num(spot, { decimals: 2 })}
        </span>
        {/* A tick without `close` has no honest day-change baseline, and pct()
            prints an em dash for it rather than measuring against the wrong one. */}
        <span className={cn("text-[11px] tnum", trendClass(tick?.changePct))}>
          {pct(tick?.changePct ?? null)}
        </span>

        <span className="ml-auto inline-flex shrink-0 items-center gap-0.5">
          <IconBtn onClick={() => onMove(-1)} disabled={!canLeft} label="Move this chart left">
            <ChevronLeft size={13} />
          </IconBtn>
          <IconBtn onClick={() => onMove(1)} disabled={!canRight} label="Move this chart right">
            <ChevronRight size={13} />
          </IconBtn>
          <IconBtn onClick={onRemove} disabled={!canRemove} label="Remove this chart">
            <X size={13} />
          </IconBtn>
        </span>
      </div>

      <div className="min-h-0 flex-1">
        <KlineChart
          height="fill" compact
          prefsScope={`charts.${pane.id}`}
          res={pane.res} onRes={onRes}
          symbol={pane.symbol} liveKey={INDEX_KEY[pane.symbol]}
          data={candles.length ? candles : NO_CANDLES} levels={levels} spot={spot}
        />
      </div>
    </Card>
  );
}
