// The shapes /api/fno/{index} and /api/history?ohlc=1 answer with.
//
// These lived in app/fno/page.tsx while that page was the only reader. The
// Charts page reads the same two routes for the same three indices, and a
// second hand-copied `Plan` is how the two would quietly disagree about what
// the API returns.

import type { Structure, Zone } from "@/components/widgets/level-ladder";

export type Candle = { t: string; open: number; high: number; low: number; close: number; volume: number };

export type Leg = { oi: number; oiChg: number; vol: number; iv: number; ltp: number; delta: number | null; buildup: string | null };
export type OCRow = { strike: number; call: Leg; put: Leg };
export type Quad = { legs: number; oi_change: number };
export type BuildupSummary = {
  call: Record<string, Quad | undefined>;
  put: Record<string, Quad | undefined>;
  unclassified?: { call: number; put: number };
  basis?: string | null;
};
export type Plan = {
  ok: boolean; index: string; name: string; spot: number; atm: number; pcr: number; maxPain: number; iv: number; vix: number | null;
  vixPctile: number | null; vixWindow: number; vixAsOf: string | null;
  callWall: number | null; putWall: number | null; biasLabel: string | null; biasScore: number | null;
  expiry: string | null;
  levels: { label: string; price: number; kind: string; crossed: boolean }[];
  zones: Zone[]; structure: Structure | null;
  buildupSummary: BuildupSummary | null; buildupBasis: string | null;
  rows: OCRow[];
};
