// Indian-market formatting helpers. All financial display routes through here
// so number style (lakh/crore, tabular signs) is identical everywhere.
//
// Every formatter is null-safe: the live API returns null for fields the DB
// doesn't have (price, changePct, pe…), so a bare n.toLocaleString/n.toFixed
// would throw and blow up the whole page render ("Something went wrong").
// Missing numbers render as an em-dash instead.
type Num = number | null | undefined;
const isNum = (n: Num): n is number => typeof n === "number" && Number.isFinite(n);

export function inr(n: Num, opts: { decimals?: number; compact?: boolean } = {}) {
  if (!isNum(n)) return "—";
  const { decimals = 2, compact = false } = opts;
  if (compact) return "₹" + compactCr(n);
  return "₹" + n.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

// Crore/lakh compaction used across market-cap, turnover, portfolio value.
export function compactCr(n: Num) {
  if (!isNum(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return (n / 1e7).toFixed(2) + " Cr";
  if (abs >= 1e5) return (n / 1e5).toFixed(2) + " L";
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toFixed(0);
}

export function pct(n: Num, withSign = true) {
  if (!isNum(n)) return "—";
  const s = n.toFixed(2) + "%";
  return withSign && n > 0 ? "+" + s : s;
}

export function signed(n: Num, decimals = 2) {
  if (!isNum(n)) return "—";
  const s = Math.abs(n).toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return (n > 0 ? "+" : n < 0 ? "−" : "") + s;
}

// Global % <-> ₹ toggle for price-change displays (see components/layout/ui-store.tsx).
export type ChangeMode = "pct" | "abs";

export function changeText(pctVal: Num, absVal: Num, mode: ChangeMode) {
  if (!isNum(pctVal) && !isNum(absVal)) return "—";
  return mode === "abs" && isNum(absVal) ? "₹" + signed(absVal) : pct(pctVal);
}

// Plain number with a unit, or "—" when the value genuinely isn't known.
export function num(n: Num, opts: { decimals?: number; suffix?: string } = {}) {
  if (!isNum(n)) return "—";
  const { decimals = 2, suffix = "" } = opts;
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }) + suffix;
}

// Market cap: DB stores crore, display wants the compact form. Null-safe.
export function mcap(cr: Num) {
  return isNum(cr) ? "₹" + compactCr(cr * 1e7) : "—";
}

// Sorting comparator value for a nullable metric — missing data sorts last
// rather than being treated as 0 (which would rank empty rows as "cheapest P/E").
export function sortNum(n: Num) {
  return isNum(n) ? n : Number.NEGATIVE_INFINITY;
}

// One rule for the entire app: which color a number gets.
export function trend(n: Num): "up" | "down" | "flat" {
  if (!isNum(n)) return "flat";
  return n > 0 ? "up" : n < 0 ? "down" : "flat";
}

export function trendClass(n: Num) {
  if (!isNum(n)) return "text-muted";
  return n > 0 ? "text-up" : n < 0 ? "text-down" : "text-muted";
}

// Null-safe like every other formatter here. News items can genuinely have no
// publication time — a search hit carries none — and an undated item must
// render as nothing rather than "NaN d ago", which is what an empty string put
// through the old arithmetic produced.
export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const diff = (Date.now() - t) / 1000;
  if (diff < 0) return "just now";
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  return Math.floor(diff / 86400) + "d ago";
}

// Same idea as timeAgo but for a future ISO timestamp (next scheduled run).
export function timeUntil(iso: string) {
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  if (diff <= 0) return "due now";
  if (diff < 60) return "in <1m";
  if (diff < 3600) return "in " + Math.floor(diff / 60) + "m";
  if (diff < 86400) return "in " + Math.floor(diff / 3600) + "h";
  return "in " + Math.floor(diff / 86400) + "d";
}
