"use client";
import { compactCr, num } from "@/lib/format";
import { cn } from "@/lib/utils";

// A leg Upstox never priced arrives as null, not 0 — the parser's zero-guard
// (services/upstox.py::_greek) exists precisely because a thin quote prints a
// literal 0.0 that reads like a measurement. Every nullable here renders "—"
// via `num()`, which is null-safe by contract.
export type OCLeg = {
  oi: number; oiChg: number; vol: number; ltp: number;
  iv: number | null; delta: number | null; buildup: string | null;
};
export type OCRow = { strike: number; call: OCLeg; put: OCLeg };

// Build-up quadrant (price change × OI change, classified in
// services/fno_analysis.py::buildup). Null = a flat or absent print, which is a
// real state and not a quadrant.
const BUILDUP: Record<string, { code: string; cls: string; title: string }> = {
  long_buildup: { code: "LB", cls: "text-up", title: "Long build-up — price up, OI up" },
  short_buildup: { code: "SB", cls: "text-down", title: "Short build-up — price down, OI up" },
  short_covering: { code: "SC", cls: "text-accent", title: "Short covering — price up, OI down" },
  long_unwinding: { code: "LU", cls: "text-warn", title: "Long unwinding — price down, OI down" },
};

function BuildupChip({ b }: { b: string | null }) {
  const m = b ? BUILDUP[b] : null;
  if (!m) return null;
  return <span className={cn("ml-1 text-[9px] font-semibold", m.cls)} title={m.title}>{m.code}</span>;
}

// The option-chain grid (calls | strike | puts) — the ONLY chain surface in the
// app. OI-weighted heat behind each side. There is no mock fallback: an empty
// `rows` says so rather than drawing an invented chain.
export function OptionChain({ spot, data }: { spot: number; data: { atm: number | null; rows: OCRow[] } }) {
  const { atm, rows } = data;
  if (!rows.length) {
    return (
      <div className="rounded-[var(--radius-lg)] hairline bg-elevated px-5 py-10 text-center">
        <p className="text-[13px] font-medium text-frost">No live chain for this expiry</p>
        <p className="mt-1 text-[12px] text-muted">Upstox returned no priced strikes. Nothing is drawn in its place.</p>
      </div>
    );
  }
  const maxOI = Math.max(...rows.flatMap((r) => [r.call.oi, r.put.oi]), 1);

  const heat = (oi: number, side: "call" | "put") => {
    const a = (oi / maxOI) * 0.5;
    return { background: `color-mix(in oklab, ${side === "call" ? "var(--color-down)" : "var(--color-up)"} ${a * 100}%, transparent)` };
  };

  return (
    <div className="overflow-x-auto scrollbar-slim rounded-[var(--radius-lg)] hairline bg-elevated">
      <table className="w-full border-collapse text-[12px] tnum">
        <thead>
          <tr className="bg-surface text-[10px] uppercase tracking-wide text-muted">
            <th colSpan={5} className="border-b border-r border-line py-2 text-down">Calls</th>
            <th className="border-b border-line py-2 text-center text-frost">Strike</th>
            <th colSpan={5} className="border-b border-l border-line py-2 text-up">Puts</th>
          </tr>
          <tr className="bg-surface/60 text-[10px] text-faint">
            <th className="px-3 py-1.5 text-right font-medium">OI</th>
            <th className="px-3 py-1.5 text-right font-medium">Chg</th>
            <th className="px-3 py-1.5 text-right font-medium">IV</th>
            <th className="px-3 py-1.5 text-right font-medium">Δ</th>
            <th className="px-3 py-1.5 text-right font-medium">LTP</th>
            <th className="px-3 py-1.5 text-center font-medium border-x border-line">Price</th>
            <th className="px-3 py-1.5 text-right font-medium">LTP</th>
            <th className="px-3 py-1.5 text-right font-medium">Δ</th>
            <th className="px-3 py-1.5 text-right font-medium">IV</th>
            <th className="px-3 py-1.5 text-right font-medium">Chg</th>
            <th className="px-3 py-1.5 text-right font-medium">OI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isAtm = r.strike === atm;
            const itmCall = r.strike < spot, itmPut = r.strike > spot;
            return (
              <tr key={r.strike} className={cn("border-b border-line/50 hover:bg-raised/40", isAtm && "bg-accent/5")}>
                <td className="px-3 py-2 text-right text-mist" style={heat(r.call.oi, "call")}>{compactCr(r.call.oi)}</td>
                <td className={cn("whitespace-nowrap px-3 py-2 text-right", r.call.oiChg >= 0 ? "text-up" : "text-down")}>
                  {r.call.oiChg >= 0 ? "+" : ""}{compactCr(r.call.oiChg)}<BuildupChip b={r.call.buildup} />
                </td>
                <td className="px-3 py-2 text-right text-muted">{num(r.call.iv, { decimals: 1 })}</td>
                <td className="px-3 py-2 text-right text-mist">{num(r.call.delta, { decimals: 2 })}</td>
                <td className={cn("px-3 py-2 text-right font-medium", itmCall ? "text-frost" : "text-muted")}>{num(r.call.ltp, { decimals: 2 })}</td>
                <td className={cn("border-x border-line px-3 py-2 text-center font-bold", isAtm ? "text-accent" : "text-frost")}>{r.strike}{isAtm && <span className="ml-1 text-[9px] text-accent">ATM</span>}</td>
                <td className={cn("px-3 py-2 text-right font-medium", itmPut ? "text-frost" : "text-muted")}>{num(r.put.ltp, { decimals: 2 })}</td>
                <td className="px-3 py-2 text-right text-mist">{num(r.put.delta, { decimals: 2 })}</td>
                <td className="px-3 py-2 text-right text-muted">{num(r.put.iv, { decimals: 1 })}</td>
                <td className={cn("whitespace-nowrap px-3 py-2 text-right", r.put.oiChg >= 0 ? "text-up" : "text-down")}>
                  {r.put.oiChg >= 0 ? "+" : ""}{compactCr(r.put.oiChg)}<BuildupChip b={r.put.buildup} />
                </td>
                <td className="px-3 py-2 text-right text-mist" style={heat(r.put.oi, "put")}>{compactCr(r.put.oi)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Rendered under the chain by /options — the codes above are meaningless
// without it, and the null policy has to be stated, not assumed.
export function ChainLegend({ basis }: { basis: string | null }) {
  return (
    <p className="mt-2 text-[11px] leading-relaxed text-muted">
      Build-up: <span className="text-up">LB</span> long build-up · <span className="text-down">SB</span> short build-up ·{" "}
      <span className="text-accent">SC</span> short covering · <span className="text-warn">LU</span> long unwinding.{" "}
      {basis
        ? <>Classified from <span className="text-mist">{basis}</span> — each leg&apos;s own change against its prior close.</>
        : <>No leg moved enough to classify this session.</>}{" "}
      A dash means Upstox published no live value for that leg; it is never shown as 0.
    </p>
  );
}
