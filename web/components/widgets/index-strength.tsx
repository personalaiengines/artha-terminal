"use client";
import { useState } from "react";
import { TrendingUp } from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Segmented } from "@/components/ui/primitives";
import { MultiLine } from "@/components/ui/chart";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { cn } from "@/lib/utils";

// Relative strength: Nifty vs Bank Nifty vs Sensex, every series rebased to
// 100 at the start of the window so indices on completely different scales
// (24k / 57k / 77k) can be read on one axis. Answers the one question the
// price tape cannot — which part of the market is actually leading.
//
// This replaced a grid of Indian index cards that duplicated the topbar tape
// already present on every page.
//
// Backed by real daily OHLC in prices_daily (ingestion/index_history.py), one
// year deep for exactly these three symbols.

type Candle = { t: string; close: number };

const INDICES = [
  { symbol: "NIFTY", label: "Nifty 50", color: "var(--color-accent)" },
  { symbol: "BANKNIFTY", label: "Bank Nifty", color: "var(--color-ai)" },
  { symbol: "SENSEX", label: "Sensex", color: "var(--color-warn)" },
];

const RANGES: Record<string, number> = { "1M": 22, "3M": 66, "6M": 126, "1Y": 252 };

function useCandles(symbol: string, days: number): Candle[] {
  return useApi<Candle[]>(
    `/api/history?symbols=${symbol}&days=${days}&ohlc=1`, [],
    (j) => j.candles ?? [], POLL.history
  );
}

export function IndexStrength() {
  const [range, setRange] = useState("6M");
  const days = RANGES[range] ?? 126;

  // One call per index. Joining on the date means a session missing from one
  // series can never silently shift another out of alignment.
  const nifty = useCandles("NIFTY", days);
  const bank = useCandles("BANKNIFTY", days);
  const sensex = useCandles("SENSEX", days);
  const byIndex = [nifty, bank, sensex];

  const maps = byIndex.map((c) => new Map(c.map((r) => [r.t, r.close])));
  const dates = (nifty.length ? nifty : bank).map((r) => r.t)
    .filter((t) => maps.every((m) => m.get(t) != null));

  const bases = maps.map((m) => (dates.length ? m.get(dates[0])! : 0));
  const data = dates.map((t) => {
    const row: Record<string, unknown> = { t: t.slice(5) };  // MM-DD
    INDICES.forEach((idx, i) => {
      const base = bases[i];
      if (base) row[idx.symbol] = (maps[i].get(t)! / base) * 100;
    });
    return row;
  });

  const last = data[data.length - 1];
  const perf = INDICES.map((idx, i) => ({
    ...idx,
    pct: last ? (last[idx.symbol] as number) - 100 : null,
    level: dates.length ? maps[i].get(dates[dates.length - 1])! : null,
  })).sort((a, b) => (b.pct ?? -Infinity) - (a.pct ?? -Infinity));

  return (
    <Card className="mb-6">
      <CardHeader
        icon={<TrendingUp size={16} />}
        title="Index Performance"
        subtitle={`Rebased to 100 · ${range} — who is leading`}
        action={
          <Segmented size="sm" value={range} onChange={setRange}
            options={Object.keys(RANGES).map((r) => ({ label: r, value: r }))} />
        }
      />
      <CardBody>
        {data.length > 1 ? (
          <>
            <div className="mb-3 flex flex-wrap gap-x-6 gap-y-2">
              {perf.map((p, i) => (
                <div key={p.symbol} className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: p.color }} />
                  <span className="text-[12.5px] font-medium text-mist">{p.label}</span>
                  <span className={cn("text-[13px] font-semibold tnum",
                    (p.pct ?? 0) >= 0 ? "text-up" : "text-down")}>
                    {(p.pct ?? 0) >= 0 ? "+" : ""}{p.pct?.toFixed(2)}%
                  </span>
                  <span className="text-[11px] text-faint tnum">
                    {p.level?.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  </span>
                  {i === 0 && (
                    <span className="rounded-full bg-up/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-up">
                      Leading
                    </span>
                  )}
                </div>
              ))}
            </div>
            <MultiLine
              data={data}
              series={INDICES.map((i) => ({ key: i.symbol, label: i.label, color: i.color }))}
            />
          </>
        ) : (
          <p className="py-8 text-center text-[13px] text-muted">
            No index history yet — run the <span className="font-medium text-frost">Index OHLC History</span> job from Settings.
          </p>
        )}
      </CardBody>
    </Card>
  );
}
