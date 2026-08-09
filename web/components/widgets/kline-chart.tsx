"use client";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  ActionType, CandleType, DomPosition, FormatDateType, IndicatorSeries, LineType, OverlayMode, PolygonType,
  TooltipShowType, YAxisType,
  dispose, init, registerIndicator, registerOverlay,
  type Chart, type KLineData, type OverlayCreate,
} from "klinecharts";
import {
  BookOpen, Eye, EyeOff, Keyboard, Magnet, Maximize2, Minimize2, Minus, MoreHorizontal,
  MousePointer2, MoveUpRight, MoveVertical, Ruler, SlidersHorizontal, Trash2, TrendingUp, Undo2,
} from "lucide-react";
import { KIND_COLOR } from "@/components/widgets/level-ladder";
import { type Level, type Timeframe } from "@/components/ui/candles";
import {
  clearDrawings, drawKey, isDrawing, migrateLegacyPrefs, onDrawingsChanged, prefsKey, readJson,
  toSaved, writeDrawings, writeJson, type SavedDrawing,
} from "@/lib/chart-store";
import { labelBudget, openBarSpace, pickLabels, shortLevelLabel } from "@/lib/chart-layout";
import { getOnce } from "@/lib/fetch-cache";
import { vwap } from "@/lib/indicators";
import { IST_MS, foldTick, isStreaming, istDate, tickTime } from "@/lib/live-bar";
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
/** Exported so a page holding several charts can name the resolution it drives
 *  one with, and persist it. */
export type ResLabel = typeof RESOLUTIONS[number]["label"];

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

/** Where the OHLC legend sits. Level names keep clear of it. */
const LEGEND_Y = 16;

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

