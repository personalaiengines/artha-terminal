"use client";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown, ArrowUp, BarChart3, ChevronDown, ChevronRight, Download, Filter,
  Flame, History, PlugZap, Search, Snowflake, Table2, Target, X,
} from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/primitives";
import { HBars, ZeroArea, ZeroColumns } from "@/components/ui/chart";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { compactCr, inr, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PositionBook } from "@/components/widgets/positions-panel";

// The F&O money view: what the book made or lost, split into what is banked and
// what is still riding, session by session and contract by contract.
//
// Read-only and deliberately descriptive — it reports the broker's own realised
// and unrealised figures. It does not score the trading, project a return, or
// suggest a position.
//
// Shape: a summary strip that never leaves the viewport while the card is on
// screen, one filter bar that scopes everything, then three tabs. The tabs exist
// because all of this on one surface ran past three screens — the reader had to
// scroll to compare a number with the filter that produced it.
//
// Encoding note: green/up and red/down sit 3.8 ΔE apart under deuteranopia, so
// color never carries sign on its own here. Every signed number is written with
// an explicit + / −, the session charts diverge around a visible zero rule, every
// bridge bar is labelled in text, and the tables state each figure in words.
// The one exception is the optional "Bars" attribution view, which inherits
// HBars from components/ui/chart.tsx — it has no zero rule and no bar labels, so
// the bridge is the default and the bars are opt-in.

export type PnlDay = {
  date: string; realized: number; unrealized: number; net: number;
  open_count: number; closed_count: number; cumulative: number;
  // 'live' = read off the broker's position book that day (carries unrealised);
  // 'trades' = reconstructed from trade history, so booked P&L only.
  source: "live" | "trades";
};
export type PnlContract = {
  symbol: string; underlying: string; right: "CE" | "PE" | null;
  realized: number; unrealized: number; net: number; sessions: number;
};
export type PnlStats = {
  sessions: number; total: number; realized: number; unrealized: number;
  best: number | null; worst: number | null; green_days: number; red_days: number;
  win_rate: number | null; avg_green: number | null; avg_red: number | null;
  max_drawdown: number; streak: number;
};

// Which measure the charts, tiles and tables read. "Booked" is money that has
// settled; "Open" is a mark-to-market quote that can still evaporate. Keeping
// them switchable rather than merged is the whole point of the split.
const BASES = [
  { label: "Net", value: "net" }, { label: "Booked", value: "realized" }, { label: "Open", value: "unrealized" },
] as const;
type Basis = (typeof BASES)[number]["value"];

const RESULTS = [
  { label: "All", value: "all" }, { label: "Winners", value: "win" }, { label: "Losers", value: "loss" },
] as const;
type Result = (typeof RESULTS)[number]["value"];

const RANGES = [
  { label: "1M", value: "1m" }, { label: "3M", value: "3m" }, { label: "6M", value: "6m" },
  { label: "YTD", value: "ytd" }, { label: "All", value: "all" },
] as const;
type Range = (typeof RANGES)[number]["value"];

const TABS = [
  { id: "overview", label: "Overview" }, { id: "sessions", label: "Sessions" }, { id: "contracts", label: "Contracts" },
] as const;
type Tab = (typeof TABS)[number]["id"];

/** Local calendar date, not `toISOString` — that is UTC, and before 05:30 IST it
 *  names yesterday, which would silently shorten every preset by a day. */
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** A preset → the ISO window the API slices on. "All" widens to the whole record. */
function rangeIso(r: Range): { from?: string; to?: string } {
  if (r === "all") return {};
  const now = new Date();
  const to = iso(now);
  if (r === "ytd") return { from: `${now.getFullYear()}-01-01`, to };
  const back = new Date(now);
  back.setDate(back.getDate() - ({ "1m": 30, "3m": 90, "6m": 182 } as const)[r]);
  return { from: iso(back), to };
}

/** "+₹12,340.00" / "−₹980.50". Zero carries no sign. */
function money(n: number | null | undefined, compact = false) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  const body = compact ? "₹" + compactCr(Math.abs(n)) : inr(Math.abs(n));
  return (n > 0 ? "+" : n < 0 ? "−" : "") + body;
}

