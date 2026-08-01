"use client";
import { GitCompareArrows } from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MultiLine } from "@/components/ui/chart";
import { num, signed } from "@/lib/format";
import type { OCRow } from "@/components/widgets/option-chain";

// Expiry payoff of the structure `strategy_concept` names, priced ENTIRELY from
// the loaded chain: every leg is a real listed strike and every premium is that
// strike's own live LTP. If one leg will not resolve — no anchor, strike outside
// the loaded range, or no live price — the diagram is not drawn and the reason
// is printed instead. Nothing is interpolated to complete the picture (R17).
//
// It illustrates a named structure. It is not a suggestion to put one on (R16).

export type ConceptLeg = { right: "call" | "put"; pos: "long" | "short"; anchor: string; step: number };
export type Concept = {
  name: string | null; note: string | null;
  anchors: Record<string, number | null> | null; legs: ConceptLeg[];
};

type Priced = ConceptLeg & { strike: number; ltp: number };

const ANCHOR_LABEL: Record<string, string> = {
  call_wall: "call OI wall", put_wall: "put OI wall",
  em_upper: "expected-move upper edge", em_lower: "expected-move lower edge",
};

function resolve(legs: ConceptLeg[], anchors: Concept["anchors"], rows: OCRow[]): Priced[] | string {
  const ks = rows.map((r) => r.strike).sort((a, b) => a - b);
  const out: Priced[] = [];
  for (const leg of legs) {
    const anchor = anchors?.[leg.anchor] ?? null;
    const label = ANCHOR_LABEL[leg.anchor] ?? leg.anchor;
    if (anchor == null) return `the ${label} is not available for this expiry`;
    const i = ks.indexOf(anchor);
    if (i < 0) return `the ${label} (${anchor}) is not a strike in the loaded chain`;
    // `step` counts strikes further out-of-the-money — up for calls, down for puts.
    const j = leg.right === "call" ? i + leg.step : i - leg.step;
    if (j < 0 || j >= ks.length) return `the ${leg.right} leg beside the ${label} falls outside the loaded strike range`;
    const strike = ks[j];
    const ltp = rows.find((r) => r.strike === strike)?.[leg.right].ltp;
    if (typeof ltp !== "number" || !Number.isFinite(ltp) || ltp <= 0) {
      return `the ${strike} ${leg.right} carries no live price, and no premium may be assumed for it`;
    }
    out.push({ ...leg, strike, ltp });
  }
  return out;
}

const intrinsic = (l: Priced, s: number) => l.right === "call" ? Math.max(0, s - l.strike) : Math.max(0, l.strike - s);
// Net premium: positive = credit taken in, negative = debit paid.
const netPremium = (legs: Priced[]) => legs.reduce((a, l) => a + (l.pos === "short" ? l.ltp : -l.ltp), 0);
const pnlAt = (legs: Priced[], net: number, s: number) =>
  net + legs.reduce((a, l) => a + (l.pos === "long" ? 1 : -1) * intrinsic(l, s), 0);

export function Payoff({ concept, rows, spot }: { concept: Concept; rows: OCRow[]; spot: number }) {
  const head = (
    <CardHeader icon={<GitCompareArrows size={16} />} title="Payoff at Expiry"
      subtitle={concept.name ?? "No structure named for this bias"}
      action={concept.name ? <Badge tone="neutral">Illustration</Badge> : undefined} />
  );
  const why = (reason: string) => (
    <Card>
      {head}
      <CardBody>
        {concept.note && <p className="mb-3 text-[12px] leading-relaxed text-mist">{concept.note}</p>}
        <p className="text-[12px] text-warn">Not drawn — {reason}.</p>
      </CardBody>
    </Card>
  );

  if (!concept.legs?.length) return why("this structure spans more than the one expiry loaded here");
  const legs = resolve(concept.legs, concept.anchors, rows);
  if (typeof legs === "string") return why(legs);

  const ks = legs.map((l) => l.strike);
  const pad = Math.max(...ks) - Math.min(...ks) || Math.abs(spot) * 0.01;
  const lo = Math.min(...ks, spot) - pad, hi = Math.max(...ks, spot) + pad;
  // Sample the kinks exactly plus an even grid, so the corners are the real
  // corners and the extremes are not an artefact of the sampling.
  const xs = [...new Set([...ks, lo, hi, ...Array.from({ length: 41 }, (_, i) => lo + (hi - lo) * i / 40)])]
    .sort((a, b) => a - b);
  const net = netPremium(legs);
  const pts = xs.map((s) => ({ s: Math.round(s), pnl: +pnlAt(legs, net, s).toFixed(2) }));
  const vals = pts.map((p) => p.pnl);
  const best = Math.max(...vals), worst = Math.min(...vals);

  // Breakevens: linear crossings of the zero line between adjacent samples.
  const be: number[] = [];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    if ((a.pnl <= 0 && b.pnl > 0) || (a.pnl >= 0 && b.pnl < 0)) {
      be.push(a.s + (b.s - a.s) * (0 - a.pnl) / (b.pnl - a.pnl));
    }
  }

  return (
    <Card>
      {head}
      <CardBody>
        {concept.note && <p className="mb-3 text-[12px] leading-relaxed text-mist">{concept.note}</p>}
        <MultiLine data={pts} xKey="s" height={200} baseline={0}
          valueFmt={(v) => signed(v, 0)} tooltipFmt={(v) => signed(v, 2)}
          series={[{ key: "pnl", label: "P/L at expiry", color: "var(--color-accent)" }]} />

        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11.5px] tnum md:grid-cols-4">
          <div><span className="text-muted">Net {net >= 0 ? "credit" : "debit"}</span> <span className="font-semibold text-frost">{num(Math.abs(net), { decimals: 2 })}</span></div>
          <div><span className="text-muted">Best</span> <span className="font-semibold text-up">{signed(best, 2)}</span></div>
          <div><span className="text-muted">Worst</span> <span className="font-semibold text-down">{signed(worst, 2)}</span></div>
          <div><span className="text-muted">Break-even</span> <span className="font-semibold text-frost">{be.length ? be.map((b) => b.toFixed(0)).join(" / ") : "—"}</span></div>
        </div>

        <table className="mt-3 w-full text-[11.5px] tnum">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-faint">
              <th className="py-1 text-left font-medium">Leg</th>
              <th className="py-1 text-right font-medium">Strike</th>
              <th className="py-1 text-right font-medium">Live LTP</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((l, i) => (
              <tr key={i} className="border-t border-line/50">
                <td className="py-1 text-mist">{l.pos === "long" ? "Long" : "Short"} {l.right}</td>
                <td className="py-1 text-right text-frost">{l.strike}</td>
                <td className="py-1 text-right text-frost">{num(l.ltp, { decimals: 2 })}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <p className="mt-3 text-[11px] leading-relaxed text-muted">
          Educational illustration of the named structure, per unit of the index and before costs.
          Premiums are the live LTPs above, taken from this chain at these strikes — nothing is assumed.
          Not a recommendation and not a price forecast.
        </p>
      </CardBody>
    </Card>
  );
}
