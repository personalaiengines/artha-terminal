"use client";
import { useEffect, useRef, useState } from "react";
import {
  CandleType, DomPosition, IndicatorSeries, LineType, OverlayMode, PolygonType, YAxisType,
  dispose, init, registerIndicator, registerOverlay,
  type Chart, type KLineData, type OverlayCreate,
} from "klinecharts";
import {
  BookOpen, Eye, EyeOff, Keyboard, Magnet, Maximize2, Minimize2, Minus, MousePointer2, MoveUpRight,
  MoveVertical, Ruler, SlidersHorizontal, Trash2, TrendingUp, Undo2,
} from "lucide-react";
import { KIND_COLOR } from "@/components/widgets/level-ladder";
import { type Level, type Timeframe } from "@/components/ui/candles";
import {
  drawKey, isDrawing, prefsKey, readJson, remove as removeStored, toSaved, writeJson,
  type SavedDrawing,
} from "@/lib/chart-store";
import { vwap } from "@/lib/indicators";
import { IST_MS, foldTick, istDate, tickTime } from "@/lib/live-bar";
import { useMarketWs } from "@/lib/use-ws";
import { cn } from "@/lib/utils";

// The F&O price chart, on KLineChart (Apache-2.0, on npm). It replaces the
// lightweight-charts build for one reason: user drawing tools. lightweight-charts
// ships none — trendlines and Fibonacci had to be hand-coded onto it — and this
// library carries them, plus its indicator set, natively.
//
// What is on screen and where it comes from:
//   · daily bars    — the page's own /api/history fetch (the `data` prop);
//   · intraday bars — /api/udf/history, the 1-minute store resampled server-side;
//   · live ticks    — the shared Upstox socket (lib/use-ws), folded into the last
//     bar so it moves between polls.
//
// Nothing here invents a bar (T10). An empty response draws an empty chart with
// the reason written beside it, a tick never opens a daily bar the store has not
// published yet, and streamed bars carry volume 0 because the tape does not
// stream volume — 0 is the measurement, not a placeholder.

type Candle = { t: string; open: number; high: number; low: number; close: number; volume: number };
type ChartType = "candles" | "hollow" | "bars" | "area";
type Scale = "normal" | "log" | "percent";
type Fetch = { status: "loading" | "ok" | "empty" | "error"; bars: KLineData[]; note?: string };

// Mirrors the CSS custom properties in app/globals.css — the chart draws to a
// canvas and cannot read var(--color-*).
const C = {
  frost: "#eef1f6", mist: "#b6bdcc", muted: "#7b8394", faint: "#545c6b",
  line: "#23272f", raised: "#1c2029", void: "#0b0d12", grid: "rgba(35,39,47,0.55)",
  accent: "#3b82f6", up: "#10b981", down: "#f4586a", warn: "#f5a623",
};

// `days` is how far back to ask, not what will arrive: Upstox serves 1-minute
// candles for roughly the trailing month and rejects every coarser intraday
// interval, so the store holds ~22 trading days and 5m/15m/1h are resampled off
// that (services/intraday.py). Asking for the whole window on the coarser
// resolutions costs one query and returns everything there is; 1m is held back
// because a full month of it is 8,250 bars per fetch.
const RESOLUTIONS = [
  { label: "1m", res: "1", days: 7, minutes: 1 },
  { label: "5m", res: "5", days: 30, minutes: 5 },
  { label: "15m", res: "15", days: 30, minutes: 15 },
  { label: "1h", res: "60", days: 30, minutes: 60 },
  { label: "1D", res: "1D", days: 0, minutes: 0 },
] as const;
type ResLabel = typeof RESOLUTIONS[number]["label"];

const TYPES: { label: string; value: ChartType }[] = [
  { label: "Candles", value: "candles" }, { label: "Hollow", value: "hollow" },
  { label: "Bars", value: "bars" }, { label: "Area", value: "area" },
];
const CANDLE_TYPE: Record<ChartType, CandleType> = {
  candles: CandleType.CandleSolid, hollow: CandleType.CandleStroke,
  bars: CandleType.Ohlc, area: CandleType.Area,
};
const Y_TYPE: Record<Scale, YAxisType> = {
  normal: YAxisType.Normal, log: YAxisType.Log, percent: YAxisType.Percentage,
};

// Every one of these but VWAP is a KLineChart built-in. `pane: null` means the
// indicator is stacked onto the candle pane rather than given one of its own.
const INDICATORS = [
  { key: "MA", label: "MA", pane: null },
  { key: "EMA", label: "EMA", pane: null },
  { key: "BOLL", label: "Bollinger", pane: null },
  { key: "VWAP", label: "VWAP", pane: null, needsVolume: true },
  { key: "TWAP", label: "TWAP", pane: null },
  { key: "VOL", label: "Volume", pane: "pane_vol", needsVolume: true },
  { key: "RSI", label: "RSI", pane: "pane_rsi" },
  { key: "MACD", label: "MACD", pane: "pane_macd" },
  { key: "KDJ", label: "KDJ", pane: "pane_kdj" },
] as const;
type IndKey = typeof INDICATORS[number]["key"];

// What each indicator measures, how it is read, and what it will not tell you.
// Rendered in the guide panel — the desk should not have to leave the chart to
// find out what a line means, and the caveat is there because an indicator read
// without its limits is worse than no indicator.
const DOC: Record<IndKey, { what: string; how: string; but: string }> = {
  MA: {
    what: "Simple moving average — the mean close of the last N bars, N from the label on the pane.",
    how: "Slope is the trend of that window; price crossing it marks where the average buyer of the window is at break-even.",
    but: "It lags by design: half the window. In a fast reversal it points the wrong way for several bars.",
  },
  EMA: {
    what: "Exponential moving average — same idea as MA, weighted so recent bars matter more.",
    how: "Turns sooner than the MA. The 20/50 pair crossing is the common trend-change read.",
    but: "Faster also means noisier — it whipsaws in a range where the MA would have stayed flat.",
  },
  BOLL: {
    what: "Bollinger Bands — a 20-bar average with bands two standard deviations above and below.",
    how: "Band width is volatility: narrow means quiet, and a squeeze often precedes an expansion. Touching a band is not a signal by itself.",
    but: "Standard deviation assumes a distribution markets do not have. Tags of the upper band cluster in strong trends and mean nothing there.",
  },
  VWAP: {
    what: "Volume-weighted average price, re-anchored every session — the average price actually traded, weighted by size.",
    how: "The session's fair-value line. Institutions benchmark fills against it, so it often acts as intraday support or resistance.",
    but: "Needs real volume. The index intraday feed publishes none, so this is only available on daily bars here (see TWAP for the volume-free version).",
  },
  TWAP: {
    what: "Time-weighted average price, re-anchored every session — the mean of each bar's typical price (high+low+close)/3, every bar counted equally.",
    how: "Read like VWAP: above it the session is trading rich, below it cheap. It is the honest substitute where no volume is published.",
    but: "Every bar counts the same, so a thin opening minute weighs as much as the busiest one. It is not VWAP and will not match a broker's VWAP fill.",
  },
  VOL: {
    what: "Volume traded per bar, with its own moving averages.",
    how: "Confirmation: a move on rising volume has participation behind it; a move on falling volume is fewer hands.",
    but: "Index intraday bars carry no volume from this feed — the pane is empty by honesty, not by failure. Daily index volume is published and does draw.",
  },
  RSI: {
    what: "Relative Strength Index, 14 bars — the ratio of average gains to average losses, scaled 0-100.",
    how: "Above 70 is stretched up, below 30 stretched down. Divergence (price makes a new high, RSI does not) is the read most desks care about.",
    but: "'Overbought' is not 'about to fall'. RSI can pin above 70 for weeks in a trend; it measures speed, not direction.",
  },
  MACD: {
    what: "Moving Average Convergence Divergence — the 12/26 EMA gap, with a 9-bar signal line and their difference as a histogram.",
    how: "Histogram flipping sign is momentum changing hands; the gap widening is a trend accelerating.",
    but: "It is two lagging averages subtracted, so it is lagging twice. In a range it crosses constantly and means nothing.",
  },
  KDJ: {
    what: "Stochastic oscillator with a third J line — where the close sits inside the recent high-low range.",
    how: "Reads momentum inside a range; the K and D crossing near an extreme is the classic setup.",
    but: "Built for range-bound markets. In a trend it saturates at the top or bottom and stays there.",
  },
};