const dayLabel = (isoDate: string) =>
  new Date(isoDate + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short" });

/** `NIFTY 26AUG26 24400 CE` / `NIFTY26AUG24400CE` → something that fits an axis. */
const shortName = (symbol: string) => {
  const parts = symbol.trim().split(/\s+/);
  if (parts.length > 1) return `${parts[0].slice(0, 4)} ${parts[parts.length - 2]}${parts[parts.length - 1]}`;
  return symbol.replace(/^([A-Z]+)/, "$1 ").slice(0, 14);
};

/** RFC-4180 enough for a spreadsheet: quote anything holding a comma, quote or
 *  newline, and double the inner quotes. */
function downloadCsv(name: string, rows: (string | number | null)[][]) {
  const body = rows
    .map((r) => r.map((c) => {
      const s = c == null ? "" : String(c);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(","))
    .join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + body], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Controls. Built inline rather than reusing components/ui/primitives.tsx —
// `Segmented` and `Tabs` there carry hardcoded framer-motion layoutIds ("seg",
// "tab-underline") and the F&O page already renders a `Segmented` for the index
// switcher, so a second one would make the highlight fly across the page.
// ---------------------------------------------------------------------------

function Seg<T extends string>({
  value, onChange, options, label,
}: { value: T; onChange: (v: T) => void; options: readonly { label: string; value: T }[]; label?: string }) {
  return (
    <div className="flex items-center gap-1.5">
      {label && <span className="text-[10px] font-medium uppercase tracking-wide text-faint">{label}</span>}
      <div role="group" aria-label={label} className="flex gap-0.5 rounded-[var(--radius-sm)] bg-void p-0.5 hairline">
        {options.map((o) => (
          <button key={o.value} type="button" onClick={() => onChange(o.value)} aria-pressed={o.value === value}
            className={cn(
              "ring-focus cursor-pointer rounded-[6px] px-2.5 py-1 text-[11.5px] font-medium transition-colors duration-150",
              o.value === value ? "bg-raised text-frost shadow-[var(--shadow-sm)]" : "text-muted hover:text-mist"
            )}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** A removable summary of one non-default filter. The bar states what is on
 *  rather than making the reader re-open the popover to find out. */
function Pill({ children, name, onClear }: { children: React.ReactNode; name: string; onClear: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft/50 py-0.5 pl-2.5 pr-1 text-[11px] font-medium text-accent hairline">
      {children}
      <button type="button" onClick={onClear} aria-label={`Remove filter: ${name}`}
        className="ring-focus cursor-pointer rounded-full p-0.5 transition-colors hover:bg-accent/20">
        <X size={11} />
      </button>
    </span>
  );
}

function TooltipBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="glass rounded-[var(--radius-sm)] px-3 py-2 text-[12px] shadow-[var(--shadow-lg)] hairline">{children}</div>
  );
}

type SortDir = 1 | -1;
function Th({
  label, sortKey, sort, onSort, align = "right", className,
}: {
  label: string; sortKey?: string; sort: { key: string; dir: SortDir };
  onSort?: (k: string) => void; align?: "left" | "right"; className?: string;
}) {
  const active = sort.key === sortKey;
  if (!sortKey || !onSort) {
    return <th className={cn("px-3 py-2 font-medium", align === "left" ? "text-left" : "text-right", className)}>{label}</th>;
  }
  return (
    <th aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
      className={cn("px-0 py-0 font-medium", className)}>
      <button type="button" onClick={() => onSort(sortKey)}
        className={cn(
          "ring-focus flex w-full cursor-pointer items-center gap-1 px-3 py-2 transition-colors duration-150 hover:text-mist",
          align === "left" ? "justify-start" : "justify-end", active && "text-mist"
        )}>
        {label}
        {active
          ? (sort.dir === 1 ? <ArrowUp size={10} /> : <ArrowDown size={10} />)
          : <ArrowDown size={10} className="opacity-0 transition-opacity group-hover/t:opacity-40" />}
      </button>
    </th>
  );
}

/** Toggle-to-reverse sorting, defaulting to descending on a fresh column —
 *  "biggest first" is what anyone means by clicking a money header. */
function useSort<K extends string>(initial: K) {
  const [sort, setSort] = useState<{ key: K; dir: SortDir }>({ key: initial, dir: -1 });
  const toggle = (k: string) =>
    setSort((s) => (s.key === k ? { key: s.key, dir: (s.dir === 1 ? -1 : 1) as SortDir } : { key: k as K, dir: -1 }));
  return [sort, toggle] as const;
}

function KPI({ label, value, tone, sub, children }: {
  label: React.ReactNode; value: string; tone?: string; sub?: React.ReactNode; children?: React.ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-[var(--radius-md)] bg-void px-3 py-2.5 hairline">
      <div className="truncate text-[10px] font-medium uppercase tracking-wide text-muted">{label}</div>
      {/* Proportional figures on tile values — tabular digits read loose at
          display sizes; the tables below are where numbers need to align. */}
      <div className={cn("mt-1 text-[17px] font-semibold leading-none tracking-tight", tone ?? "text-frost")}>{value}</div>
      {sub && <div className="mt-1 truncate text-[10.5px] leading-snug text-faint">{sub}</div>}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Attribution bridge (waterfall). Which contracts carried the window's total,
// and in what order they add up to it. Bars are capped at 9 named contracts +
// an aggregated tail + the total, because a bridge stops being readable past
// about a dozen steps.
// ---------------------------------------------------------------------------

function Bridge({ items, height = 300 }: { items: { name: string; full: string; value: number }[]; height?: number }) {
  const data = useMemo(() => {
    const top = items.slice(0, 9);
    const tail = items.slice(9);
    const rest = tail.reduce((a, c) => a + c.value, 0);
    const steps = [...top, ...(tail.length ? [{ name: `Other ×${tail.length}`, full: `${tail.length} smaller contracts`, value: rest }] : [])];
    let run = 0;
    const out = steps.map((s) => {
      const start = run;
      run += s.value;
      return {
        name: s.name, full: s.full, value: s.value, total: false,
        base: Math.min(start, run), span: Math.abs(s.value) || 0.0001,
        label: money(s.value, true),
      };
    });
    // "Filtered", not "Window": these are the contracts left after the Result and
    // Underlying filters, and the API only ever returns the 60 biggest movers.
    // Calling this the window total would print a different number from the
    // summary strip under a name that claims to be the same one.
    out.push({
      name: "Total shown", full: "Total of the contracts shown", value: run, total: true,
      base: Math.min(0, run), span: Math.abs(run) || 0.0001, label: money(run, true),
    });
    return out;
  }, [items]);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 18, right: 6, left: 0, bottom: 34 }} barCategoryGap="22%">
        <CartesianGrid stroke="var(--color-line)" vertical={false} opacity={0.4} />
        <XAxis dataKey="name" stroke="var(--color-faint)" fontSize={9.5} tickLine={false} axisLine={false}
          interval={0} angle={-32} textAnchor="end" height={40} />
        <YAxis stroke="var(--color-faint)" fontSize={10} tickLine={false} axisLine={false} width={54}
          orientation="right" tickFormatter={(v) => money(Number(v), true)} />
        <ReferenceLine y={0} stroke="var(--color-line)" ifOverflow="extendDomain" />
        <Tooltip cursor={{ fill: "var(--color-raised)", opacity: 0.3 }}
          content={({ active, payload }) => {
            const d = active && payload?.length ? (payload[0].payload as (typeof data)[number]) : null;
            return d ? (
              <TooltipBox>
                <div className="mb-0.5 max-w-[220px] text-muted">{d.full}</div>
                <div className={cn("font-semibold tnum", d.total ? "text-frost" : trendClass(d.value))}>
                  {money(d.value)}
                </div>
              </TooltipBox>
            ) : null;
          }} />
        {/* The invisible pedestal each step floats on. */}
        <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="span" stackId="w" animationDuration={700} maxBarSize={46} radius={[3, 3, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.total ? "var(--color-accent)" : d.value >= 0 ? "var(--color-up)" : "var(--color-down)"} />
          ))}
          {/* Sign is written on every bar — the bridge must read without color. */}
          <LabelList dataKey="label" position="top" fontSize={9.5} fill="var(--color-mist)" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------

export function PnlTracker({ book }: { book: PositionBook | null }) {
  const [range, setRange] = useState<Range>("all");
  const [basis, setBasis] = useState<Basis>("net");
  const [result, setResult] = useState<Result>("all");
  const [unders, setUnders] = useState<string[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [attribution, setAttribution] = useState<"bridge" | "bars">("bridge");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sync, setSync] = useState<{ busy: boolean; note: string | null }>({ busy: false, note: null });
  const [daySort, sortDays] = useSort<"date" | "realized" | "unrealized" | "net" | "cumulative">("date");
  const [conSort, sortContracts] = useSort<"symbol" | "sessions" | "realized" | "unrealized" | "net">("net");

  const popRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const onTabKey = (e: React.KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n =
      e.key === "ArrowRight" ? (i + 1) % TABS.length
        : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length
          : e.key === "Home" ? 0
            : e.key === "End" ? TABS.length - 1
              : -1;
    if (n < 0) return;
    e.preventDefault();
    setTab(TABS[n].id);
    tabRefs.current[n]?.focus();
  };

  // Light dismiss for the overflow popover. Pointerdown rather than click so the
  // panel closes on the same gesture that starts elsewhere.
  useEffect(() => {
    if (!filtersOpen) return;
    const onDown = (e: PointerEvent) => {
      if (!popRef.current?.contains(e.target as Node)) setFiltersOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setFiltersOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [filtersOpen]);

  // Pull the record back from Upstox trade history. The positions API only ever
  // knows today, so without this every window shows the same single session.
  const backfill = async () => {
    setSync({ busy: true, note: null });
    try {
      const r = await fetch("/api/fno/pnl/backfill", { method: "POST" }).then((x) => x.json());
      setSync({
        busy: false,
        note: r?.ok
          ? `Rebuilt ${r.sessions} session${r.sessions === 1 ? "" : "s"} from ${r.trades} trades (${r.from} → ${r.to}).`
          : r?.message ?? "Backfill failed.",
      });
      if (r?.ok) window.dispatchEvent(new Event("artha:refresh"));
    } catch {
      setSync({ busy: false, note: "Could not reach the API." });
    }
  };

  // The slice is cut server-side, so a month's view carries a month's rows —
  // that is what keeps the panel short enough to read without a scroller.
  const { from, to } = rangeIso(range);
  const qs = [from && `from=${from}`, to && `to=${to}`].filter(Boolean).join("&");
  const hist = useApi<{ days: PnlDay[]; contracts: PnlContract[]; months: string[]; stats: PnlStats | null }>(
    `/api/fno/pnl${qs ? `?${qs}` : ""}`,
    { days: [], contracts: [], months: [], stats: null },
    (j) => ({ days: j.days ?? [], contracts: j.contracts ?? [], months: j.months ?? [], stats: j.stats ?? null }),
    POLL.fnoPnl
  );
  const { days, contracts, stats } = hist;

  // Today comes from the live book when the broker is reachable and from the
  // recorded row when it is not — the tracker has to keep reading after the
  // daily Upstox token expires, which is most of the time anyone opens it.
  const recorded = days.length ? days[days.length - 1] : null;
  const today = book?.ok
    ? { realized: book.realized ?? 0, unrealized: book.unrealized ?? 0, net: book.net ?? 0, live: true }
    : recorded
      ? { realized: recorded.realized, unrealized: recorded.unrealized, net: recorded.net, live: false }
      : null;

  // Offered only where the record actually has contracts — an underlying that
  // matches nothing is a dead end the user has to discover by clicking it.
  const underlyings = useMemo(
    () => Array.from(new Set(contracts.map((c) => c.underlying))).sort(),
    [contracts]
  );

  const shown = useMemo(() => {
    const q = query.trim().toUpperCase();
    return contracts.filter((c) =>
      (unders.length === 0 || unders.includes(c.underlying)) &&
      (result === "all" || (result === "win" ? c[basis] > 0 : c[basis] < 0)) &&
      (!q || c.symbol.toUpperCase().includes(q)) &&
      c[basis] !== 0
    );
  }, [contracts, unders, result, basis, query]);

  const basisLabel = BASES.find((b) => b.value === basis)!.label;

  // Why the contract list is empty, said accurately — this always returns a
  // sentence, never null, because both call sites render it straight into a
  // panel and a blank box explains nothing.
  //
  // Three different causes get three different sentences. Basis in particular is
  // not one of the filters the bar shows or "Clear all" resets, and every session
  // rebuilt from trade history books 0 unrealised — so switching to Open on a
  // backfilled record empties the list with no filter set. Blaming "this filter"
  // there sends the reader hunting for a control that is already off.
  const emptyReason = useMemo(() => {
    // A day with no open positions still writes a daily row and no contract rows,
    // so "sessions recorded, contracts none" is a normal state, not a filter miss.
    if (contracts.length === 0) return "No contracts recorded in this window.";
    if (!contracts.some((c) => c[basis] !== 0)) {
      return basis === "unrealized"
        ? "No contract carries an open mark-to-market figure in this window — sessions rebuilt from trade history book realised P&L only."
        : `No contract has a non-zero ${basisLabel.toLowerCase()} figure in this window.`;
    }
    return "No contract matches this filter in the selected window.";
  }, [contracts, basis, basisLabel]);

  const sortedContracts = useMemo(() => {
    const { key, dir } = conSort;
    return [...shown].sort((a, b) =>
      key === "symbol" ? dir * a.symbol.localeCompare(b.symbol) : dir * ((a[key] as number) - (b[key] as number))
    );
  }, [shown, conSort]);

  const sortedDays = useMemo(() => {
    const { key, dir } = daySort;
    return [...days].sort((a, b) =>
      key === "date" ? dir * a.date.localeCompare(b.date) : dir * (a[key] - b[key])
    );
  }, [days, daySort]);

  // The curve is a running total of whichever basis is selected, recomputed
  // here rather than read off `cumulative` — that column only ever tracks net.
  const curve = useMemo(() => {
    let run = 0;
    return days.map((d) => ({ t: dayLabel(d.date), v: (run += d[basis]) }));
  }, [days, basis]);
  const columns = days.map((d) => ({ t: dayLabel(d.date), v: d[basis] }));

  const bridgeItems = useMemo(
    () => [...shown]
      .sort((a, b) => Math.abs(b[basis]) - Math.abs(a[basis]))
      .map((c) => ({ name: shortName(c.symbol), full: c.symbol, value: c[basis] })),
    [shown, basis]
  );

  const reconstructed = days.filter((d) => d.source === "trades").length;
  const basisTotal = basis === "net" ? stats?.total : basis === "realized" ? stats?.realized : stats?.unrealized;
  const streak = stats?.streak ?? 0;
  // Denominator for a contract's share of the window: gross turnover of the
  // filtered set, so a book that nets to ~zero still divides sensibly.
  const gross = useMemo(() => shown.reduce((a, c) => a + Math.abs(c[basis]), 0), [shown, basis]);
  const extraFilters = (result !== "all" ? 1 : 0) + (unders.length ? 1 : 0);
  const clearAll = () => { setResult("all"); setUnders([]); setQuery(""); };

  const exportCsv = () => {
    const stamp = `${from ?? "start"}_${to ?? "latest"}`;
    if (tab === "contracts") {
      downloadCsv(`artha-fno-pnl-contracts_${stamp}.csv`,
        [["Contract", "Underlying", "Right", "Sessions", "Booked", "Open", "Net"],
        ...sortedContracts.map((c) => [c.symbol, c.underlying, c.right ?? "", c.sessions, c.realized, c.unrealized, c.net])]);
    } else {
      downloadCsv(`artha-fno-pnl-sessions_${stamp}.csv`,
        [["Session", "Booked", "Open", "Net", "Cumulative", "Open contracts", "Closed", "Source"],
        ...sortedDays.map((d) => [d.date, d.realized, d.unrealized, d.net, d.cumulative, d.open_count, d.closed_count, d.source])]);
    }
  };

  const emptySlice = days.length === 0 && hist.months.length > 0;
  const emptyRecord = days.length === 0 && hist.months.length === 0;

  const iconBtn =
    "ring-focus inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] bg-void px-2.5 py-1.5 text-[11.5px] font-medium text-mist transition-colors duration-150 hairline hover:bg-raised hover:text-frost disabled:cursor-not-allowed disabled:opacity-60";

  return (
    <Card variant="elevated">
      <CardHeader
        icon={<BarChart3 size={16} />}
        title="F&O P&L Tracker"
        subtitle={
          days.length
            ? `${stats?.sessions ?? days.length} session${stats?.sessions === 1 ? "" : "s"} · ${dayLabel(days[0].date)} → ${dayLabel(days[days.length - 1].date)}`
            : "Every session ARTHA has recorded, by contract and by day"
        }
        action={
          <div className="flex items-center gap-2">
            {streak !== 0 && (
              <Badge tone={streak > 0 ? "up" : "down"}>
                {streak > 0 ? <Flame size={11} /> : <Snowflake size={11} />}
                {Math.abs(streak)} {streak > 0 ? "green" : "red"}
              </Badge>
            )}
            <button type="button" onClick={exportCsv} disabled={days.length === 0} className={iconBtn}
              title={tab === "contracts" ? "Download the filtered contracts as CSV" : "Download the filtered sessions as CSV"}>
              <Download size={12} />CSV
            </button>
            <button type="button" onClick={backfill} disabled={sync.busy} className={iconBtn}>
              <History size={12} className={sync.busy ? "animate-spin" : undefined} />
              {sync.busy ? "Rebuilding…" : "Sync history"}
            </button>
          </div>
        }
      />

      <CardBody className="space-y-4">
        {/* ---- summary strip: pinned under the app topbar (h-14) so the number
             the filters are moving stays on screen while the tables scroll ---- */}
        <div className={cn("sticky top-14 z-20 -mx-5 border-y border-line bg-elevated/92 px-5 py-3 backdrop-blur-xl",
          emptyRecord && "hidden")}>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            <div className="min-w-0 rounded-[var(--radius-md)] bg-void px-3.5 py-2.5 hairline sm:col-span-2 xl:col-span-1">
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted">
                {basisLabel} · {RANGES.find((r) => r.value === range)!.label}
              </div>
              <div className={cn("mt-1 text-[27px] font-semibold leading-none tracking-tight", trendClass(basisTotal))}>
                {money(basisTotal, true)}
              </div>
              <div className="mt-1 truncate text-[10.5px] text-faint">
                Booked {money(stats?.realized, true)} · open {money(stats?.unrealized, true)}
              </div>
            </div>

            <KPI
              label={today?.live ? "Today · live" : recorded ? `Last recorded · ${dayLabel(recorded.date)}` : "Today"}
              value={money(today?.[basis], true)}
              tone={trendClass(today?.[basis])}
              sub={book?.ok
                ? `${book.items.length} open · ${book.closed ?? 0} closed`
                : book ? `Broker ${book.status ?? "unavailable"}` : "Checking the book…"}
            />

            <KPI label="Win rate" value={stats?.win_rate == null ? "—" : `${stats.win_rate}%`}
              sub={`${stats?.green_days ?? 0} green · ${stats?.red_days ?? 0} red`}>
              {/* A ratio against a limit is a meter, not a chart. */}
              <div className="mt-1.5 flex h-1 overflow-hidden rounded-full bg-line">
                <div className="bg-up" style={{ width: `${stats?.win_rate ?? 0}%` }} />
              </div>
            </KPI>

            <KPI label="Max drawdown" value={money(stats?.max_drawdown, true)} tone={trendClass(stats?.max_drawdown)}
              sub={`Peak-to-trough on the curve`} />

            <KPI label="Best / worst session" value={money(stats?.best, true)} tone={trendClass(stats?.best)}
              sub={<span className={trendClass(stats?.worst)}>worst {money(stats?.worst, true)}</span>} />
          </div>
        </div>

        {/* ---- one filter bar, scoping everything below it ---- */}
        <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius-md)] bg-surface/60 px-3 py-2 hairline",
          emptyRecord && "hidden")}>
          <Seg label="Range" value={range} onChange={setRange} options={RANGES} />
          <Seg label="Basis" value={basis} onChange={setBasis} options={BASES} />

          <div ref={popRef} className="relative">
            <button type="button" onClick={() => setFiltersOpen((v) => !v)}
              aria-expanded={filtersOpen} aria-haspopup="dialog"
              className={cn(
                "ring-focus inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-[11.5px] font-medium transition-colors duration-150 hairline",
                extraFilters || filtersOpen ? "bg-raised text-frost" : "bg-void text-mist hover:text-frost"
              )}>
              <Filter size={12} />Filters
              {extraFilters > 0 && (
                <span className="rounded-full bg-accent px-1.5 text-[9.5px] font-bold leading-[15px] text-white">{extraFilters}</span>
              )}
              <ChevronDown size={11} className={cn("transition-transform duration-150", filtersOpen && "rotate-180")} />
            </button>

            {filtersOpen && (
              <div role="dialog" aria-label="More filters"
                className="glass rise absolute left-0 top-full z-30 mt-1.5 w-64 rounded-[var(--radius-md)] p-3 shadow-[var(--shadow-lg)] hairline">
                <div className="text-[10px] font-medium uppercase tracking-wide text-faint">Result</div>
                <div className="mt-1.5"><Seg value={result} onChange={setResult} options={RESULTS} /></div>

                <div className="mt-3 flex items-center justify-between">
                  <span className="text-[10px] font-medium uppercase tracking-wide text-faint">Underlying</span>
                  {unders.length > 0 && (
                    <button type="button" onClick={() => setUnders([])}
                      className="ring-focus cursor-pointer text-[10.5px] text-accent hover:underline">reset</button>
                  )}
                </div>
                {underlyings.length === 0 ? (
                  <p className="mt-1.5 text-[11.5px] text-faint">No contracts in this window.</p>
                ) : (
                  <div className="mt-1.5 flex max-h-40 flex-wrap gap-1 overflow-y-auto scrollbar-slim">
                    {underlyings.map((u) => {
                      const on = unders.includes(u);
                      return (
                        <button key={u} type="button" aria-pressed={on}
                          onClick={() => setUnders((s) => (on ? s.filter((x) => x !== u) : [...s, u]))}
                          className={cn(
                            "ring-focus cursor-pointer rounded-[var(--radius-xs)] px-2 py-1 text-[11px] font-medium transition-colors duration-150 hairline",
                            on ? "bg-accent-soft/60 text-accent" : "bg-void text-muted hover:text-mist"
                          )}>
                          {u}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Active non-default filters, stated in the bar rather than hidden
              behind the popover that set them. */}
          {result !== "all" && (
            <Pill name={result === "win" ? "Winners" : "Losers"} onClear={() => setResult("all")}>
              {result === "win" ? "Winners" : "Losers"}
            </Pill>
          )}
          {unders.map((u) => (
            <Pill key={u} name={u} onClear={() => setUnders((s) => s.filter((x) => x !== u))}>{u}</Pill>
          ))}
          {query.trim() && (
            <Pill name={`search ${query.trim()}`} onClear={() => setQuery("")}>“{query.trim()}”</Pill>
          )}
          {(extraFilters > 0 || query.trim()) && (
            <button type="button" onClick={clearAll}
              className="ring-focus ml-auto cursor-pointer text-[11px] font-medium text-muted transition-colors hover:text-frost">
              Clear all
            </button>
          )}
        </div>

        {/* A rebuild can run for minutes; its outcome has to be announced, not
            just drawn. The node is always rendered and never display:none — a
            live region has to be in the accessibility tree BEFORE the text lands
            in it, or the mutation is not observed and nothing is announced. Only
            the box styling is conditional; empty, it collapses to zero height. */}
        <p role="status" aria-live="polite"
          className={cn((sync.busy || sync.note) && "rounded-[var(--radius-sm)] bg-void px-3 py-2 text-[12px] text-mist hairline")}>
          {sync.busy ? "Rebuilding the record from trade history…" : sync.note}
        </p>

        {emptySlice ? (
          /* The record has sessions, just none in this slice — offering "Sync
             history" here would be answering a question nobody asked. */
          <p className="rounded-[var(--radius-sm)] bg-void px-3 py-8 text-center text-[12.5px] text-muted hairline">
            No sessions recorded in this window ({RANGES.find((r) => r.value === range)!.label}).{" "}
            <button type="button" onClick={() => setRange("all")} className="ring-focus cursor-pointer text-accent hover:underline">
              Widen to all time
            </button>
          </p>
        ) : emptyRecord ? (
          <EmptyState icon={<Target size={22} />} title="No sessions recorded yet"
            description="Sync history pulls your executed F&O trades from Upstox and rebuilds the record from them. After that, each live read of the book keeps it current."
            action={
              <button type="button" onClick={backfill} disabled={sync.busy}
                className="ring-focus inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] bg-raised px-4 text-[13px] font-medium text-frost transition-colors hairline hover:bg-line disabled:opacity-60">
                <History size={13} />{sync.busy ? "Rebuilding…" : "Sync history"}
              </button>
            } />
        ) : (
          <>
            {/* ---- tabs ---- */}
            {/* Full tablist pattern, not just the roles: roving tabindex so the
                group is one tab stop, arrow/Home/End to move within it. */}
            <div role="tablist" aria-label="P&L views" className="flex items-center gap-1 border-b border-line">
              {TABS.map((t, i) => (
                <button key={t.id} type="button" role="tab" id={`pnl-tab-${t.id}`}
                  aria-selected={tab === t.id} aria-controls={`pnl-panel-${t.id}`}
                  tabIndex={tab === t.id ? 0 : -1}
                  ref={(el) => { tabRefs.current[i] = el; }}
                  onKeyDown={(e) => onTabKey(e, i)}
                  onClick={() => setTab(t.id)}
                  className={cn(
                    "ring-focus relative cursor-pointer px-3.5 py-2 text-[12.5px] font-medium transition-colors duration-150",
                    tab === t.id ? "text-frost" : "text-muted hover:text-mist"
                  )}>
                  {t.label}
                  {t.id === "contracts" && (
                    <span className="ml-1.5 text-[10.5px] text-faint tnum">{shown.length}</span>
                  )}
                  {t.id === "sessions" && (
                    <span className="ml-1.5 text-[10.5px] text-faint tnum">{days.length}</span>
                  )}
                  {tab === t.id && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent" />}
                </button>
              ))}
            </div>

            {/* No tabIndex: every panel here holds its own focusable controls, so
                APG does not want the panel itself in the tab order. */}
            <div key={tab} role="tabpanel" id={`pnl-panel-${tab}`} aria-labelledby={`pnl-tab-${tab}`}
              className="rise">
              {tab === "overview" && (
                <div className="grid gap-5 xl:grid-cols-5">
                  <div className="xl:col-span-3">
                    <div className="mb-1.5 flex items-baseline justify-between gap-3">
                      <span className="text-[11px] font-medium uppercase tracking-wide text-muted">Cumulative {basisLabel.toLowerCase()}</span>
                      <span className="truncate text-[11px] text-faint">running total, {dayLabel(days[0].date)} → {dayLabel(days[days.length - 1].date)}</span>
                    </div>
                    <ZeroArea data={curve} height={230} label={`Cumulative ${basisLabel.toLowerCase()}`}
                      color={(basisTotal ?? 0) >= 0 ? "var(--color-up)" : "var(--color-down)"}
                      valueFmt={(v) => money(v, true)} />
                  </div>
                  <div className="xl:col-span-2">
                    <div className="mb-1.5 flex items-baseline justify-between">
                      <span className="text-[11px] font-medium uppercase tracking-wide text-muted">Per session</span>
                      <span className="text-[11px] text-faint">above / below zero</span>
                    </div>
                    <ZeroColumns data={columns} height={230} valueFmt={(v) => money(v, true)} />
                  </div>

                  <div className="xl:col-span-5">
                    <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                      <span className="text-[11px] font-medium uppercase tracking-wide text-muted">
                        Attribution · {shown.length} contract{shown.length === 1 ? "" : "s"}
                        <span className="ml-2 normal-case tracking-normal text-faint">
                          {unders.length === 0 ? "all underlyings" : unders.join(", ")}
                          {result !== "all" ? ` · ${result === "win" ? "winners" : "losers"} only` : ""}
                        </span>
                      </span>
                      <Seg value={attribution} onChange={setAttribution}
                        options={[{ label: "Bars", value: "bars" as const }, { label: "Bridge", value: "bridge" as const }]} />
                    </div>
                    {shown.length === 0 ? (
                      <p className="rounded-[var(--radius-sm)] bg-void px-3 py-6 text-center text-[12.5px] text-muted hairline">
                        {emptyReason}
                      </p>
                    ) : attribution === "bars" ? (
                      <HBars
                        data={bridgeItems.slice(0, 12).map((c) => ({ name: c.name, value: c.value }))}
                        height={Math.max(140, Math.min(bridgeItems.length, 12) * 28)}
                        fmt={(v) => money(v)} />
                    ) : (
                      <>
                        <Bridge items={bridgeItems} />
                        <p className="mt-1 text-[10.5px] leading-snug text-faint">
                          Each bar starts where the last one ended, so the steps add up to the total on the right. That total
                          is the contracts shown here, not the window — the filters above it and the API&apos;s 60-mover cap
                          both narrow the set{contracts.length >= 60 ? ", and this window is at that cap" : ""}. Past nine
                          contracts the tail is aggregated: a bridge stops being readable beyond about a dozen steps.
                        </p>
                      </>
                    )}
                  </div>
                </div>
              )}

              {tab === "sessions" && (
                <div className="group/t overflow-x-auto rounded-[var(--radius-sm)] hairline scrollbar-slim">
                  <table className="w-full min-w-[560px] text-[12px] tnum">
                    <thead>
                      <tr className="bg-surface text-[10px] uppercase tracking-wide text-faint">
                        <Th label="Session" sortKey="date" sort={daySort} onSort={sortDays} align="left" />
                        <Th label="Booked" sortKey="realized" sort={daySort} onSort={sortDays} />
                        <Th label="Open" sortKey="unrealized" sort={daySort} onSort={sortDays} />
                        <Th label="Net" sortKey="net" sort={daySort} onSort={sortDays} />
                        <Th label="Cumulative" sortKey="cumulative" sort={daySort} onSort={sortDays} />
                        <Th label="Source" sort={daySort} align="right" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {sortedDays.map((d) => (
                        <tr key={d.date} className="transition-colors duration-150 hover:bg-void/60">
                          <td className="px-3 py-1.5 text-left text-mist">{dayLabel(d.date)}</td>
                          <td className={cn("px-3 py-1.5 text-right", trendClass(d.realized))}>{money(d.realized)}</td>
                          <td className={cn("px-3 py-1.5 text-right", trendClass(d.unrealized))}>{money(d.unrealized)}</td>
                          <td className={cn("px-3 py-1.5 text-right font-semibold", trendClass(d.net))}>{money(d.net)}</td>
                          <td className={cn("px-3 py-1.5 text-right", trendClass(d.cumulative))}>{money(d.cumulative)}</td>
                          <td className="px-3 py-1.5 text-right text-[10.5px] text-faint">
                            {d.source === "trades" ? "rebuilt" : "live read"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {tab === "contracts" && (
                <div className="space-y-2.5">
                  <div className="relative max-w-xs">
                    <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
                    <input
                      type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                      placeholder="Search contracts…" aria-label="Search contracts by symbol"
                      className="ring-focus h-8 w-full rounded-[var(--radius-sm)] bg-void pl-8 pr-3 text-[12px] text-frost placeholder:text-faint hairline"
                    />
                  </div>

                  <div className="group/t overflow-x-auto rounded-[var(--radius-sm)] hairline scrollbar-slim">
                    <table className="w-full min-w-[680px] text-[12px] tnum">
                      <thead>
                        <tr className="bg-surface text-[10px] uppercase tracking-wide text-faint">
                          <Th label="Contract" sortKey="symbol" sort={conSort} onSort={sortContracts} align="left" />
                          <Th label="Sessions" sortKey="sessions" sort={conSort} onSort={sortContracts} />
                          <Th label="Booked" sortKey="realized" sort={conSort} onSort={sortContracts} />
                          <Th label="Open" sortKey="unrealized" sort={conSort} onSort={sortContracts} />
                          <Th label="Net" sortKey="net" sort={conSort} onSort={sortContracts} />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {sortedContracts.length === 0 && (
                          <tr><td colSpan={5} className="px-3 py-6 text-center text-muted">{emptyReason}</td></tr>
                        )}
                        {sortedContracts.map((c, i) => {
                          const isOpen = open === c.symbol;
                          const share = gross ? (Math.abs(c[basis]) / gross) * 100 : 0;
                          const panelId = `pnl-contract-${i}`;
                          return (
                            /* Two sibling rows rather than one row wrapping a flex
                               layout — a colSpan cell would stop the drill-down's
                               columns lining up with the header above it. */
                            <Fragment key={c.symbol}>
                              {/* border-b-0 while open: tbody's divide-y draws a bottom
                                  border on THIS row, which would otherwise cut the row
                                  off from its own drill-down panel. */}
                              <tr className={cn("transition-colors duration-150",
                                isOpen ? "border-b-0 bg-void/70" : "hover:bg-void/60")}>
                                <td className="p-0 text-left">
                                  {/* aria-controls only while the panel exists — pointing at
                                      an absent id is worse than not pointing at all. */}
                                  <button type="button" aria-expanded={isOpen} aria-controls={isOpen ? panelId : undefined}
                                    onClick={() => setOpen(isOpen ? null : c.symbol)}
                                    className="ring-focus flex w-full cursor-pointer items-center gap-1.5 px-3 py-1.5 text-left">
                                    <ChevronRight size={12} className={cn("shrink-0 text-faint transition-transform duration-150", isOpen && "rotate-90")} />
                                    <span className="truncate font-medium text-frost">{c.symbol}</span>
                                    {c.right && <span className="shrink-0 text-[10px] text-faint">{c.right}</span>}
                                  </button>
                                </td>
                                <td className="px-3 py-1.5 text-right text-mist">{c.sessions}</td>
                                <td className={cn("px-3 py-1.5 text-right", trendClass(c.realized))}>{money(c.realized)}</td>
                                <td className={cn("px-3 py-1.5 text-right", trendClass(c.unrealized))}>{money(c.unrealized)}</td>
                                <td className={cn("px-3 py-1.5 text-right font-semibold", trendClass(c.net))}>{money(c.net)}</td>
                              </tr>
                              {isOpen && (
                                <tr id={panelId} className="bg-void">
                                  <td colSpan={5} className="px-3 py-3">
                                    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
                                      {([
                                        ["Underlying", c.underlying],
                                        ["Right", c.right ?? "future / none"],
                                        ["Sessions held", String(c.sessions)],
                                        [`Avg / session (${basisLabel.toLowerCase()})`, money(c[basis] / (c.sessions || 1))],
                                        ["Booked", money(c.realized)],
                                        ["Open", money(c.unrealized)],
                                        ["Net", money(c.net)],
                                        /* Denominator is the gross of the filtered set, so the label
                                           says "shown" — against the window it would be a different %. */
                                        [`Share of shown ${basisLabel.toLowerCase()}`, `${share.toFixed(1)}%`],
                                      ] as const).map(([k, v]) => (
                                        <div key={k}>
                                          <dt className="text-[10px] uppercase tracking-wide text-faint">{k}</dt>
                                          <dd className="mt-0.5 text-[12px] font-medium text-mist">{v}</dd>
                                        </div>
                                      ))}
                                    </dl>
                                    <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-line">
                                      <div className={c[basis] >= 0 ? "h-full bg-up" : "h-full bg-down"} style={{ width: `${share}%` }} />
                                    </div>
                                    <p className="mt-2 text-[10.5px] leading-snug text-faint">
                                      Totals over the selected window. A per-session breakdown for this contract is recorded in the
                                      database but is not carried by this endpoint, so it cannot be shown here.
                                    </p>
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {contracts.length >= 60 && (
                    <p className="text-[10.5px] text-faint">
                      The API returns the 60 biggest movers in a window — narrow the range if a smaller contract is missing.
                    </p>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        {book && !book.ok && (
          <p className="flex items-center gap-1.5 text-[11.5px] text-faint">
            <PlugZap size={12} />
            Broker session {book.status ?? "unavailable"} — today reads from the last recorded session, not a live number.
          </p>
        )}

        <p className="flex items-start gap-1.5 text-[11px] leading-snug text-faint">
          <Table2 size={12} className="mt-0.5 shrink-0" />
          Realised and unrealised P&amp;L exactly as the broker reports it — brokerage, STT and other charges
          are not modelled, so a booked figure is gross. Sessions ARTHA never read are absent from the
          record rather than counted as flat.
          {reconstructed > 0 && ` ${reconstructed} of these ${days.length} sessions were rebuilt from trade history: FIFO-matched booked P&L only, with no mark-to-market on anything carried overnight.`}
        </p>
      </CardBody>
    </Card>
  );
}
