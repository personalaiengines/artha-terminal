// The Charts page's grid, as data and pure functions. No React, no DOM.
//
// Everything the page has to decide — how many panes a preset holds, what
// happens to the surplus when the preset shrinks, which ids survive a removal,
// and what a restored layout means — is decided here so it can be tested by
// the node-only runner this repo has. The page above it is then wiring.

import type { ResLabel } from "@/components/widgets/kline-chart";
import { readJson, writeJson } from "./chart-store";

/** Indices only, by binding decision: NIFTY, BANKNIFTY and SENSEX are the three
 *  instruments with both an intraday store and an option chain, so a pane can
 *  always draw candles and a full level map. */
export const INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"] as const;
export type IndexSymbol = typeof INDEX_SYMBOLS[number];

// Duplicated from kline-chart's RESOLUTIONS because importing that module would
// pull klinecharts — and a canvas — into a node test run. `satisfies` keeps the
// two from drifting in the direction that would break a restore: a label dropped
// there fails to compile here.
const RES_LABELS = ["1m", "5m", "15m", "1h", "1D"] as const satisfies readonly ResLabel[];

export const DEFAULT_SYMBOL: IndexSymbol = "NIFTY";
/** What kline-chart itself opens on, and what all three instruments have bars for. */
export const DEFAULT_RES: ResLabel = "15m";

export type Preset = "1" | "2H" | "2V" | "3" | "4" | "6";
export type Pane = { id: string; symbol: IndexSymbol; res: ResLabel };
export type Layout = { preset: Preset; panes: Pane[] };

/** Grid classes per preset. One column below `xl:` (1280px) in every preset —
 *  three columns at that width give 480px panes, which is already the narrowest
 *  a candle stays readable at, so the grid stacks rather than tiling further.
 *  Preset `3` is one full-width pane above two, which is the first cell spanning
 *  both columns; the arbitrary variant keeps that inside the one class string
 *  instead of making the page special-case a cell. */
export const PRESETS: Record<Preset, { panes: number; cls: string }> = {
  "1":  { panes: 1, cls: "grid-cols-1" },
  "2H": { panes: 2, cls: "grid-cols-1 xl:grid-cols-2" },
  "2V": { panes: 2, cls: "grid-cols-1 xl:grid-rows-2" },
  "3":  { panes: 3, cls: "grid-cols-1 xl:grid-cols-2 xl:grid-rows-2 xl:[&>*:first-child]:col-span-2" },
  "4":  { panes: 4, cls: "grid-cols-1 xl:grid-cols-2 xl:grid-rows-2" },
  "6":  { panes: 6, cls: "grid-cols-1 xl:grid-cols-3 xl:grid-rows-2" },
};

/** Presentation order, and the order `addPane` grows through. */
export const PRESET_ORDER: Preset[] = ["1", "2H", "2V", "3", "4", "6"];
export const MAX_PANES = 6;

export const LAYOUT_KEY = "artha.charts.layout.v1";

/** `p{max + 1}`. Ids must be unique for the life of the layout, not just dense:
 *  the per-pane prefs scope is `charts.<id>`, so reusing `p2` after removing it
 *  would hand the new pane the old one's saved indicators. */
export function nextPaneId(panes: Pane[]): string {
  const max = panes.reduce((m, p) => {
    const n = /^p(\d+)$/.exec(p.id);
    return n ? Math.max(m, Number(n[1])) : m;
  }, 0);
  return `p${max + 1}`;
}

const newPane = (panes: Pane[]): Pane => ({ id: nextPaneId(panes), symbol: DEFAULT_SYMBOL, res: DEFAULT_RES });

/** The smallest preset that holds `n` panes. */
const presetFor = (n: number): Preset =>
  PRESET_ORDER.find((p) => PRESETS[p].panes >= n) ?? "6";

export const emptyLayout = (): Layout => ({ preset: "1", panes: [newPane([])] });

/** Grows the preset when the current one is full, which is what "add" means at
 *  a fixed grid — there are no empty slots to fill, every pane holds an
 *  instrument. At 6 it is a no-op and the page disables the control (R3). */
export function addPane(l: Layout): Layout {
  const n = l.panes.length + 1;
  if (n > MAX_PANES) return l;
  const preset = PRESETS[l.preset].panes >= n ? l.preset : presetFor(n);
  return { preset, panes: [...l.panes, newPane(l.panes)] };
}

/** The preset is left alone: the user picked it, and silently re-tiling under
 *  them on a remove is more surprising than a gap. Removing the last pane is a
 *  no-op — a Charts page with no chart is not a state worth having. */
export function removePane(l: Layout, id: string): Layout {
  if (l.panes.length <= 1) return l;
  const panes = l.panes.filter((p) => p.id !== id);
  return panes.length === l.panes.length ? l : { ...l, panes };
}

const patch = (l: Layout, id: string, fn: (p: Pane) => Pane): Layout => {
  const panes = l.panes.map((p) => (p.id === id ? fn(p) : p));
  return { ...l, panes };
};