// What each line on the price map is, in plain words. Keyed by the prefix of the
// label the engine produces (labels merge when methods agree: "Prev Day High +
// Pivot R1"), so the first match wins.
const LEVEL_DOC: [string, string][] = [
  ["Call OI Wall", "The strike where the most calls are sold. Sellers defend it, so rallies often stall there."],
  ["Put OI Wall", "The strike where the most puts are sold. Sellers defend it, so falls often hold there."],
  ["Max Pain", "The price at which the most options expire worthless. Price tends to drift toward it as expiry nears."],
  ["Exp-Move", "How far the option market is priced to move by expiry — the at-the-money straddle, up and down from spot."],
  ["CPR", "Yesterday's pivot band. A narrow band suggests a trending day, a wide one a rangebound day."],
  ["Camarilla", "A fade band built from yesterday's range. Price rejecting it is the reversal read, closing through it the breakout read."],
  ["Pivot", "Yesterday's high, low and close turned into today's reference prices. R = above, S = below."],
  ["Prev Day High", "Yesterday's highest price."],
  ["Prev Day Low", "Yesterday's lowest price."],
  ["Prev Day Close", "Where yesterday settled — what today's gap is measured from."],
  ["Prev Week High", "Last week's highest price."],
  ["Prev Week Low", "Last week's lowest price."],
];

const levelDoc = (label: string) => LEVEL_DOC.find(([k]) => label.includes(k))?.[1];

// Read alongside DOC — these are about the surface, not the maths.
const TIPS = [
  "Every level on this chart is drawn by a rule, and the rule is spelled out under Level Map below. Filter the ones you are not trading with the sliders button.",
  "Indicators are computed from the bars on screen only. Switch resolution and a 20-period average is 20 of the NEW bars — the same line means a different thing.",
  "A level drawn broken (dashed and dimmed) traded through this session. It is kept on the chart because where a level failed matters as much as where it held.",
  "Drawings snap to OHLC values when the magnet is on. Useful for anchoring a trendline to real highs and lows rather than to a pixel.",
  "Drawings, the level filter and the indicator set are saved in this browser — drawings per index, the setup shared. The bin button clears this index's drawings for good.",
];

// KLineChart's own overlay names. Everything the desk actually draws on a level
// map; the library carries ~15 and the rest are variants of these.
const TOOLS = [
  { name: "horizontalStraightLine", label: "Horizontal line", Icon: Minus },
  { name: "segment", label: "Trend line", Icon: TrendingUp },
  { name: "rayLine", label: "Ray", Icon: MoveUpRight },
  { name: "verticalStraightLine", label: "Vertical line", Icon: MoveVertical },
  { name: "fibonacciLine", label: "Fibonacci retracement", Icon: Ruler },
  { name: "priceChannelLine", label: "Price channel", Icon: MousePointer2 },
] as const;

// The 1-minute store's own refill is throttled to 300s server-side, so anything
// faster than this only re-reads the same rows. Live movement between polls comes
// off the socket, not off this.
const INTRADAY_POLL_MS = 60_000;

const RANGES: Timeframe[] = ["1M", "3M", "6M", "1Y"];

/** The setup that survives a reload. Resolution is deliberately NOT in here: the
 *  page opens on 15m by design, and a chart that opens wherever it was last left
 *  makes that default unreadable. */
type Prefs = {
  type: ChartType; scale: Scale; showLevels: boolean;
  ind: Record<IndKey, boolean>; hidden: string[];
};

// Every shortcut the chart answers to. Rendered verbatim in the help sheet, so
// the list and the handler cannot drift apart.
const KEYS: [string, string][] = [
  ["← →", "step the read cursor one bar (Shift: ten)"],
  ["Home / End", "first / last bar"],
  ["+ / −", "zoom in / out"],
  ["R", "reset the view (or double-click the price axis)"],
  ["1 … 5", "resolution: 1m, 5m, 15m, 1h, 1D"],
  ["L", "show or hide the level map"],
  ["S", "pick which levels are drawn"],
  ["I", "what the indicators mean"],
  ["F", "expand the chart to the window"],
  ["Esc", "close a panel, cancel the drawing, the cursor, then the expansion"],
  ["?", "this list"],
];

const fade = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
};

