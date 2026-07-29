"use client";
import { Activity, ArrowDown, ArrowUp } from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { StaleBadge } from "@/components/widgets/data-health";
import { cn } from "@/lib/utils";

// Market breadth, written to be read by someone who doesn't already know what
// "breadth" means.
//
// The old card was three progress bars (Advances / Declines / Unchanged) and a
// bare "Adv/Dec Ratio 7.17". Every number was correct and none of them said
// anything: no verdict, no scale to judge the ratio against, and no mention of
// WHICH universe was measured — "43 of 49" is meaningless without "of the
// NIFTY 50".

export type Breadth = { advancing: number; declining: number; total: number; pct: number };
export type Extreme = { symbol: string; chg: number } | null;

/** Plain-English reading of the advance/decline split. */
function verdict(pct: number): { title: string; detail: string; tone: "up" | "down" | "neutral" } {
  if (pct >= 70)
    return { title: "Broad-based advance", tone: "up",
      detail: "Most stocks are rising, not just a few heavyweights — moves this wide tend to hold." };
  if (pct >= 55)
    return { title: "Moderately broad advance", tone: "up",
      detail: "More stocks up than down, though the move isn't market-wide." };
  if (pct > 45)
    return { title: "Mixed, no clear direction", tone: "neutral",
      detail: "Advances and declines are near even — the index level is being set by a handful of names." };
  if (pct > 30)
    return { title: "Moderately broad decline", tone: "down",
      detail: "More stocks down than up, though not across the board." };
  return { title: "Broad-based decline", tone: "down",
    detail: "Selling is market-wide rather than concentrated in a few names." };
}

/** Position of an adv/dec ratio on a 0-1 scale, log-spaced around parity. */
function ratioPos(r: number): number {
  if (!Number.isFinite(r) || r <= 0) return 0;
  const clamped = Math.min(3, Math.max(1 / 3, r));
  return (Math.log(clamped) - Math.log(1 / 3)) / (Math.log(3) - Math.log(1 / 3));
}

export function MarketBreadth({
  breadth, sectors, universeLabel, topGainer, topLoser, stale, asOf,
}: {
  breadth?: Breadth | null;
  sectors: { name: string; chg: number }[];
  universeLabel?: string | null;
  topGainer?: Extreme; topLoser?: Extreme;
  stale?: boolean; asOf?: string | null;
}) {
  const adv = breadth?.advancing ?? 0;
  const dec = breadth?.declining ?? 0;
  const total = breadth?.total ?? 0;
  const flat = Math.max(0, total - adv - dec);
  const pct = breadth?.pct ?? 0;
  const ratio = dec ? adv / dec : adv ? Infinity : 0;
  const v = verdict(pct);

  const green = sectors.filter((s) => s.chg > 0).length;
  const width = (n: number) => `${total ? (n / total) * 100 : 0}%`;

  return (
    <Card>
      <CardHeader icon={<Activity size={16} />} title="Market Breadth"
        subtitle="How many stocks rose versus fell — width matters more than the index level"
        action={stale ? <StaleBadge asOf={asOf ?? null} /> : null} />
      <CardBody className="space-y-4">
        {total === 0 ? (
          <p className="py-6 text-center text-[13px] text-muted">No breadth data available yet.</p>
        ) : (
          <>
            {/* Headline: the number, then what it means in words. */}
            <div className="flex items-start gap-4">
              <div className="shrink-0">
                <div className={cn("text-[34px] font-bold leading-none tnum",
                  v.tone === "up" ? "text-up" : v.tone === "down" ? "text-down" : "text-frost")}>
                  {pct}%
                </div>
                <div className="mt-1 text-[11px] uppercase tracking-wide text-muted">advancing</div>
              </div>
              <div className="min-w-0">
                <div className="text-[13.5px] font-semibold text-frost">{v.title}</div>
                <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted">{v.detail}</p>
                <p className="mt-1 text-[11.5px] text-mist tnum">
                  {adv} of {total} {universeLabel ?? "tracked"} stocks rose
                </p>
              </div>
            </div>

            {/* One diverging bar reads faster than three separate ones. */}
            <div>
              <div className="flex h-3 overflow-hidden rounded-full bg-line">
                <div className="bg-up transition-all" style={{ width: width(adv) }} title={`${adv} advancing`} />
                <div className="bg-muted/40 transition-all" style={{ width: width(flat) }} title={`${flat} unchanged`} />
                <div className="bg-down transition-all" style={{ width: width(dec) }} title={`${dec} declining`} />
              </div>
              <div className="mt-1.5 flex justify-between text-[11px] tnum">
                <span className="text-up">{adv} advancing</span>
                {flat > 0 && <span className="text-muted">{flat} flat</span>}
                <span className="text-down">{dec} declining</span>
              </div>
            </div>

            {/* Ratio with a scale, so the number is judgeable without knowing
                what a "normal" adv/dec ratio looks like. */}
            <div className="rounded-[var(--radius-md)] bg-void/40 p-3 hairline">
              <div className="flex items-baseline justify-between">
                <span className="text-[12px] text-muted">Advance / decline ratio</span>
                <span className={cn("text-[15px] font-bold tnum", ratio >= 1 ? "text-up" : "text-down")}>
                  {ratio === Infinity ? "∞" : ratio.toFixed(2)}
                </span>
              </div>
              <div className="relative mt-2 h-1.5 rounded-full bg-gradient-to-r from-down via-muted to-up opacity-70">
                <span className="absolute top-1/2 h-3 w-3 -translate-y-1/2 rounded-full bg-frost ring-2 ring-abyss"
                  style={{ left: `calc(${ratioPos(ratio) * 100}% - 6px)` }} />
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-faint">
                <span>0.33 selling</span><span>1.0 even</span><span>3.0 buying</span>
              </div>
            </div>

            {/* Sector participation — the second dimension of "how broad". */}
            {sectors.length > 0 && (
              <div>
                <div className="mb-1 flex justify-between text-[12px]">
                  <span className="text-muted">Sectors positive</span>
                  <span className="font-semibold text-frost tnum">{green} of {sectors.length}</span>
                </div>
                <div className="flex gap-0.5">
                  {sectors.map((s) => (
                    <span key={s.name} title={`${s.name} ${s.chg > 0 ? "+" : ""}${s.chg?.toFixed(2)}%`}
                      className={cn("h-2 flex-1 rounded-sm", s.chg > 0 ? "bg-up" : s.chg < 0 ? "bg-down" : "bg-muted/40")} />
                  ))}
                </div>
              </div>
            )}

            {(topGainer || topLoser) && (
              <div className="flex gap-2 text-[11.5px]">
                {topGainer && (
                  <span className="flex flex-1 items-center gap-1.5 rounded-[var(--radius-sm)] bg-up-soft/25 px-2.5 py-1.5">
                    <ArrowUp size={12} className="text-up" />
                    <span className="font-semibold text-frost">{topGainer.symbol}</span>
                    <span className="ml-auto font-semibold text-up tnum">+{topGainer.chg?.toFixed(2)}%</span>
                  </span>
                )}
                {topLoser && (
                  <span className="flex flex-1 items-center gap-1.5 rounded-[var(--radius-sm)] bg-down-soft/25 px-2.5 py-1.5">
                    <ArrowDown size={12} className="text-down" />
                    <span className="font-semibold text-frost">{topLoser.symbol}</span>
                    <span className="ml-auto font-semibold text-down tnum">{topLoser.chg?.toFixed(2)}%</span>
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