export const setSymbol = (l: Layout, id: string, symbol: IndexSymbol): Layout =>
  patch(l, id, (p) => ({ ...p, symbol }));

export const setRes = (l: Layout, id: string, res: ResLabel): Layout =>
  patch(l, id, (p) => ({ ...p, res }));

/** Moves the pane *element*, so its id — and with it its prefs scope and its
 *  chart instance's React key — travels to the new position. Swapping the
 *  symbols instead would leave each slot's saved indicators behind. */
export function movePane(l: Layout, id: string, dir: -1 | 1): Layout {
  const i = l.panes.findIndex((p) => p.id === id);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= l.panes.length) return l;
  const panes = [...l.panes];
  [panes[i], panes[j]] = [panes[j], panes[i]];
  return { ...l, panes };
}

/** Returns the panes that no longer fit alongside the new layout, so the page
 *  can ask before throwing away a pane the user set up (R7) rather than asking
 *  on every preset change. Growing pads with new panes so the preset renders
 *  the count it advertises. */
export function setPreset(l: Layout, preset: Preset): { layout: Layout; dropped: Pane[] } {
  const want = PRESETS[preset].panes;
  const panes = l.panes.slice(0, want);
  while (panes.length < want) panes.push(newPane(panes));
  return { layout: { preset, panes }, dropped: l.panes.slice(want) };
}

// ---- restoring what was saved ----------------------------------------------

const isSymbol = (x: unknown): x is IndexSymbol => INDEX_SYMBOLS.includes(x as IndexSymbol);
const isRes = (x: unknown): x is ResLabel => RES_LABELS.includes(x as typeof RES_LABELS[number]);

/**
 * Total. A layout comes back from localStorage, which means it was written by
 * an older build, edited by hand, or truncated — and a Charts page that throws
 * on boot is worse than one that forgets. Every bad part is dropped and the
 * rest kept; a total loss is one default pane.
 *
 * The drops come back with the layout, the way `setPreset` returns them: a chart
 * the user set up disappearing on reload with nothing said about it is
 * indistinguishable from a bug, and R31 asks for a named notice. Sentences
 * rather than codes, because the page's only job with them is to print them.
 *
 * A missing key is not a drop — `null` is what a first visit reads.
 *
 * Accepts the raw string as well as a parsed value so a caller that read the
 * key itself gets the same guarantees.
 */
export function parseLayout(raw: unknown): { layout: Layout; dropped: string[] } {
  const unreadable = (why: string) => ({ layout: emptyLayout(), dropped: [why] });

  let value = raw;
  if (typeof value === "string") {
    try { value = JSON.parse(value); } catch { return unreadable("The saved layout was not readable, so this is a fresh one."); }
  }
  if (value == null) return { layout: emptyLayout(), dropped: [] };
  if (typeof value !== "object") return unreadable("The saved layout was not a layout, so this is a fresh one.");

  const { preset, panes } = value as { preset?: unknown; panes?: unknown };
  const seen = new Set<string>();
  const kept: Pane[] = [];
  const dropped: string[] = [];

  const list = Array.isArray(panes) ? panes : [];
  list.forEach((p, i) => {
    const at = `Chart ${i + 1}`;
    if (typeof p !== "object" || p === null) { dropped.push(`${at} — the saved entry was not a chart.`); return; }
    const { id, symbol, res } = p as { id?: unknown; symbol?: unknown; res?: unknown };
    // An unknown symbol is a dead pane (R31) and a repeated id would give two
    // panes one prefs scope — both drop. A bad resolution only costs the
    // resolution, so that falls back rather than taking the pane with it.
    if (typeof id !== "string" || !id) { dropped.push(`${at} — the saved entry had no id.`); return; }
    if (seen.has(id)) { dropped.push(`${at} — a second chart was saved under the id "${id}".`); return; }
    if (!isSymbol(symbol)) {
      dropped.push(`${at} — "${String(symbol)}" is not one of ${INDEX_SYMBOLS.join(", ")}, the three instruments this page charts.`);
      return;
    }
    seen.add(id);
    kept.push({ id, symbol, res: isRes(res) ? res : DEFAULT_RES });
  });

  // Nothing survived: the per-pane reasons above already say why, and one default
  // pane is what the page opens with.
  if (!kept.length) return { layout: emptyLayout(), dropped };

  const known = typeof preset === "string" && preset in PRESETS ? (preset as Preset) : presetFor(kept.length);
  const fits = kept.slice(0, PRESETS[known].panes);
  for (const p of kept.slice(PRESETS[known].panes)) {
    dropped.push(`${p.symbol} (${p.id}) — the "${known}" layout holds ${PRESETS[known].panes}.`);
  }
  return { layout: { preset: known, panes: fits }, dropped };
}

/** Reads and writes go through chart-store, whose swallow means storage being
 *  unavailable costs the layout and nothing else (R36). */
export const readLayout = (): { layout: Layout; dropped: string[] } =>
  parseLayout(readJson<unknown>(LAYOUT_KEY, null));
export const writeLayout = (l: Layout): void => writeJson(LAYOUT_KEY, l);