// Every date the chart draws, in IST and in one house style.
//
// KLineChart's defaults produced three different formats on one axis — "07-15",
// then "2026-08" where the month rolled over, and "15:15" intraday — so the same
// row read as three kinds of thing. The library still decides the tick SPACING
// (it hands us the format string it would have used); this only decides how the
// result is spelled: "15:15" for an intraday tick, "05 Aug" for a date one, and
// the full "05 Aug 2026 15:15" wherever a single moment is quoted.
const fmtDate = (_dtf: Intl.DateTimeFormat, timestamp: number, format: string, type: FormatDateType) => {
  const d = new Date(timestamp + IST_MS);
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const mon = d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
  const hm = `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
  if (type === FormatDateType.XAxis) return format.includes("HH") ? hm : `${dd} ${mon}`;
  return `${dd} ${mon} ${d.getUTCFullYear()} ${hm}`;
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

/** What a level line carries. `label: false` draws the line and no name. */
type TagData = { text: string; label?: boolean };

// A level line, with its name written ON the line rather than stamped into the
// price scale.
//
// It used to put every label in the y-axis gutter, right-aligned to the axis
// edge. With a dozen levels — which is the normal count here, not the worst case
// — that gutter became a solid wall of coloured chips: they overlapped each
// other, the longer names ("Prev Day High", "Call OI Wall") ran off the left of
// the axis and were clipped mid-word, and they buried the price ticks. The one
// column of a price chart that must always be readable is the price.
//
// So: the price scale carries prices (plus SPOT, the single line worth pinning
// there), and a level's identity rides on the line, which is where the eye
// already is. Both figures ignore events — the built-in tag consumes the drag,
// and levels stacked near spot made the axis dead to the mouse and to touch.
registerOverlay({
  name: "levelTag",
  totalStep: 2,
  lock: true,
  needDefaultPointFigure: false,
  needDefaultXAxisFigure: false,
  needDefaultYAxisFigure: false,
  createPointFigures: ({ overlay, coordinates, bounding }) => {
    const d = (overlay.extendData ?? {}) as TagData;
    const y = coordinates[0].y;
    const figures: ReturnType<NonNullable<Parameters<typeof registerOverlay>[0]["createPointFigures"]>> = [{
      type: "line",
      attrs: { coordinates: [{ x: 0, y }, { x: bounding.width, y }] },
      ignoreEvent: true,
    }];
    if (d.text && d.label !== false) {
      // Sits just above its own line, at the left margin, so it never covers the
      // most recent bars — the ones being read.
      figures.push({
        type: "text",
        attrs: { x: 4, y: y - 3, text: d.text, align: "left", baseline: "bottom" },
        ignoreEvent: true,
      });
    }
    return figures;
  },
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
      // The last-price chip sits ON TOP of whatever axis tick shares its row —
      // the library draws both, it does not hide the one underneath. So the chip
      // has to be at least as wide as a tick or the tick's tail shows past it.
      // It was 11px against 12px ticks, which is exactly what left a stray digit
      // hanging off the chip's right edge. Same size, and padding to spare.
      last: { upColor: C.up, downColor: C.down, noChangeColor: C.muted,
        text: { color: C.void, size: 12, paddingLeft: 6, paddingRight: 6 } },
    },
    // The desk legend, in the order every terminal writes it. The library's own
    // default spelled out "Time: … Open: … High: …" as one long grey sentence;
    // this is the OHLC line a trader actually reads, with the values taking the
    // bar's own direction so the colour says something.
    tooltip: {
      showType: TooltipShowType.Standard,
      text: { color: C.mist, size: 12, marginLeft: 8, marginTop: 6 },
      rect: { color: "transparent", borderColor: "transparent" },
      custom: ({ current }: { current: KLineData }) => {
        const tone = current.close >= current.open ? C.up : C.down;
        const n = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return ([["O", current.open], ["H", current.high], ["L", current.low], ["C", current.close]] as const)
          .map(([k, v]) => ({ title: { text: `${k} `, color: C.faint }, value: { text: n(v), color: tone } }));
      },
    },
  },
  indicator: {
    tooltip: { text: { color: C.muted, size: 11 } },
    lastValueMark: { show: false },
  },
  // Axis text was #545c6b on a near-black pane — about 3:1, under WCAG AA for
  // small text, and the first thing anyone squinted at. The ticks are the chart's
  // units; they read at #b6bdcc (~8:1) and one size larger again at 12px, which
  // is where "24,800.00" stops needing a second look.
  //
  // The price scale is pinned to a fixed width rather than sized to its content:
  // it is the column the eye returns to, and an axis that changes width as the
  // range moves makes the whole chart shift under the cursor.
  xAxis: {
    axisLine: { color: C.line }, tickLine: { color: C.line },
    tickText: { color: C.mist, size: 12, marginStart: 6, marginEnd: 6 },
  },
  yAxis: {
    size: 76, axisLine: { color: C.line }, tickLine: { color: C.line },
    tickText: { color: C.mist, size: 12, marginStart: 8, marginEnd: 8 },
  },
  separator: { color: C.line },
  crosshair: {
    horizontal: { line: { color: C.mist }, text: { backgroundColor: C.frost, color: C.void, size: 12, weight: "bold" } },
    vertical: { line: { color: C.mist }, text: { backgroundColor: C.frost, color: C.void, size: 12, weight: "bold" } },
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
  prefsScope = "fno", compact = false, res: resProp, onRes,
}: {
  symbol: string;
  /** the name the tick socket knows this index by ("nifty50"); omit for no stream */
  liveKey?: string | null;
  /** daily OHLC, already fetched by the page from /api/history */
  data: Candle[];
  levels?: Level[];
  spot?: number | null;
  /** px, or "fill" to take the height of the grid cell this chart sits in */
  height?: number | "fill";
  timeframe?: Timeframe;
  onTimeframe?: (tf: Timeframe) => void;
  /** which saved setup this chart owns. Charts sharing a page must not share
   *  one — each writes the whole prefs object on every change. */
  prefsScope?: string;
  /** one toolbar row plus an overflow menu, for a pane too narrow for three */
  compact?: boolean;
  /** with `onRes`, the resolution is the caller's to own (a page persists it per
   *  pane); without them the chart keeps its own, opening on 15m */
  res?: ResLabel;
  onRes?: (r: ResLabel) => void;
}) {
  const [ownRes, setOwnRes] = useState<ResLabel>("15m");
  const res = resProp ?? ownRes;
  const setRes = (r: ResLabel) => (onRes ? onRes(r) : setOwnRes(r));
  const [type, setType] = useState<ChartType>("candles");
  const [scale, setScale] = useState<Scale>("normal");
  const [ind, setInd] = useState<Record<IndKey, boolean>>({
    MA: false, EMA: false, BOLL: false, VWAP: false, TWAP: false, VOL: true, RSI: false, MACD: false, KDJ: false,
  });
  const [intra, setIntra] = useState<Fetch>({ status: "ok", bars: [] });
  const [tool, setTool] = useState<string | null>(null);
  const [magnet, setMagnet] = useState(false);
  const [ready, setReady] = useState(false);
  const [lastTickAt, setLastTickAt] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [showLevels, setShowLevels] = useState(true);
  const [help, setHelp] = useState(false);
  const [guide, setGuide] = useState(false);
  const [picker, setPicker] = useState(false);
  const [more, setMore] = useState(false);   // compact mode's overflow menu
  // Levels hidden by name. Absent = drawn, so a level the engine adds later shows
  // up rather than inheriting someone's old filter.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // Index of the bar the keyboard cursor sits on. A canvas cannot be read by a
  // screen reader and cannot be reached by Tab, so this is how the chart is read
  // without a mouse: the cursor walks the bars and every stop is announced.
  const [cursor, setCursor] = useState<number | null>(null);

  // Per instance: a page can hold several charts, and a literal id would give
  // them all the same one — every chart's description resolving to the first.
  // The same value doubles as this chart's writer token for drawings, which
  // needs exactly the same property: unique per instance.
  const readoutId = useId();

  // Saved setup is applied AFTER the first render, not read into useState: the
  // server renders this markup too, and localStorage on the client would make the
  // two disagree. One extra paint beats a hydration mismatch.
  const restored = useRef(false);
  useEffect(() => {
    migrateLegacyPrefs(prefsScope);
    const p = readJson<Partial<Prefs>>(prefsKey(prefsScope), {});
    if (p.type) setType(p.type);
    if (p.scale) setScale(p.scale);
    if (typeof p.showLevels === "boolean") setShowLevels(p.showLevels);
    // Merged, not replaced — an indicator added in a later build must not be
    // dropped because an older saved object had no key for it.
    if (p.ind) setInd((cur) => ({ ...cur, ...p.ind }));
    if (Array.isArray(p.hidden)) setHidden(new Set(p.hidden.filter((h) => typeof h === "string")));
    restored.current = true;
  }, [prefsScope]);

  useEffect(() => {
    if (!restored.current) return;   // don't write defaults over the saved setup
    writeJson(prefsKey(prefsScope), { type, scale, showLevels, ind, hidden: [...hidden] } satisfies Prefs);
  }, [prefsScope, type, scale, showLevels, ind, hidden]);

  const spec = RESOLUTIONS.find((r) => r.label === res)!;
  const intraday = res !== "1D";
  const { subscribe } = useMarketWs();

  // ---- data ---------------------------------------------------------------

  // Daily rows are "YYYY-MM-DD"; stored at UTC midnight of the trading date and
  // read back in IST (see istDate). Non-increasing rows are dropped rather than
  // handed to the chart out of order.
  //
  // Memoised on `data`, and that is not a micro-optimisation: a new array every
  // render re-runs the data effect below, whose incremental branch replays every
  // stored bar from `lastRef` forward. On 1D the folded live bar carries the
  // stored bar's own timestamp, so the replay overwrote the tick with the API's
  // settled close — inside the same frame — while the pill still said streaming.
  const daily: KLineData[] = useMemo(() => data
    .map((d) => ({
      timestamp: Date.parse(`${d.t}T00:00:00Z`),
      open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume,
    }))
    .filter((b, i, a) => Number.isFinite(b.timestamp) && (i === 0 || b.timestamp > a[i - 1].timestamp)), [data]);

  useEffect(() => {
    if (!intraday) return;
    let alive = true;
    setIntra({ status: "loading", bars: [] });
    const load = () => {
      // Rounded to the poll cycle, so two charts on the same (symbol, resolution)
      // build the SAME url and share one request. The raw seconds would differ by
      // whenever each of them mounted and coalesce nothing.
      const to = Math.floor(Date.now() / INTRADAY_POLL_MS) * (INTRADAY_POLL_MS / 1000);
      const from = to - spec.days * 86400;
      getOnce<any>(
        `/api/udf/history?symbol=${encodeURIComponent(symbol)}&resolution=${spec.res}&from=${from}&to=${to}`,
        INTRADAY_POLL_MS - 5_000,
      )
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
  const pendingRef = useRef<string | null>(null);  // the overlay an armed tool is waiting on
  // Spot for the levels effect to read without depending on it — see below.
  const spotRef = useRef<number | null | undefined>(spot);
  spotRef.current = spot;

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const chart = init(el, { timezone: "Asia/Kolkata", styles: STYLES, customApi: { formatDate: fmtDate } });
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

  // The box's own height, which only "fill" needs: in a grid cell the pane
  // decides it, not this component. It also replaces the resize-on-expand
  // effect — expanding changes the box, and so does a preset switch, a window
  // resize and a sidebar collapse, none of which this component would hear about.
  const [boxH, setBoxH] = useState(0);
  const [boxW, setBoxW] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      setBoxH(el.clientHeight);
      setBoxW(el.clientWidth);
      chartRef.current?.resize();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Level names are placed by pixel position, so anything that moves a price up
  // or down the pane invalidates that placement. Zooming, panning and dragging
  // the axis all do, and none of them re-render React — so without this the
  // labels stayed where the LAST level-set change put them and collapsed into an
  // unreadable stack as soon as the chart was touched.
  //
  // Coalesced to one frame: a zoom gesture fires these continuously, and the
  // work behind the bump is a pickLabels pass plus a cheap signature compare
  // that draws nothing when the chosen set has not actually changed.
  const [relayout, setRelayout] = useState(0);
  /** What the level group was last drawn from. Zoom and resize now fire the
   *  levels effect continuously; this is what keeps that from meaning continuous
   *  overlay rebuilds. */
  const sigRef = useRef("");
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !ready) return;
    let frame = 0;
    const bump = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => { frame = 0; setRelayout((n) => n + 1); });
    };
    const types = [ActionType.OnZoom, ActionType.OnScroll, ActionType.OnVisibleRangeChange, ActionType.OnPaneDrag];
    for (const t of types) chart.subscribeAction(t, bump);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      for (const t of types) chart.unsubscribeAction(t, bump);
    };
  }, [ready]);

  // What an indicator sub-pane sizes off. 440 is the first-paint fallback in fill
  // mode, before the observer has measured anything.
  const paneH = height === "fill" ? boxH || 440 : height;

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
      if (width > 0) chart.setBarSpace(openBarSpace(width, bars.length, intraday));
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
          : chart.createIndicator(i.key, false, { id: i.pane, height: Math.round(paneH * 0.22) });
        if (id) panesRef.current[i.key] = id;
      } else if (!want && paneId) {
        chart.removeIndicator(paneId, i.key);
        delete panesRef.current[i.key];
      }
    }
  }, [ind, hasVol, paneH]);

  // Levels and zones (T7), redrawn as one locked group. KIND_COLOR is imported
  // from the ladder so the two cannot drift apart on colour.
  //
  // Weight is the whole point of this pass. Twelve levels is the ordinary count,
  // and every one of them used to be drawn dashed, at full saturation, up to 3px
  // thick, across the entire pane — so the reference grid shouted louder than the
  // price it was there to describe. They are now hairlines at partial opacity:
  // present when looked for, silent otherwise, which is how a professional chart
  // carries its levels.
  //
  // It also means BROKEN finally looks different. Everything was dashed before,
  // so the one distinction that matters — this level failed — was carried by
  // opacity alone. Intact is solid now; dashed means broken, nothing else.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !ready) return;
    if (!showLevels) {
      chart.removeOverlay({ groupId: "levels" });
      sigRef.current = "";
      return;
    }

    // Which levels get their name written on them — see lib/chart-layout.
    //
    // Re-run on every zoom, pan, axis drag and resize (via `relayout`/`boxH`),
    // because all of those move a price up or down the pane and a name placed
    // for the old geometry is a name in the wrong place. It is cheap: the pass
    // below is N convertToPixel calls, and the signature guard means a gesture
    // that does not change WHICH names fit draws nothing at all.
    const yOf = (value: number): number | null => {
      try {
        const c = chart.convertToPixel({ value }, { paneId: "candle_pane" }) as { y?: number };
        return typeof c?.y === "number" && Number.isFinite(c.y) ? c.y : null;
      } catch { return null; }
    };
    // Reserved: the OHLC legend's own band at the top left, which is where the
    // labels also live — a level near the top of the range used to print its name
    // straight through "O 24,570.20 H 24,624.65" — and SPOT, which is not one of
    // `levels` and always draws, so it claims its space before the contest rather
    // than being written over by whichever level sits a few points from price.
    //
    // Spot is READ FROM A REF, not depended on: it moves with the tape, and a
    // dependency here is what made every tick rebuild all ~19 level overlays.
    // The cost is that thinning is decided against spot as it stood when the
    // level set last changed, so after a long drift a name can end up a few
    // pixels from the SPOT chip — the same staleness pickLabels already accepts
    // for the y-axis.
    const s = spotRef.current;
    const spotY = s != null && Number.isFinite(s) ? yOf(s) : null;
    const labelled = pickLabels(
      levels.filter((l) => !hidden.has(l.label))
        .map((l) => ({ label: l.label, strength: l.strength, y: yOf(l.price) })),
      spotY == null ? [LEGEND_Y] : [LEGEND_Y, spotY],
    );

    // How wide a name may be, at this pane's width. A split pane is not a
    // narrower version of a full one — the same compound label that reads fine
    // at 1400px overran the canvas at 480 and was clipped mid-word.
    const budget = labelBudget(boxW || 900);

    // Everything that decides what gets DRAWN, in one string. A zoom or a resize
    // that leaves the same names in the same fitted form is a no-op here, so the
    // overlay churn this run removed does not come back through the new triggers.
    const sig = JSON.stringify([
      symbol, res, budget, [...labelled].sort(),
      levels.filter((l) => !hidden.has(l.label)).map((l) => [l.label, l.price, l.crossed, l.strength, l.lo, l.hi]),
    ]);
    if (sig === sigRef.current) return;
    sigRef.current = sig;

    chart.removeOverlay({ groupId: "levels" });
    const items: OverlayCreate[] = [];
    for (const l of levels) {
      if (hidden.has(l.label)) continue;
      const color = KIND_COLOR[l.kind ?? ""] ?? l.color;
      const broken = !!l.crossed;
      if (l.lo != null && l.hi != null && l.hi > l.lo) {
        items.push({
          name: "zoneBand", groupId: "levels", lock: true,
          points: [{ value: l.hi }, { value: l.lo }],
          styles: { rect: { style: PolygonType.Fill, color: fade(color, broken ? 0.06 : 0.14), borderSize: 0, borderColor: "transparent" } },
        });
      }
      items.push({
        name: "levelTag", groupId: "levels", lock: true,
        points: [{ value: l.price }],
        extendData: {
          text: shortLevelLabel(l.label, budget, broken),
          label: labelled.has(l.label),
        } satisfies TagData,
        styles: {
          line: {
            // A strong level earns opacity, not thickness. Every line is 1px.
            color: fade(color, broken ? 0.34 : 0.4 + Math.min(0.32, (l.strength ?? 0) / 300)),
            style: broken ? LineType.Dashed : LineType.Solid,
            dashedValue: [4, 4],
            size: 1,
          },
          // Coloured text on the pane's own background, not white-on-saturated:
          // a chip per level is what made the old axis a wall of colour.
          text: {
            color: broken ? fade(color, 0.75) : color,
            backgroundColor: fade(C.void, 0.72),
            size: 11, paddingLeft: 4, paddingRight: 4, paddingTop: 1, paddingBottom: 1, borderRadius: 3,
          },
        },
      });
    }
    if (items.length) chart.createOverlay(items);
  }, [levels, ready, showLevels, hidden, scale, res, symbol, relayout, boxH, boxW]);

  // SPOT, in a group of its own — it is the one line here that moves with the
  // tape. Drawn with the levels it shared their fate: every tick destroyed and
  // recreated all ~19 level overlays, each with a convertToPixel, several times a
  // second. One overlay per tick instead.
  //
  // No price-scale chip: the chart folds live ticks into its last bar, so the
  // library's own last-price mark already sits at this exact height and the two
  // tags landed on top of each other, each clipping the other. The scale keeps one
  // price marker; SPOT keeps the full-width line, which is the part that is
  // actually worth having.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !ready) return;
    chart.removeOverlay({ groupId: "spot" });
    if (!showLevels || spot == null || !Number.isFinite(spot)) return;
    chart.createOverlay({
      name: "levelTag", groupId: "spot", lock: true, points: [{ value: spot }],
      extendData: { text: "SPOT" } satisfies TagData,
      styles: {
        line: { color: C.accent, style: LineType.Solid, size: 1 },
        text: {
          color: C.void, backgroundColor: C.accent, size: 11,
          paddingLeft: 5, paddingRight: 5, paddingTop: 1, paddingBottom: 1, borderRadius: 3,
        },
      },
    });
  }, [spot, ready, showLevels]);

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
      setLastTickAt(Date.now());
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveKey, spec.minutes]);

  useEffect(() => { setLastTickAt(null); }, [symbol, res]);

  // Liveness is the age of the last tick, not a flag the first one latched: the
  // tape stops at 15:30 and nothing arrives to switch a flag back off. Sampling
  // the clock is what makes the claim expire on its own; 5s is well inside the
  // 15s window, and one timer per chart is cheaper than a shared clock's
  // bookkeeping.
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    if (!liveKey) return;
    const id = setInterval(() => setClock(Date.now()), 5_000);
    return () => clearInterval(id);
  }, [liveKey]);
  const streaming = isStreaming(lastTickAt, clock);

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
    // Through the store's wrapper, not writeJson: another chart on this symbol
    // has to hear about the write or it keeps a stale set and overwrites this
    // one on its next save.
    if (saved.length) writeDrawings(symbol, saved, readoutId);
    else clearDrawings(symbol, readoutId);
  };

  const track = (name: string) => ({
    onDrawEnd: (e: { overlay: { id: string } }) => {
      drawnRef.current.push(e.overlay.id);
      pendingRef.current = null;          // finished — no longer cancellable
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
    // Arming a second tool abandons the first one's overlay — it carries no
    // points and no id on the undo stack, so nothing else would ever remove it.
    if (pendingRef.current) chart.removeOverlay(pendingRef.current);
    setTool(name);
    const id = chart.createOverlay({
      ...track(name), groupId: "draw",
      mode: magnet ? OverlayMode.WeakMagnet : OverlayMode.Normal,
    });
    // The armed overlay exists from this moment, with no points on it yet and no
    // id on the undo stack. Held so cancelling can remove exactly it.
    pendingRef.current = typeof id === "string" ? id : null;
  };

  // Changing your mind about an armed tool throws away the unfinished overlay and
  // NOTHING else. This used to clear the whole "draw" group and the symbol's saved
  // drawings, so Esc on an armed trendline deleted every trendline ever saved for
  // NIFTY — unrecoverably, and now instantly in every other pane on that symbol
  // too, since the write is broadcast. The bin below is the control that wipes.
  const cancelTool = () => {
    const id = pendingRef.current;
    if (id) chartRef.current?.removeOverlay(id);
    pendingRef.current = null;
    setTool(null);
  };

  /** The bin: every drawing on this symbol, saved ones included. Deliberate,
   *  labelled as such, and reachable from one button only. */
  const clearAllDrawings = () => {
    chartRef.current?.removeOverlay({ groupId: "draw" });
    drawnRef.current = [];
    pendingRef.current = null;
    clearDrawings(symbol, readoutId);
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
  const [drawSeq, setDrawSeq] = useState(0);
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
  }, [symbol, ready, drawSeq]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Someone else drew on this symbol — another pane on this page, or another tab.
  // Forget which symbol is drawn and the effect above recreates the group from
  // storage; recreating it here as well is how the two copies would drift apart.
  // Programmatic overlays fire no onDrawEnd, so this cannot loop back into a save.
  useEffect(() => onDrawingsChanged(symbol, (token) => {
    if (token === readoutId) return;        // our own write, already on screen
    drawnFor.current = "";
    setDrawSeq((n) => n + 1);
  }), [symbol, readoutId]);

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
    if (width > 0 && bars.length) chart.setBarSpace(openBarSpace(width, bars.length, intraday));
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
      if (help || guide || picker || more) { setHelp(false); setGuide(false); setPicker(false); setMore(false); }
      else if (tool) cancelTool();
      else if (cursor != null) setCursor(null);
      else setExpanded(false);
    }
  };

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

  // Coverage and every caveat that goes with it, as ONE string rather than four
  // spans: compact mode has to be able to put it somewhere other than under the
  // canvas, and a title attribute or a popover cannot take JSX. Laid out below
  // the chart it reads exactly as it did as spans.
  const notes = [
    showEmpty ? "" : coverage,
    !hasVol && bars.length > 0
      ? `no volume drawn: ${noVolWhy}, and a fabricated one would be worse than none` : "",
    ind.VWAP && !hasVol ? "VWAP needs volume, so it is not drawn here" : "",
    (ind.VWAP || ind.TWAP) && !intraday
      ? `on daily bars ${ind.VWAP && ind.TWAP ? "VWAP and TWAP are" : ind.VWAP ? "VWAP is" : "TWAP is"} anchored`
        + " once to the first bar loaded, not re-anchored per session — a per-bar anchor would only redraw"
        + " each bar's own typical price" : "",
  ].filter(Boolean).join(" · ");

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

  // ---- toolbar ------------------------------------------------------------

  // Every control, defined once and laid out twice. A 480px grid cell cannot take
  // the three-row toolbar this chart was built with — it wraps to ~140px and eats
  // a third of the pane — so `compact` folds everything but the resolution and the
  // scale into an overflow menu. Same handlers, same state, same aria-pressed: a
  // second implementation is a second thing to keep in step, and it would not stay.
  const resPills = (
    <Pills options={RESOLUTIONS.map((r) => ({ label: r.label, value: r.label }))} value={res} onChange={setRes} title="Resolution" />
  );
  const rangePills = !intraday && onTimeframe
    ? <Pills options={RANGES.map((r) => ({ label: r, value: r }))} value={timeframe ?? "1Y"} onChange={onTimeframe} title="Daily range" />
    : null;
  const typePills = <Pills options={TYPES} value={type} onChange={setType} title="Series type" />;
  const scaleToggles = (
    <>
      <Toggle on={scale === "log"} onClick={() => setScale((s) => (s === "log" ? "normal" : "log"))}>LOG</Toggle>
      <Toggle on={scale === "percent"} onClick={() => setScale((s) => (s === "percent" ? "normal" : "percent"))}>%</Toggle>
    </>
  );
  const indicatorToggles = INDICATORS.map((i) => {
    const blocked = "needsVolume" in i && i.needsVolume && !hasVol;
    return (
      <Toggle key={i.key} on={ind[i.key] && !blocked} disabled={blocked}
        title={blocked ? noVolWhy : undefined}
        onClick={() => setInd((p) => ({ ...p, [i.key]: !p[i.key] }))}>
        {i.label}
      </Toggle>
    );
  });

  // Drawing tools. A tool arms one overlay: click the chart to place its points,
  // and the tool disarms itself when the drawing is finished.
  const drawTools = (
    <>
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
      <button onClick={clearAllDrawings} title="Remove every drawing, saved ones included" aria-label="Remove every drawing"
        className="rounded-[7px] bg-void p-1.5 text-muted transition-colors hairline hover:text-mist">
        <Trash2 size={14} />
      </button>
    </>
  );

  const drawHint = tool
    ? "Click the chart to place the drawing's points."
    : `Drawings and this setup are saved in this browser, per index — ${symbol} here.`;

  // Liveness, in the two states it can honestly be in. No tick ever seen draws
  // nothing at all — an empty claim is worse than none.
  const streamPill = lastTickAt == null ? null : (
    <span className="mr-1 inline-flex shrink-0 items-center gap-1.5 text-[10.5px] text-mist"
      title={streaming ? "ticks are arriving now" : "the time of the last tick — the tape has gone quiet since"}>
      <span className={cn("h-1.5 w-1.5 rounded-full", streaming ? "bg-up" : "bg-faint")} />
      {streaming ? "streaming" : label(lastTickAt)}
    </span>
  );

  const panelButtons = (
    <>
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
    </>
  );

  return (
    <div className={cn("space-y-2.5",
      // Fill mode: the cell owns the height, so the chrome takes what it needs
      // and the canvas below takes the rest.
      height === "fill" && "flex h-full min-h-0 flex-col gap-2.5 space-y-0",
      // Every row of chrome in a pane is a row the candles do not get (R42).
      height === "fill" && compact && "gap-1.5",
      expanded && "fixed inset-0 z-50 overflow-auto bg-void p-4")}>
      {expanded && (
        <div className="flex items-baseline gap-2">
          <h2 className="text-[13px] font-semibold text-frost">{symbol} · {res}</h2>
          <span className="text-[11px] text-faint">Esc or F to collapse</span>
        </div>
      )}

      {compact ? (
        <div className="flex items-center gap-1">
          {resPills}
          <div className="inline-flex items-center gap-1">{scaleToggles}</div>
          <div className="ml-auto inline-flex items-center gap-1">
            {streamPill}
            <div className="relative">
              <button onClick={() => setMore((v) => !v)} aria-pressed={more}
                title="Everything else on this chart" aria-label="Everything else on this chart"
                className={cn("rounded-[7px] p-1.5 transition-colors hairline",
                  more ? "bg-raised text-accent" : "bg-void text-muted hover:text-mist")}>
                <MoreHorizontal size={14} />
              </button>
              {more && (
                <div className="absolute right-0 top-full z-20 mt-1 w-[296px] rounded-[var(--radius-sm)] bg-raised p-2 shadow-lg hairline">
                  <div className="flex flex-wrap items-center gap-1">{rangePills}{typePills}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1">{indicatorToggles}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1">{drawTools}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1">{panelButtons}</div>
                  <p className="mt-1.5 text-[10.5px] leading-snug text-faint">{drawHint}</p>
                  {/* What the pane below has no room to print: which bars these
                      are, over what window, and what is missing from them. */}
                  {notes && <p className="mt-1.5 border-t border-line pt-1.5 text-[10.5px] leading-snug text-faint">{notes}</p>}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {resPills}
            {rangePills}
            {typePills}
            <div className="inline-flex items-center gap-1">{scaleToggles}</div>
            <div className="ml-auto inline-flex flex-wrap items-center gap-1">{indicatorToggles}</div>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            {drawTools}
            <span className="ml-2 text-[10.5px] text-faint">{drawHint}</span>
            <div className="ml-auto inline-flex items-center gap-1">{streamPill}{panelButtons}</div>
          </div>
        </>
      )}

      {/* The canvas itself: reachable by Tab, driven by the keys in KEYS, and
          labelled so a screen reader announces what it is before the cursor
          starts reading bars out of it. */}
      <div className={cn("relative w-full outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
        height === "fill" && !expanded && "min-h-0 flex-1")}
        style={{ height: expanded ? "calc(100vh - 230px)" : height === "fill" ? undefined : height }}
        tabIndex={0} role="application" onKeyDown={onKeyDown}
        aria-label={`${symbol} ${res} price chart, ${bars.length} bars. `
          + `Use the arrow keys to read bar by bar, question mark for the shortcuts.`}
        aria-describedby={readoutId}>
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
          reader. The chart is a canvas — without this it reads as nothing.
          In a pane it is capped at one line with the rest in the title: four
          wrapped lines of prose under a 336px cell is the canvas's height, and
          the canvas is what the cell is for (R42). Never hidden — a keyboard
          user reading bar by bar reads it here. */}
      <p id={readoutId} aria-live="polite" aria-atomic="true"
        title={compact ? readout ?? undefined : undefined}
        className={cn("text-[11.5px] leading-snug tnum", compact && "truncate text-[11px]",
          readout ? "text-mist" : "text-faint")}>
        {readout ?? (bars.length
          ? compact ? "Arrow keys read this chart bar by bar."
            : "Click the chart or press Tab, then use the arrow keys to read it bar by bar."
          : "")}
      </p>

      {/* Coverage and its caveats. Compact hands them to the ⋯ menu instead of
          spending four lines of a grid cell on them — reachable, not deleted. */}
      {!compact && notes && <p className="text-[11px] leading-snug text-faint">{notes}</p>}
    </div>
  );
}
