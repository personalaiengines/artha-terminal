"use client";
import { Smile, TrendingUp } from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { MultiLine } from "@/components/ui/chart";
import type { OCRow } from "@/components/widgets/option-chain";

// Implied volatility, read two ways: across strikes at one expiry (the smile)
// and across expiries at the money (the term structure). Both draw only what
// Upstox actually priced — a leg or an expiry with no live IV is a GAP in the
// line, never a point at 0 (R17).

const CALL = "var(--color-down)";   // same side-colours the chain uses
const PUT = "var(--color-up)";
const ATM = "var(--color-accent)";

const ivFmt = (v: number) => `${v.toFixed(1)}%`;

export function IvSmile({ rows, spot, expiry }: { rows: OCRow[]; spot: number; expiry: string | null }) {
  // Keep strikes within ±10% of spot: the far wings are quoted so thinly that
  // they dominate the y-axis and flatten the part of the curve that is read.
  const near = rows.filter((r) => Math.abs(r.strike - spot) / spot <= 0.1);
  const data = near.map((r) => ({ strike: r.strike, call: r.call.iv, put: r.put.iv }));
  const missing = near.reduce((n, r) => n + (r.call.iv == null ? 1 : 0) + (r.put.iv == null ? 1 : 0), 0);
  const priced = near.length * 2 - missing;

  return (
    <Card>
      <CardHeader icon={<Smile size={16} />} title="IV Smile"
        subtitle={`Call and put IV by strike${expiry ? ` · ${expiry}` : ""} · strikes within 10% of spot`} />
      <CardBody>
        {priced > 0 ? (
          <MultiLine data={data} xKey="strike" height={240} baseline={null}
            valueFmt={ivFmt} tooltipFmt={ivFmt}
            series={[{ key: "call", label: "Call IV", color: CALL },
                     { key: "put", label: "Put IV", color: PUT }]} />
        ) : (
          <p className="py-10 text-center text-[12px] text-muted">
            No leg in this expiry carries a live IV quote. Nothing is plotted.
          </p>
        )}
        <p className="mt-2 text-[11px] text-muted">
          {missing > 0
            ? `${missing} of ${near.length * 2} legs shown carry no live IV — the line breaks there rather than dropping to zero.`
            : "Every leg shown carries a live IV quote."}
        </p>
      </CardBody>
    </Card>
  );
}

export type TermPoint = { expiry: string; atm: number | null; atm_iv: number | null; spot: number | null };
export type Term = { ok?: boolean; cap?: number; points?: TermPoint[]; unpriced?: string[]; complete?: boolean };

export function IvTerm({ term, listed }: { term: Term; listed: number }) {
  const points = term.points ?? [];
  const unpriced = term.unpriced ?? [];
  const cap = term.cap ?? 0;
  // The cap is stated from the payload, never hardcoded: the curve is the
  // nearest few expiries and must not read as the whole board.
  const subtitle = cap
    ? `ATM IV per expiry · nearest ${cap} of ${listed || cap} listed expiries`
    : "ATM IV per expiry";

  return (
    <Card>
      <CardHeader icon={<TrendingUp size={16} />} title="IV Term Structure" subtitle={subtitle} />
      <CardBody>
        {points.length ? (
          <MultiLine data={points.map((p) => ({ expiry: p.expiry, iv: p.atm_iv }))}
            xKey="expiry" height={220} baseline={null} valueFmt={ivFmt} tooltipFmt={ivFmt}
            series={[{ key: "iv", label: "ATM IV", color: ATM }]} />
        ) : (
          <p className="py-10 text-center text-[12px] text-muted">
            No listed expiry returned a live at-the-money IV quote.
          </p>
        )}
        {unpriced.length > 0 && (
          <p className="mt-2 text-[11px] text-warn">
            {unpriced.join(" and ")} {unpriced.length > 1 ? "carry" : "carries"} no live ATM quote,
            so {unpriced.length > 1 ? "they are" : "it is"} absent from the curve — not plotted at zero,
            and the gap is not interpolated.
          </p>
        )}
        {term.complete === false && points.length > 0 && (
          <p className="mt-1 text-[11px] text-muted">
            {points.length} of {cap} expiries priced.
          </p>
        )}
      </CardBody>
    </Card>
  );
}
