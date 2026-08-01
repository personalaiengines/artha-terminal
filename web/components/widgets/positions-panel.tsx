"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Briefcase, PlugZap } from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/primitives";
import { POLL } from "@/lib/poll";
import { num, signed, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// Read-only view of the live Upstox F&O book (GET /api/positions).
// This component renders data and nothing else — there is no control here, and
// no route behind it, that can place or change a trade.

export type Position = {
  symbol: string; qty: number; side: string;
  avg: number; ltp: number; pnl: number;
  product: string; exchange: string;
};
export type PositionBook = {
  ok: boolean; status?: string; message?: string;
  items: Position[]; closed?: number;
};

/** `NIFTY26AUG24400CE` -> 24400. null when the contract name carries no strike. */
export function strikeOf(symbol: string): number | null {
  const m = /(\d{4,7})(CE|PE)$/.exec(symbol.trim().toUpperCase());
  return m ? Number(m[1]) : null;
}

// useApi() is deliberately NOT used: it drops any ok:false response and keeps
// its fallback, which would render an expired Upstox session as an empty book —
// exactly the state that must never look like "you hold nothing" (R17).
export function usePositions(): PositionBook | null {
  const [book, setBook] = useState<PositionBook | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch("/api/positions")
        .then((r) => r.json())
        .then((j) => {
          if (!alive || !j) return;
          setBook({ ok: !!j.ok, status: j.status, message: j.message, items: j.items ?? [], closed: j.closed ?? 0 });
        })
        .catch(() => {
          if (alive) setBook({ ok: false, status: "unreachable", message: "Could not reach the positions service.", items: [] });
        });
    load();
    const id = setInterval(load, POLL.holdings);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return book;
}

export function PositionsPanel({ book }: { book: PositionBook | null }) {
  const closed = book?.closed ?? 0;

  return (
    <Card>
      <CardHeader
        icon={<Briefcase size={16} />}
        title="Live F&O Book"
        subtitle="Your open derivative contracts — read-only"
      />
      <CardBody className="pt-0">
        {book === null && <p className="py-8 text-center text-[12.5px] text-muted">Checking your F&amp;O book…</p>}

        {book && !book.ok && (
          <EmptyState
            icon={<PlugZap size={22} />}
            title="Upstox not connected"
            description={book.message || `The broker session is ${book.status ?? "unavailable"}, so your book cannot be read right now.`}
            action={
              <Link href="/upstox" className="inline-flex h-9 items-center rounded-[var(--radius-sm)] bg-raised px-4 text-[13px] font-medium text-frost hairline hover:bg-line">
                Reconnect Upstox
              </Link>
            }
          />
        )}

        {book?.ok && book.items.length === 0 && (
          <div className="py-8 text-center">
            <p className="text-[13px] font-semibold text-frost">No open F&amp;O positions</p>
            <p className="mt-1 text-[12px] text-muted">
              {closed > 0
                ? `${closed} contract${closed === 1 ? "" : "s"} traded and closed today. Nothing is open.`
                : "Nothing open in the derivatives segment right now."}
            </p>
          </div>
        )}

        {book?.ok && book.items.length > 0 && (
          <div className="overflow-x-auto scrollbar-slim rounded-[var(--radius-sm)] hairline">
            <table className="w-full text-[12px] tnum">
              <thead>
                <tr className="bg-surface text-[10px] uppercase tracking-wide text-faint">
                  <th className="px-3 py-2 text-left font-medium">Contract</th>
                  <th className="px-3 py-2 text-left font-medium">Side</th>
                  <th className="px-3 py-2 text-right font-medium">Qty</th>
                  <th className="px-3 py-2 text-right font-medium">Avg</th>
                  <th className="px-3 py-2 text-right font-medium">LTP</th>
                  <th className="px-3 py-2 text-right font-medium">P&amp;L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {book.items.map((p) => (
                  <tr key={`${p.symbol}-${p.product}`}>
                    <td className="px-3 py-2 text-left">
                      <span className="font-medium text-frost">{p.symbol}</span>
                      <span className="ml-1.5 text-[10px] text-faint">{p.exchange}</span>
                    </td>
                    <td className="px-3 py-2 text-left">
                      <Badge tone={p.side === "LONG" ? "up" : "down"}>{p.side}</Badge>
                    </td>
                    <td className="px-3 py-2 text-right text-mist">{p.qty}</td>
                    <td className="px-3 py-2 text-right text-mist">{num(p.avg)}</td>
                    <td className="px-3 py-2 text-right text-mist">{num(p.ltp)}</td>
                    <td className={cn("px-3 py-2 text-right font-semibold", trendClass(p.pnl))}>{signed(p.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="mt-3 text-[11px] leading-snug text-faint">
          Read-only. Positions come straight from the broker; nothing here can place or change a trade.
          {closed > 0 && book?.ok && book.items.length > 0 ? ` ${closed} contract(s) already closed today are counted, not listed.` : ""}
        </p>
      </CardBody>
    </Card>
  );
}
