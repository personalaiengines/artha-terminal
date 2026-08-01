"use client";
import { Layers } from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { HealthBar } from "@/components/ui/stat";
import { num, pct, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// The S/R surface: the confluence zones services/fno_analysis.py::level_zones
// computes, ordered by price with live spot pinned between them.
//
// Every number and every word on a row comes out of the payload — the `basis`
// string is rendered VERBATIM and is never model-touched. That string is the
// product: it is what makes a line on the chart trustworthy (R18).

export type ZoneMember = { label: string; price: number; kind: string; crossed: boolean };
export type Zone = {
  price: number; lo: number; hi: number;
  members: ZoneMember[];
  kind: string; crossed: boolean;
  state: string;          // "INTACT" | "AT PRICE" | "BROKEN" — rendered as-is
  flip?: string;          // present only when crossed
  dist_pct: number; strength: number; basis: string;
};
export type Structure = { signal: string | null; headline: string; basis?: string | null };
/** A live position pinned to the zone whose band contains its strike. */
export type LevelMarker = { price: number; label: string };

// One colour per level kind. Exported so the candle chart draws the same zone
// in the same colour it has in the ladder.
export const KIND_COLOR: Record<string, string> = {
  resistance: "#f4586a",
  support: "#10b981",
  pivot: "#f5a623",
  maxpain: "#a78bfa",
  range: "#38bdf8",
};

// HOLD / WATCH / REVIEW describe the state of the LEVEL MAP, never a position.
const SIGNAL_TONE = { HOLD: "neutral", WATCH: "accent", REVIEW: "warn" } as const;
const STATE_TONE = { INTACT: "neutral", "AT PRICE": "accent", BROKEN: "warn" } as const;

const color = (kind: string) => KIND_COLOR[kind] ?? "#f5a623";

export function LevelLadder({
  zones, spot, structure, markers = [],
}: {
  zones: Zone[];
  spot: number;
  structure: Structure | null;
  markers?: LevelMarker[];
}) {
  const desc = [...zones].sort((a, b) => b.price - a.price);
  const above = desc.filter((z) => z.price >= spot);
  const below = desc.filter((z) => z.price < spot);

  const row = (z: Zone, i: number) => {
    const band = z.hi > z.lo;
    const pins = markers.filter((m) => m.price >= z.lo && m.price <= z.hi);
    return (
      <li key={`${z.price}-${i}`} className="grid grid-cols-[110px_1fr] gap-x-4 gap-y-2 px-4 py-3.5 md:grid-cols-[140px_1fr_150px]">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-4 w-1 shrink-0 rounded-full" style={{ background: color(z.kind), opacity: z.crossed ? 0.45 : 1 }} />
            <span className={cn("text-[16px] font-semibold tnum", z.crossed ? "text-mist line-through decoration-warn/60" : "text-frost")}>
              {num(z.price, { decimals: 0 })}
            </span>
          </div>
          <div className="mt-0.5 pl-3 text-[11.5px] tnum">
            <span className={trendClass(z.dist_pct)}>{pct(z.dist_pct)}</span>
            <span className="ml-1.5 text-faint uppercase">{z.kind}</span>
          </div>
          {band && (
            <div className="pl-3 text-[10.5px] text-faint tnum">
              {num(z.lo, { decimals: 0 })}–{num(z.hi, { decimals: 0 })}
            </div>
          )}
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            {z.members.map((m) => (
              <span key={m.label}
                className={cn("inline-flex items-center gap-1.5 rounded-full bg-raised px-2 py-0.5 text-[10.5px] font-medium hairline",
                  m.crossed ? "text-muted line-through" : "text-mist")}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: color(m.kind) }} />
                {m.label}
              </span>
            ))}
            <Badge tone={STATE_TONE[z.state as keyof typeof STATE_TONE] ?? "neutral"}>{z.state}</Badge>
            {z.flip && <span className="text-[11px] font-medium text-warn">{z.flip}</span>}
            {pins.map((m) => (
              <Badge key={m.label} tone="accent">position · {m.label}</Badge>
            ))}
          </div>
          {/* rule-derived provenance, verbatim from the engine (R18) */}
          <p className="mt-1.5 text-[11.5px] leading-snug text-muted">{z.basis}</p>
        </div>

        <div className="col-span-2 md:col-span-1 md:pt-1">
          <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-faint">
            <span>Strength</span>
            <span className="tnum text-mist">{z.strength}/100</span>
          </div>
          <HealthBar value={z.strength} />
        </div>
      </li>
    );
  };

  return (
    <Card>
      <CardHeader
        icon={<Layers size={16} />}
        title="Level Map · confluence zones"
        subtitle="Where independent methods — pivots, prior-session extremes, OI walls, max pain — land on the same price"
        action={structure?.signal
          ? <Badge tone={SIGNAL_TONE[structure.signal as keyof typeof SIGNAL_TONE] ?? "neutral"}>{structure.signal}</Badge>
          : null}
      />
      <CardBody className="pt-0">
        {structure && (
          <div className="mb-3 rounded-[var(--radius-sm)] bg-void p-3 hairline">
            <p className="text-[12.5px] text-frost">{structure.headline}</p>
            {structure.basis && <p className="mt-0.5 text-[11.5px] text-muted">{structure.basis}</p>}
          </div>
        )}

        {zones.length === 0 ? (
          <p className="py-8 text-center text-[12.5px] text-muted">
            Level map unavailable — no zones were computed for this session.
          </p>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-[var(--radius-sm)] hairline">
            {above.map(row)}
            <li className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-accent-soft/25 px-4 py-2">
              <span className="text-[10.5px] font-semibold uppercase tracking-wider text-accent">Spot</span>
              <span className="text-[14px] font-semibold text-frost tnum">{num(spot, { decimals: 2 })}</span>
              <span className="ml-auto text-[11px] text-muted tnum">{above.length} above · {below.length} below</span>
            </li>
            {below.map(row)}
          </ul>
        )}

        <p className="mt-3 text-[11px] leading-snug text-faint">
          Technical reference levels computed from the last settled session&apos;s OHLC and the live option
          chain. A zone marked BROKEN traded through this session and is shown as broken, not renamed.
          These are not price targets and not investment advice.
        </p>
      </CardBody>
    </Card>
  );
}
