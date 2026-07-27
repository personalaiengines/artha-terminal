"use client";
import { optionChain } from "@/lib/data";
import { compactCr } from "@/lib/format";
import { cn } from "@/lib/utils";

type OCRow = { strike: number; call: { oi: number; oiChg: number; vol: number; iv: number; ltp: number }; put: { oi: number; oiChg: number; vol: number; iv: number; ltp: number } };

// Shared option-chain grid (calls | strike | puts). OI-weighted heat behind
// each side. Reused by F&O and Options pages. Pass `data` for a real Upstox
// chain; omit it to render the deterministic mock chain around `spot`.
export function OptionChain({ spot, seed = 7, data }: { spot: number; seed?: number; data?: { atm: number; rows: OCRow[] } }) {
  const mock = optionChain(spot, seed);
  const atm = data?.atm ?? mock.atm;
  const rows = data?.rows?.length ? data.rows : mock.rows;
  const maxOI = Math.max(...rows.flatMap((r) => [r.call.oi, r.put.oi]));

  const heat = (oi: number, side: "call" | "put") => {
    const a = (oi / maxOI) * 0.5;
    return { background: `color-mix(in oklab, ${side === "call" ? "var(--color-down)" : "var(--color-up)"} ${a * 100}%, transparent)` };
  };

  return (
    <div className="overflow-x-auto scrollbar-slim rounded-[var(--radius-lg)] hairline bg-elevated">
      <table className="w-full border-collapse text-[12px] tnum">
        <thead>
          <tr className="bg-surface text-[10px] uppercase tracking-wide text-muted">
            <th colSpan={3} className="border-b border-r border-line py-2 text-down">Calls</th>
            <th className="border-b border-line py-2 text-center text-frost">Strike</th>
            <th colSpan={3} className="border-b border-l border-line py-2 text-up">Puts</th>
          </tr>
          <tr className="bg-surface/60 text-[10px] text-faint">
            <th className="px-3 py-1.5 text-right font-medium">OI</th><th className="px-3 py-1.5 text-right font-medium">Chg</th><th className="px-3 py-1.5 text-right font-medium">LTP</th>
            <th className="px-3 py-1.5 text-center font-medium border-x border-line">Price</th>
            <th className="px-3 py-1.5 text-right font-medium">LTP</th><th className="px-3 py-1.5 text-right font-medium">Chg</th><th className="px-3 py-1.5 text-right font-medium">OI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isAtm = r.strike === atm;
            const itmCall = r.strike < spot, itmPut = r.strike > spot;
            return (
              <tr key={r.strike} className={cn("border-b border-line/50 hover:bg-raised/40", isAtm && "bg-accent/5")}>
                <td className="px-3 py-2 text-right text-mist" style={heat(r.call.oi, "call")}>{compactCr(r.call.oi)}</td>
                <td className={cn("px-3 py-2 text-right", r.call.oiChg >= 0 ? "text-up" : "text-down")}>{r.call.oiChg >= 0 ? "+" : ""}{compactCr(r.call.oiChg)}</td>
                <td className={cn("px-3 py-2 text-right font-medium", itmCall ? "text-frost" : "text-muted")}>{r.call.ltp}</td>
                <td className={cn("border-x border-line px-3 py-2 text-center font-bold", isAtm ? "text-accent" : "text-frost")}>{r.strike}{isAtm && <span className="ml-1 text-[9px] text-accent">ATM</span>}</td>
                <td className={cn("px-3 py-2 text-right font-medium", itmPut ? "text-frost" : "text-muted")}>{r.put.ltp}</td>
                <td className={cn("px-3 py-2 text-right", r.put.oiChg >= 0 ? "text-up" : "text-down")}>{r.put.oiChg >= 0 ? "+" : ""}{compactCr(r.put.oiChg)}</td>
                <td className="px-3 py-2 text-right text-mist" style={heat(r.put.oi, "put")}>{compactCr(r.put.oi)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