/** "31 Jul 09:15" IST. */
const label = (ms: number) => {
  const d = new Date(ms + IST_MS);
  return `${d.getUTCDate()} ${d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" })} `
    + `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};

/** The session each bar belongs to — VWAP and TWAP re-anchor when it changes.
 *
 *  Intraday that is the trading day. On DAILY bars a "session" is one bar, which
 *  would make both averages nothing but that bar's own typical price — a line
 *  that looks like an average and measures nothing. Daily bars therefore share
 *  one anchor across the loaded window (anchored VWAP), which the note under the
 *  chart states outright. */
const sessionKeys = (bars: KLineData[]): string[] => {
  const daily = bars.length > 1 && bars[1].timestamp - bars[0].timestamp >= 20 * 3600_000;
  return daily ? bars.map(() => "window") : bars.map((b) => istDate(b.timestamp));
};

// ---- registrations (module scope: the library's registries are global) -------

// VWAP is not in KLineChart's built-in set, and the maths already lives in
// lib/indicators.ts behind its own assertions — so it is registered here rather
// than reimplemented. Zero volume ⇒ vwap() returns [] and nothing draws, which
// is the honest answer for an index whose exchange publishes no volume.
registerIndicator<{ vwap?: number }>({
  name: "VWAP",
  shortName: "VWAP",
  series: IndicatorSeries.Price,
  precision: 2,
  figures: [{ key: "vwap", title: "VWAP: ", type: "line" }],
  styles: { lines: [{ color: C.warn, size: 2, style: LineType.Solid, smooth: false, dashedValue: [2, 2] }] },
  calc: (dataList) => {
    const values = vwap(
      dataList.map((d) => ({ high: d.high, low: d.low, close: d.close, volume: d.volume ?? 0 })),
      sessionKeys(dataList),
    );
    return dataList.map((_, i) => (values[i] == null ? {} : { vwap: values[i] as number }));
  },
});

// The volume-free session average, for the instruments this feed publishes no
// intraday volume for. Deliberately NOT called VWAP and deliberately not VWAP's
// formula with volume forced to 1: it is the mean typical price of the session
// so far, and it says so everywhere it appears.
registerIndicator<{ twap?: number }>({
  name: "TWAP",
  shortName: "TWAP",
  series: IndicatorSeries.Price,
  precision: 2,
  figures: [{ key: "twap", title: "TWAP: ", type: "line" }],
  styles: { lines: [{ color: "#38bdf8", size: 2, style: LineType.Solid, smooth: false, dashedValue: [2, 2] }] },
  calc: (dataList) => {
    const keys = sessionKeys(dataList);
    let sum = 0, n = 0, session = "";
    return dataList.map((d, i) => {
      if (keys[i] !== session) { session = keys[i]; sum = 0; n = 0; }
      sum += (d.high + d.low + d.close) / 3;
      n += 1;
      return { twap: sum / n };
    });
  },
});

// A level's tag on the price axis, copied from the library's simpleTag with one
// change: both figures ignore events. The built-in consumes the drag, and eight
// levels stacked near spot made the top of the price axis dead to the mouse and
// to touch — the axis could not be rescaled where the levels actually are.
registerOverlay({
  name: "levelTag",
  totalStep: 2,
  lock: true,
  needDefaultPointFigure: false,
  needDefaultXAxisFigure: false,
  needDefaultYAxisFigure: false,
  createPointFigures: ({ coordinates, bounding }) => [{
    type: "line",
    attrs: { coordinates: [{ x: 0, y: coordinates[0].y }, { x: bounding.width, y: coordinates[0].y }] },
    ignoreEvent: true,
  }],
  createYAxisFigures: ({ overlay, coordinates, bounding }) => ({
    type: "text",
    attrs: { x: bounding.width, y: coordinates[0].y, text: String(overlay.extendData ?? ""), align: "right", baseline: "middle" },
    ignoreEvent: true,
  }),
});

// A confluence zone is a RANGE, not a line, and no built-in overlay fills a
// horizontal band. Two points (hi, lo), locked, drawn across the full pane.
registerOverlay({
  name: "zoneBand",
  totalStep: 3,
  lock: true,
  needDefaultPointFigure: false,
  needDefaultXAxisFigure: false,
  needDefaultYAxisFigure: false,
  createPointFigures: ({ coordinates, bounding }) => {
    if (coordinates.length < 2) return [];
    // A confluence zone is often a handful of points wide on a 24,000 index —
    // a couple of pixels. Floored at 3px so a real zone is still visible as a band.
    const height = Math.max(Math.abs(coordinates[0].y - coordinates[1].y), 3);
    const y = Math.min(coordinates[0].y, coordinates[1].y) - (height - Math.abs(coordinates[0].y - coordinates[1].y)) / 2;
    return [{ type: "rect", attrs: { x: 0, y, width: bounding.width, height }, ignoreEvent: true }];
  },
});

const STYLES = {
  grid: { horizontal: { color: C.grid }, vertical: { color: C.grid } },
  candle: {
    bar: {
      upColor: C.up, downColor: C.down, noChangeColor: C.muted,
      upBorderColor: C.up, downBorderColor: C.down, noChangeBorderColor: C.muted,
      upWickColor: C.up, downWickColor: C.down, noChangeWickColor: C.muted,
    },
    area: { lineColor: C.accent, lineSize: 2, backgroundColor: [
      { offset: 0, color: fade(C.accent, 0.28) }, { offset: 1, color: fade(C.accent, 0.01) },
    ] },
    priceMark: {
      high: { color: C.faint }, low: { color: C.faint },
      last: { upColor: C.up, downColor: C.down, noChangeColor: C.muted,
        text: { color: C.void, size: 11 } },
    },
    tooltip: {
      text: { color: C.mist, size: 11 },
      rect: { color: "transparent", borderColor: "transparent" },
    },
  },
  indicator: {
    tooltip: { text: { color: C.muted, size: 11 } },
    lastValueMark: { show: false },
  },
  // Axis text was #545c6b on a near-black pane — about 3:1, under WCAG AA for
  // small text, and the first thing anyone squinted at. The ticks are the chart's
  // units; they read at #b6bdcc (~8:1) and one size larger.
  xAxis: { axisLine: { color: C.line }, tickLine: { color: C.line }, tickText: { color: C.mist, size: 11 } },
  yAxis: { axisLine: { color: C.line }, tickLine: { color: C.line }, tickText: { color: C.mist, size: 11 } },
  separator: { color: C.line },
  crosshair: {
    horizontal: { line: { color: C.mist }, text: { backgroundColor: C.frost, color: C.void, size: 11, weight: "bold" } },
    vertical: { line: { color: C.mist }, text: { backgroundColor: C.frost, color: C.void, size: 11, weight: "bold" } },
  },
  overlay: { point: { color: C.accent, borderColor: fade(C.accent, 0.35) } },
};

function Pills<T extends string>({ options, value, onChange, title }: {
  options: readonly { label: string; value: T }[]; value: T; onChange: (v: T) => void; title?: string;
}) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-[var(--radius-sm)] bg-void p-0.5 hairline" title={title}>
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)} aria-pressed={value === o.value}
          className={cn("rounded-[7px] px-2.5 py-1 text-[11px] font-medium transition-colors",
            value === o.value ? "bg-raised text-frost hairline" : "text-muted hover:text-mist")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Toggle({ on, onClick, disabled, title, children }: {
  on: boolean; onClick: () => void; disabled?: boolean; title?: string; children: React.ReactNode;
}) {
  return (
    <button onClick={onClick} aria-pressed={on} disabled={disabled} title={title}
      className={cn("rounded-[7px] px-2.5 py-1 text-[11px] font-medium transition-colors hairline",
        disabled ? "bg-void text-faint opacity-50" : on ? "bg-raised text-frost" : "bg-void text-muted hover:text-mist")}>
      {children}
    </button>
  );
}

export function KlineChart({
  symbol, liveKey, data, levels = [], spot, height = 440, timeframe, onTimeframe,
}: {
  symbol: string;
  /** the name the tick socket knows this index by ("nifty50"); omit for no stream */
  liveKey?: string | null;
  /** daily OHLC, already fetched by the page from /api/history */
  data: Candle[];
  levels?: Level[];
  spot?: number | null;
  height?: number;
  timeframe?: Timeframe;
  onTimeframe?: (tf: Timeframe) => void;
}) {
  const [res, setRes] = useState<ResLabel>("15m");
  const [type, setType] = useState<ChartType>("candles");
  const [scale, setScale] = useState<Scale>("normal");
  const [ind, setInd] = useState<Record<IndKey, boolean>>({
    MA: false, EMA: false, BOLL: false, VWAP: false, TWAP: false, VOL: true, RSI: false, MACD: false, KDJ: false,
  });
  const [intra, setIntra] = useState<Fetch>({ status: "ok", bars: [] });
  const [tool, setTool] = useState<string | null>(null);
  const [magnet, setMagnet] = useState(false);
  const [ready, setReady] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showLevels, setShowLevels] = useState(true);
  const [help, setHelp] = useState(false);
  const [guide, setGuide] = useState(false);
  const [picker, setPicker] = useState(false);
  // Levels hidden by name. Absent = drawn, so a level the engine adds later shows
  // up rather than inheriting someone's old filter.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // Index of the bar the keyboard cursor sits on. A canvas cannot be read by a
  // screen reader and cannot be reached by Tab, so this is how the chart is read
  // without a mouse: the cursor walks the bars and every stop is announced.
  const [cursor, setCursor] = useState<number | null>(null);

  // Saved setup is applied AFTER the first render, not read into useState: the
  // server renders this markup too, and localStorage on the client would make the
  // two disagree. One extra paint beats a hydration mismatch.
  const restored = useRef(false);
  useEffect(() => {
    const p = readJson<Partial<Prefs>>(prefsKey(), {});
    if (p.type) setType(p.type);
    if (p.scale) setScale(p.scale);
    if (typeof p.showLevels === "boolean") setShowLevels(p.showLevels);
    // Merged, not replaced — an indicator added in a later build must not be
    // dropped because an older saved object had no key for it.
    if (p.ind) setInd((cur) => ({ ...cur, ...p.ind }));
    if (Array.isArray(p.hidden)) setHidden(new Set(p.hidden.filter((h) => typeof h === "string")));
    restored.current = true;
  }, []);

  useEffect(() => {
    if (!restored.current) return;   // don't write defaults over the saved setup
    writeJson(prefsKey(), { type, scale, showLevels, ind, hidden: [...hidden] } satisfies Prefs);
  }, [type, scale, showLevels, ind, hidden]);

  const spec = RESOLUTIONS.find((r) => r.label === res)!;
  const intraday = res !== "1D";
  const { subscribe } = useMarketWs();

  // ---- data ---------------------------------------------------------------

  // Daily rows are "YYYY-MM-DD"; stored at UTC midnight of the trading date and
  // read back in IST (see istDate). Non-increasing rows are dropped rather than
  // handed to the chart out of order.
  const daily: KLineData[] = data
    .map((d) => ({
      timestamp: Date.parse(`${d.t}T00:00:00Z`),
      open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume,
    }))
    .filter((b, i, a) => Number.isFinite(b.timestamp) && (i === 0 || b.timestamp > a[i - 1].timestamp));

  useEffect(() => {
    if (!intraday) return;
    let alive = true;
    setIntra({ status: "loading", bars: [] });
    const load = () => {
      const to = Math.floor(Date.now() / 1000);
      const from = to - spec.days * 86400;
      fetch(`/api/udf/history?symbol=${encodeURIComponent(symbol)}&resolution=${spec.res}&from=${from}&to=${to}`)
        .then((r) => r.json())
        .then((j) => {
          if (!alive) return;
          if (j?.s === "ok" && Array.isArray(j.t) && j.t.length) {
            // UDF answers in column arrays; KLineChart wants rows, in milliseconds.
            const bars: KLineData[] = j.t.map((t: number, i: number) => ({
              timestamp: t * 1000, open: j.o[i], high: j.h[i], low: j.l[i], close: j.c[i], volume: j.v?.[i] ?? 0,
            }));
            setIntra({ status: "ok", bars });
          } else if (j?.s === "no_data") {
            setIntra({ status: "empty", bars: [] });
          } else {
            setIntra({ status: "error", bars: [], note: j?.errmsg ?? "the datafeed returned an unreadable response" });
          }
        })
        .catch(() => { if (alive) setIntra({ status: "error", bars: [], note: "the datafeed could not be reached" }); });
    };
    load();
    const id = setInterval(load, INTRADAY_POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, [symbol, intraday, spec.res, spec.days]);

  const bars = intraday ? intra.bars : daily;
  const hasVol = bars.some((b) => (b.volume ?? 0) > 0);

  // ---- chart --------------------------------------------------------------

  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const appliedRef = useRef("");          // symbol|resolution currently applied
  const lastRef = useRef<KLineData | null>(null);
  const panesRef = useRef<Partial<Record<IndKey, string>>>({});
  const drawnRef = useRef<string[]>([]);  // user drawings, newest last (undo stack)

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const chart = init(el, { timezone: "Asia/Kolkata", styles: STYLES });
    chart?.setPriceVolumePrecision(2, 0);
    chartRef.current = chart;
    return () => {
      dispose(el);                        // React 19 strict mode mounts twice
      chartRef.current = null;
      appliedRef.current = ""; lastRef.current = null;
      panesRef.current = {}; drawnRef.current = [];
      setReady(false);
    };
  }, []);

  // Applying a whole new dataset snaps the viewport back to the latest bar, so
  // it happens only when the series itself changed. A poll that extends the same
  // series is fed bar-by-bar instead, which leaves the user's zoom alone.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const key = `${symbol}|${res}`;
    if (!bars.length) {
      // An empty payload must NOT claim the key: a resolution switch shows one
      // while its bars load, and claiming it would send the arriving series down
      // the incremental path — 375 single-bar updates at the previous
      // resolution's bar width.
      if (appliedRef.current) chart.clearData();
      appliedRef.current = ""; lastRef.current = null; setReady(false);
      return;
    }
    if (appliedRef.current !== key) {
      // KLineChart keeps a fixed bar width, so a 22-bar daily window would sit in
      // the right quarter of the pane. Widen the bars to fill it — before the data
      // lands, so the view settles on the latest bar with the new spacing — and
      // only on a new series, so a poll never overrides the zoom the user set.
      const width = chart.getSize("candle_pane", DomPosition.Main)?.width ?? 0;
      if (width > 0) chart.setBarSpace(Math.min(40, Math.max(2, width / (bars.length + 4))));
      chart.applyNewData(bars);
      appliedRef.current = key;
    } else {
      const from = lastRef.current?.timestamp ?? 0;
      for (const b of bars) if (b.timestamp >= from) chart.updateData(b);
    }
    lastRef.current = bars[bars.length - 1];
    setReady(true);
  }, [bars, symbol, res]);

  useEffect(() => {
    chartRef.current?.setStyles({
      candle: { type: CANDLE_TYPE[type] },
      yAxis: { type: Y_TYPE[scale] },
    });
  }, [type, scale]);

  // Indicators — created and removed against what is already on the chart, so a
  // toggle never rebuilds the panes that are not changing.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    for (const i of INDICATORS) {
      const want = ind[i.key] && (!("needsVolume" in i && i.needsVolume) || hasVol);
      const paneId = panesRef.current[i.key];
      if (want && !paneId) {
        const id = i.pane == null
          ? chart.createIndicator(i.key, true, { id: "candle_pane" })
          : chart.createIndicator(i.key, false, { id: i.pane, height: Math.round(height * 0.22) });
        if (id) panesRef.current[i.key] = id;
      } else if (!want && paneId) {
        chart.removeIndicator(paneId, i.key);
        delete panesRef.current[i.key];
      }
    }
  }, [ind, hasVol, height]);

  // Levels and zones (T7), redrawn as one locked group. A crossed level is drawn
  // BROKEN — dashed, dimmed and labelled so — never quietly relabelled. KIND_COLOR
  // is imported from the ladder so the two cannot drift apart on colour.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !ready) return;
    chart.removeOverlay({ groupId: "levels" });
    if (!showLevels) return;
    const items: OverlayCreate[] = [];
    for (const l of levels) {
      if (hidden.has(l.label)) continue;
      const color = KIND_COLOR[l.kind ?? ""] ?? l.color;
      const broken = !!l.crossed;
      if (l.lo != null && l.hi != null && l.hi > l.lo) {
        items.push({
          name: "zoneBand", groupId: "levels", lock: true,
          points: [{ value: l.hi }, { value: l.lo }],
          styles: { rect: { style: PolygonType.Fill, color: fade(color, broken ? 0.08 : 0.2), borderSize: 0, borderColor: "transparent" } },
        });
      }
      items.push({
        name: "levelTag", groupId: "levels", lock: true,
        points: [{ value: l.price }],
        extendData: broken ? `${l.label} · BROKEN` : l.label,
        styles: {
          line: {
            color: broken ? fade(color, 0.5) : color,
            style: LineType.Dashed,
            size: Math.min(3, 1 + Math.round((l.strength ?? 0) / 40)),
          },
          text: { color: C.void, backgroundColor: broken ? fade(color, 0.5) : color, size: 10 },
        },
      });
    }
    if (spot != null && Number.isFinite(spot)) {
      items.push({
        name: "levelTag", groupId: "levels", lock: true, points: [{ value: spot }],
        extendData: "SPOT",
        styles: { line: { color: C.accent, style: LineType.Solid, size: 2 }, text: { color: C.void, backgroundColor: C.accent, size: 10 } },
      });
    }
    if (items.length) chart.createOverlay(items);
  }, [levels, spot, ready, showLevels, hidden]);

  // Live ticks folded into the last bar. Volume is not on the tape, so a bar
  // opened here carries 0 — the poll replaces it with the exchange's own bar.
  useEffect(() => {
    if (!liveKey) return;
    const step = spec.minutes * 60_000;
    return subscribe([liveKey], (t: any) => {
      const chart = chartRef.current, last = lastRef.current;
      if (t?.ltp == null || !chart || !last) return;
      // `ltt` is the exchange's own last-traded time. Preferred over the browser
      // clock, which decides which bar a tick belongs to.
      const bar = foldTick(last, t.ltp, tickTime(t.ltt, Date.now()), step);
      if (!bar) return;
      lastRef.current = bar;
      chart.updateData(bar);
      setStreaming(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveKey, spec.minutes]);

  useEffect(() => { setStreaming(false); }, [symbol, res]);

  // ---- drawing tools ------------------------------------------------------

  // Drawings are kept per symbol: a trendline anchored to NIFTY prices means
  // nothing on BANKNIFTY. Anchors are timestamp + price, so a drawing made on 15m
  // is still in the right place on 1D.
  const saveDrawings = () => {
    const chart = chartRef.current;
    if (!chart) return;
    const saved = drawnRef.current
      .map((id) => chart.getOverlayById(id))
      .filter((o): o is NonNullable<typeof o> => o != null)
      .map((o) => toSaved(o.name, o.points, o.styles ?? undefined));
    if (saved.length) writeJson(drawKey(symbol), saved);
    else removeStored(drawKey(symbol));
  };

  const track = (name: string) => ({
    onDrawEnd: (e: { overlay: { id: string } }) => {
      drawnRef.current.push(e.overlay.id);
      setTool(null);
      saveDrawings();
      return false;
    },
    onRemoved: (e: { overlay: { id: string } }) => {
      drawnRef.current = drawnRef.current.filter((id) => id !== e.overlay.id);
      return false;
    },
    // Moving or reshaping a drawing changes its anchors — save those too, or a
    // reload would put it back where it was first drawn.
    onPressedMoveEnd: () => { saveDrawings(); return false; },
    name,
  });

  const startTool = (name: string) => {
    const chart = chartRef.current;
    if (!chart) return;
    setTool(name);
    chart.createOverlay({
      ...track(name), groupId: "draw",
      mode: magnet ? OverlayMode.WeakMagnet : OverlayMode.Normal,
    });
  };

  const cancelTool = () => {
    // Removes the half-drawn overlay too — it is in the same group and has no id
    // on the stack yet.
    chartRef.current?.removeOverlay({ groupId: "draw" });
    drawnRef.current = [];
    removeStored(drawKey(symbol));
    setTool(null);
  };

  const undo = () => {
    const id = drawnRef.current.pop();
    if (id) chartRef.current?.removeOverlay(id);
    saveDrawings();
  };

  // Put the saved drawings back, once per symbol and only once there are bars to
  // anchor them against.
  const drawnFor = useRef("");
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !ready || drawnFor.current === symbol) return;
    chart.removeOverlay({ groupId: "draw" });
    drawnRef.current = [];
    drawnFor.current = symbol;
    const saved = readJson<SavedDrawing[]>(drawKey(symbol), []);
    for (const d of Array.isArray(saved) ? saved : []) {
      if (!isDrawing(d)) continue;
      const id = chart.createOverlay({
        ...track(d.name), groupId: "draw", points: d.points,
        styles: (d.styles ?? undefined) as never,
      });
      if (typeof id === "string") drawnRef.current.push(id);
    }
  }, [symbol, ready]);   // eslint-disable-line react-hooks/exhaustive-deps

  // ---- keyboard cursor ----------------------------------------------------

  // The cursor bar, drawn as a locked vertical line so a sighted keyboard user
  // sees where the announcement is coming from. Redrawn rather than moved: it is
  // one overlay, and removeOverlay+createOverlay is the whole API surface here.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.removeOverlay({ groupId: "cursor" });
    if (cursor == null || !bars[cursor]) return;
    chart.createOverlay({
      name: "verticalStraightLine", groupId: "cursor", lock: true,
      points: [{ timestamp: bars[cursor].timestamp }],
      styles: { line: { color: C.accent, style: LineType.Dashed, size: 1 } },
    });
    // Follow the cursor only when it walks off the edge, so reading a visible
    // stretch of bars does not drag the viewport on every keypress. scrollToDataIndex
    // parks its argument at the RIGHT edge, so aim half a screen ahead of the
    // cursor — landing it mid-pane with context on both sides instead of against
    // the wall with the whole window empty behind it.
    const view = chart.getVisibleRange();
    if (cursor <= view.from || cursor >= view.to - 1) {
      const ahead = Math.max(1, Math.floor((view.to - view.from) / 2));
      chart.scrollToDataIndex(Math.min(bars.length - 1, cursor + ahead));
    }
  }, [cursor, bars]);

  // A bar the cursor left behind is meaningless once the series changes.
  useEffect(() => { setCursor(null); }, [symbol, res]);

  const step = (delta: number) => setCursor((c) => {
    if (!bars.length) return null;
    const next = c == null ? bars.length - 1 : c + delta;
    return Math.min(bars.length - 1, Math.max(0, next));
  });

  const zoom = (factor: number) => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.setBarSpace(Math.min(50, Math.max(1, chart.getBarSpace() * factor)));
  };

  // Back to the view the chart opened with. Dragging the price axis puts it into
  // manual scaling and it stays there — the library clears that flag when the
  // y-axis style is set (or on a double-click of the axis), which is what this
  // borrows rather than reloading the series.
  const resetView = () => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.setStyles({ yAxis: { type: Y_TYPE[scale] } });
    const width = chart.getSize("candle_pane", DomPosition.Main)?.width ?? 0;
    if (width > 0 && bars.length) chart.setBarSpace(Math.min(40, Math.max(2, width / (bars.length + 4))));
    chart.scrollToRealTime();
    setCursor(null);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const k = e.key;
    const hit = () => e.preventDefault();
    if (k === "ArrowLeft") { hit(); step(e.shiftKey ? -10 : -1); }
    else if (k === "ArrowRight") { hit(); step(e.shiftKey ? 10 : 1); }
    else if (k === "Home") { hit(); setCursor(bars.length ? 0 : null); }
    else if (k === "End") { hit(); setCursor(bars.length ? bars.length - 1 : null); }
    else if (k === "+" || k === "=") { hit(); zoom(1.25); }
    else if (k === "-" || k === "_") { hit(); zoom(0.8); }
    else if (k === "r" || k === "R") { hit(); resetView(); }
    else if (k >= "1" && k <= "5") { hit(); setRes(RESOLUTIONS[Number(k) - 1].label); }
    else if (k === "l" || k === "L") { hit(); setShowLevels((v) => !v); }
    else if (k === "s" || k === "S") { hit(); setPicker((v) => !v); }
    else if (k === "i" || k === "I") { hit(); setGuide((v) => !v); }
    else if (k === "f" || k === "F") { hit(); setExpanded((v) => !v); }
    else if (k === "?") { hit(); setHelp((v) => !v); }
    else if (k === "Escape") {
      // One key, unwound in the order a user expects to undo things.
      hit();
      if (help || guide || picker) { setHelp(false); setGuide(false); setPicker(false); }
      else if (tool) cancelTool();
      else if (cursor != null) setCursor(null);
      else setExpanded(false);
    }
  };

  // Expanding changes the box, and the library sizes to its container.
  useEffect(() => { chartRef.current?.resize(); }, [expanded]);

  // ---- level filter -------------------------------------------------------

  // The level map is eight lines stacked around spot, and which of them matter
  // depends on what is being traded. Rather than one all-or-nothing switch, the
  // picker keeps a hidden set and offers the three cuts a desk actually asks for:
  // everything, only what is still intact, and only what price is near.
  const near1pct = (l: Level) => spot != null && Math.abs((l.price - spot) / spot) <= 0.01;
  const showOnly = (keep: (l: Level) => boolean) =>
    setHidden(new Set(levels.filter((l) => !keep(l)).map((l) => l.label)));
  const toggleLevel = (name: string) => setHidden((prev) => {
    const next = new Set(prev);
    if (!next.delete(name)) next.add(name);
    return next;
  });
  const shown = levels.filter((l) => !hidden.has(l.label));

  // ---- honest coverage line (T9) ------------------------------------------

  const coverage = !intraday
    ? `${bars.length} daily bars`
    : intra.status === "loading" ? `Loading ${res} bars for ${symbol}…`
      : intra.status === "error" ? `Intraday bars unavailable — ${intra.note}.`
        : intra.status === "empty" || !bars.length
          ? `No ${res} bars stored for ${symbol} over the last ${spec.days} days.`
          : `${bars.length} bars · ${label(bars[0].timestamp)} → ${label(bars[bars.length - 1].timestamp)} IST`
          + ` · the source caps 1-minute history at 22 trading days, so this window can be shorter than ${spec.days} days`;

  const showEmpty = bars.length === 0;

  // Volume and VWAP are greyed out only when the bars on screen carry none, and
  // they say which of the two cases this is. Daily index bars do carry volume;
  // the intraday feed publishes 0 on every index bar, and a VWAP over zero volume
  // is the typical price wearing another name (T10).
  const noVolWhy = intraday
    ? "the intraday feed publishes no volume on index bars — switch to 1D, where it does"
    : "the exchange publishes no volume for this instrument";

  // What the cursor bar says, in words. A price alone is not a reading — what
  // makes this chart worth looking at is the price against the level map, so the
  // nearest level and the distance to it are said out loud too. Announced to a
  // screen reader and shown on screen from the same string, so they cannot differ.
  const at = cursor == null ? null : bars[cursor];
  const near = at && levels.length
    ? levels.reduce((a, b) => (Math.abs(b.price - at.close) < Math.abs(a.price - at.close) ? b : a))
    : null;
  const price = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  const readout = !at ? null : [
    `${label(at.timestamp)} IST`,
    `open ${price(at.open)}`, `high ${price(at.high)}`, `low ${price(at.low)}`, `close ${price(at.close)}`,
    `${at.close >= at.open ? "up" : "down"} ${(Math.abs((at.close - at.open) / at.open) * 100).toFixed(2)}% on the bar`,
    ...(at.volume ? [`volume ${at.volume.toLocaleString("en-IN")}`] : []),
    ...(near ? [`nearest level ${near.label} at ${price(near.price)}, `
      + `${(Math.abs((near.price - at.close) / at.close) * 100).toFixed(2)}% `
      + `${near.price >= at.close ? "above" : "below"}${near.crossed ? ", broken" : ""}`] : []),
    `bar ${cursor! + 1} of ${bars.length}`,
  ].join(" · ");

  return (
    <div className={cn("space-y-2.5", expanded && "fixed inset-0 z-50 overflow-auto bg-void p-4")}>
      {expanded && (
        <div className="flex items-baseline gap-2">
          <h2 className="text-[13px] font-semibold text-frost">{symbol} · {res}</h2>
          <span className="text-[11px] text-faint">Esc or F to collapse</span>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Pills options={RESOLUTIONS.map((r) => ({ label: r.label, value: r.label }))} value={res} onChange={setRes} title="Resolution" />
        {!intraday && onTimeframe && (
          <Pills options={RANGES.map((r) => ({ label: r, value: r }))} value={timeframe ?? "1Y"} onChange={onTimeframe} title="Daily range" />
        )}
        <Pills options={TYPES} value={type} onChange={setType} title="Series type" />
        <div className="inline-flex items-center gap-1">
          <Toggle on={scale === "log"} onClick={() => setScale((s) => (s === "log" ? "normal" : "log"))}>LOG</Toggle>
          <Toggle on={scale === "percent"} onClick={() => setScale((s) => (s === "percent" ? "normal" : "percent"))}>%</Toggle>
        </div>
        <div className="ml-auto inline-flex flex-wrap items-center gap-1">
          {INDICATORS.map((i) => {
            const blocked = "needsVolume" in i && i.needsVolume && !hasVol;
            return (
              <Toggle key={i.key} on={ind[i.key] && !blocked} disabled={blocked}
                title={blocked ? noVolWhy : undefined}
                onClick={() => setInd((p) => ({ ...p, [i.key]: !p[i.key] }))}>
                {i.label}
              </Toggle>
            );
          })}
        </div>
      </div>

      {/* Drawing tools. A tool arms one overlay: click the chart to place its
          points, and the tool disarms itself when the drawing is finished. */}
      <div className="flex flex-wrap items-center gap-1">
        {TOOLS.map(({ name, label: tip, Icon }) => (
          <button key={name} onClick={() => (tool === name ? cancelTool() : startTool(name))}
            aria-pressed={tool === name} title={tip} aria-label={tip}
            className={cn("rounded-[7px] p-1.5 transition-colors hairline",
              tool === name ? "bg-raised text-accent" : "bg-void text-muted hover:text-mist")}>
            <Icon size={14} />
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-line" />
        <button onClick={() => setMagnet((m) => !m)} aria-pressed={magnet} title="Snap new points to the nearest OHLC value" aria-label="Snap new points to the nearest OHLC value"
          className={cn("rounded-[7px] p-1.5 transition-colors hairline",
            magnet ? "bg-raised text-accent" : "bg-void text-muted hover:text-mist")}>
          <Magnet size={14} />
        </button>
        <button onClick={undo} title="Remove the last drawing" aria-label="Remove the last drawing"
          className="rounded-[7px] bg-void p-1.5 text-muted transition-colors hairline hover:text-mist">
          <Undo2 size={14} />
        </button>
        <button onClick={cancelTool} title="Remove every drawing, saved ones included" aria-label="Remove every drawing"
          className="rounded-[7px] bg-void p-1.5 text-muted transition-colors hairline hover:text-mist">
          <Trash2 size={14} />
        </button>
        <span className="ml-2 text-[10.5px] text-faint">
          {tool ? "Click the chart to place the drawing's points." : `Drawings and this setup are saved in this browser, per index — ${symbol} here.`}
        </span>

        <div className="ml-auto inline-flex items-center gap-1">
          {streaming && (
            <span className="mr-1 inline-flex items-center gap-1.5 text-[10.5px] text-mist">
              <span className="h-1.5 w-1.5 rounded-full bg-up" /> streaming
            </span>
          )}
          <button onClick={() => setShowLevels((v) => !v)} aria-pressed={showLevels}
            title={`${showLevels ? "Hide" : "Show"} the level map on the chart (L)`}
            aria-label={`${showLevels ? "Hide" : "Show"} the level map`}
            className={cn("rounded-[7px] p-1.5 transition-colors hairline",
              showLevels ? "bg-raised text-accent" : "bg-void text-muted hover:text-mist")}>
            {showLevels ? <Eye size={14} /> : <EyeOff size={14} />}
          </button>
          <button onClick={() => { setPicker((v) => !v); setGuide(false); setHelp(false); }} aria-pressed={picker}
            title="Pick which levels are drawn (S)" aria-label="Pick which levels are drawn"
            className={cn("relative rounded-[7px] p-1.5 transition-colors hairline",
              picker ? "bg-raised text-accent" : "bg-void text-muted hover:text-mist")}>
            <SlidersHorizontal size={14} />
            {hidden.size > 0 && (
              <span className="absolute -right-0.5 -top-0.5 rounded-full bg-accent px-1 text-[8px] font-semibold text-void tnum">
                {shown.length}
              </span>
            )}
          </button>
          <button onClick={() => { setGuide((v) => !v); setPicker(false); setHelp(false); }} aria-pressed={guide}
            title="What the indicators mean (I)" aria-label="What the indicators mean"
            className={cn("rounded-[7px] p-1.5 transition-colors hairline",
              guide ? "bg-raised text-accent" : "bg-void text-muted hover:text-mist")}>
            <BookOpen size={14} />
          </button>
          <button onClick={() => setHelp((v) => !v)} aria-pressed={help}
            title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts"
            className={cn("rounded-[7px] p-1.5 transition-colors hairline",
              help ? "bg-raised text-accent" : "bg-void text-muted hover:text-mist")}>
            <Keyboard size={14} />
          </button>
          <button onClick={() => setExpanded((v) => !v)} aria-pressed={expanded}
            title={`${expanded ? "Collapse" : "Expand"} the chart (F)`}
            aria-label={`${expanded ? "Collapse" : "Expand"} the chart`}
            className={cn("rounded-[7px] p-1.5 transition-colors hairline",
              expanded ? "bg-raised text-accent" : "bg-void text-muted hover:text-mist")}>
            {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {/* The canvas itself: reachable by Tab, driven by the keys in KEYS, and
          labelled so a screen reader announces what it is before the cursor
          starts reading bars out of it. */}
      <div className="relative w-full outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
        style={{ height: expanded ? "calc(100vh - 230px)" : height }}
        tabIndex={0} role="application" onKeyDown={onKeyDown}
        aria-label={`${symbol} ${res} price chart, ${bars.length} bars. `
          + `Use the arrow keys to read bar by bar, question mark for the shortcuts.`}
        aria-describedby="chart-readout">
        {/* The library owns this node's children — nothing of React's goes in it. */}
        <div ref={box} className="absolute inset-0" />
        {showEmpty && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-center text-[12.5px] text-muted">
            {coverage}
          </div>
        )}
        {/* Which levels are drawn. Rows carry the same colour the line does, so
            the panel and the chart read as one thing. */}
        {picker && (
          <div className="absolute right-3 top-3 z-10 max-h-[86%] w-[330px] overflow-auto rounded-[var(--radius-sm)] bg-raised p-3 shadow-lg hairline">
            <div className="mb-1 flex items-baseline justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-mist">Lines on the chart</span>
              <span className="text-[10.5px] text-faint tnum">{shown.length} of {levels.length} shown</span>
            </div>
            <p className="mb-2 text-[10.5px] leading-snug text-faint">
              Tap a line to hide it. Hover one to read why it is there.
            </p>
            <div className="mb-2 flex flex-wrap gap-1">
              <button onClick={() => setHidden(new Set())}
                className="rounded-[6px] bg-void px-2 py-0.5 text-[10.5px] text-muted hairline hover:text-frost">Show all</button>
              <button onClick={() => showOnly(() => false)}
                className="rounded-[6px] bg-void px-2 py-0.5 text-[10.5px] text-muted hairline hover:text-frost">Hide all</button>
              <button onClick={() => showOnly((l) => !l.crossed)}
                className="rounded-[6px] bg-void px-2 py-0.5 text-[10.5px] text-muted hairline hover:text-frost">Still holding</button>
              <button onClick={() => showOnly(near1pct)} disabled={spot == null}
                className="rounded-[6px] bg-void px-2 py-0.5 text-[10.5px] text-muted hairline hover:text-frost disabled:opacity-40">Close to price</button>
            </div>
            <ul className="space-y-0.5">
              {levels.map((l) => {
                const on = !hidden.has(l.label);
                const color = KIND_COLOR[l.kind ?? ""] ?? l.color;
                const dist = spot ? ((l.price - spot) / spot) * 100 : null;
                return (
                  <li key={l.label}>
                    <button onClick={() => toggleLevel(l.label)} aria-pressed={on}
                      title={[levelDoc(l.label), l.basis].filter(Boolean).join("\n\n")}
                      className={cn("flex w-full items-center gap-2 rounded-[6px] px-2 py-1 text-left text-[11px] transition-colors",
                        on ? "bg-void text-frost" : "text-faint hover:text-muted")}>
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color, opacity: on ? 1 : 0.35 }} />
                      <span className="truncate">{l.label}</span>
                      {l.crossed && <span className="shrink-0 text-[9.5px] uppercase text-warn">broken</span>}
                      <span className="ml-auto shrink-0 tnum">{price(l.price)}</span>
                      {dist != null && (
                        <span className="w-[52px] shrink-0 text-right text-[10.5px] text-muted tnum">
                          {dist >= 0 ? "+" : "−"}{Math.abs(dist).toFixed(2)}%
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
            {!showLevels && (
              <p className="mt-2 text-[10.5px] text-warn">The whole map is hidden (L) — nothing here will draw until it is back on.</p>
            )}
          </div>
        )}

        {/* What the indicators mean. Every line the chart can draw, what it does
            not tell you included. */}
        {guide && (
          <div className="absolute right-3 top-3 z-10 max-h-[86%] w-[400px] overflow-auto rounded-[var(--radius-sm)] bg-raised p-3 shadow-lg hairline">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-mist">Reading the indicators</div>
            <dl className="space-y-2.5">
              {INDICATORS.map((i) => (
                <div key={i.key}>
                  <dt className="flex items-baseline gap-2">
                    <span className="text-[11.5px] font-semibold text-frost">{i.label}</span>
                    {ind[i.key] && <span className="text-[9.5px] uppercase text-accent">on</span>}
                  </dt>
                  <dd className="text-[11px] leading-snug text-muted">
                    {DOC[i.key].what}
                    <span className="block text-mist">Read it: {DOC[i.key].how}</span>
                    <span className="block text-faint">But: {DOC[i.key].but}</span>
                  </dd>
                </div>
              ))}
            </dl>
            <div className="mt-3 border-t border-line pt-2">
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-mist">The lines on the price map</div>
              <dl className="space-y-1.5">
                {LEVEL_DOC.map(([name, what]) => (
                  <div key={name}>
                    <dt className="text-[11px] font-semibold text-frost">{name}</dt>
                    <dd className="text-[11px] leading-snug text-muted">{what}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-1.5 text-[10.5px] leading-snug text-faint">
                Names combine when two methods land on the same price — &quot;Prev Day High + Pivot R1&quot; is one line
                that two independent rules agree on, which is what makes it worth watching.
              </p>
            </div>

            <div className="mt-3 border-t border-line pt-2">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-mist">Working this chart</div>
              <ul className="list-disc space-y-1 pl-4 text-[11px] leading-snug text-muted">
                {TIPS.map((t) => <li key={t}>{t}</li>)}
              </ul>
            </div>
          </div>
        )}

        {help && (
          <div className="absolute right-3 top-3 z-10 w-[330px] rounded-[var(--radius-sm)] bg-raised p-3 shadow-lg hairline">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-mist">Keyboard</div>
            <dl className="space-y-1">
              {KEYS.map(([k, what]) => (
                <div key={k} className="flex gap-2 text-[11px]">
                  <dt className="w-[74px] shrink-0 font-medium text-frost tnum">{k}</dt>
                  <dd className="text-muted">{what}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      {/* One string, two audiences: shown to everyone, announced to a screen
          reader. The chart is a canvas — without this it reads as nothing. */}
      <p id="chart-readout" aria-live="polite" aria-atomic="true"
        className={cn("text-[11.5px] leading-snug tnum", readout ? "text-mist" : "text-faint")}>
        {readout ?? (bars.length ? "Click the chart or press Tab, then use the arrow keys to read it bar by bar." : "")}
      </p>

      <p className="text-[11px] leading-snug text-faint">
        {!showEmpty && <span>{coverage}</span>}
        {!hasVol && bars.length > 0 && (
          <span>{!showEmpty && " · "}no volume drawn: {noVolWhy}, and a fabricated one would be worse than none</span>
        )}
        {ind.VWAP && !hasVol && <span> · VWAP needs volume, so it is not drawn here</span>}
        {(ind.VWAP || ind.TWAP) && !intraday && (
          <span> · on daily bars {ind.VWAP && ind.TWAP ? "VWAP and TWAP are" : ind.VWAP ? "VWAP is" : "TWAP is"} anchored
            once to the first bar loaded, not re-anchored per session — a per-bar anchor would only redraw each bar&apos;s own typical price</span>
        )}
      </p>
    </div>
  );
}
