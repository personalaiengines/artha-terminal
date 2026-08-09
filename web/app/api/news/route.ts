import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";
import { NewsBriefing, NewsItem, SessionPhase } from "@/lib/data";

const POS = /(surge|jump|gain|rise|beat|record|high|profit|upgrade|rally|boost|strong)/i;
const NEG = /(fall|drop|slump|loss|miss|cut|weak|decline|plunge|downgrade|fear|slow)/i;

function sentiment(t: string): NewsItem["sentiment"] {
  return POS.test(t) ? "positive" : NEG.test(t) ? "negative" : "neutral";
}

// Derive a UI category from the headline/summary so the News page filter tabs
// (Macro / Earnings / Sector / Flows / Corporate) actually segment the feed —
// previously every item was hardcoded "Markets" and every other tab was empty.
const CAT_RULES: [RegExp, NewsItem["category"]][] = [
  [/(earnings|q[1-4]\b|quarter|profit|net profit|revenue|results|pat\b|ebitda)/i, "Earnings"],
  [/(rbi|inflation|cpi|wpi|gdp|repo|policy|fed|budget|fiscal|rupee|bond yield|crude|macro)/i, "Macro"],
  [/(fii|dii|inflow|outflow|institutional|fund flow|sip|mutual fund)/i, "Flows"],
  [/(merger|acquisition|acqui|stake|buyback|dividend|board|ipo|fundrais|deal|order win|contract)/i, "Corporate"],
  [/(bank|it |pharma|auto|metal|fmcg|realty|energy|psu|sector|infra|telecom)/i, "Sector"],
];
function category(t: string): NewsItem["category"] {
  for (const [re, cat] of CAT_RULES) if (re.test(t)) return cat;
  return "Markets";
}

// Publisher name from the article URL — the real source. The backend's own
// `source` field holds the curation model's *category* ("Macro", "Global"),
// which is why every card used to be bylined "Markets" instead of the outlet
// that actually published it.
const PUBLISHERS: Record<string, string> = {
  economictimes: "Economic Times", moneycontrol: "Moneycontrol",
  livemint: "Mint", business: "Business Standard", thehindubusinessline: "BusinessLine",
  reuters: "Reuters", bloomberg: "Bloomberg", cnbctv18: "CNBC-TV18",
  ndtvprofit: "NDTV Profit", zeebiz: "Zee Business", financialexpress: "Financial Express",
};
// Hosts whose first label is not the publisher's name. Finnhub hands back
// news.google.com redirect URLs, and taking the stem bylined those cards
// "News" — a masthead that does not exist.
const HOSTS: Record<string, string> = {
  "news.google.com": "Google News",
};

function publisher(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (HOSTS[host]) return HOSTS[host];
    const stem = host.split(".")[0];
    return PUBLISHERS[stem] ?? stem.charAt(0).toUpperCase() + stem.slice(1);
  } catch {
    return "Newswire";
  }
}

// The curation model labels items with its own vocabulary; fold those onto the
// tabs the News page actually renders, or the item shows up under "All" and
// nowhere else.
const BACKEND_CATS: Record<string, NewsItem["category"]> = {
  Markets: "Markets", Stocks: "Markets", Global: "Markets",
  Macro: "Macro", Policy: "Macro",
};

// Stable per-article id. The Alerts page stores "already seen" ids in
// localStorage, so this must not move when the feed re-ranks — hence a hash of
// the article URL rather than the position in the array.
function idFor(url: string, headline: string): string {
  const src = url || headline;
  let h = 0;
  for (let i = 0; i < src.length; i++) h = (Math.imul(31, h) + src.charCodeAt(i)) | 0;
  return `n${(h >>> 0).toString(36)}`;
}

const REGIONS = new Set(["india", "global"]);
const IMPACTS = new Set(["high", "medium", "low"]);

// Live LLM-curated market news mapped to the UI NewsItem shape. Sentiment and
// category are derived here; the headline, one-line "why it matters", region,
// impact and the source URL all come from the backend, which only keeps links
// it actually saw in the search results.
export async function GET() {
  const live = await fromApi<{
    items: any[]; generated_ist?: string; briefing?: NewsBriefing | null; phase?: SessionPhase;
  }>("/api/news", 14000);
  if (!live?.items?.length) return NextResponse.json({ ok: false, items: [] });

  const items: NewsItem[] = live.items.slice(0, 24).map((n) => {
    const url = n.link ?? n.url ?? "";
    const headline = n.title ?? n.headline ?? "Market update";
    const text = `${headline} ${n.snippet ?? n.summary ?? ""}`;
    return {
      id: idFor(url, headline),
      headline,
      source: url ? publisher(url) : (n.source ?? "Newswire"),
      url,
      sentiment: sentiment(text),
      // The article's own publication time, straight from the backend's
      // `published` (RSS <pubDate> / Finnhub `datetime`, ISO-8601 UTC).
      //
      // This used to be the *curation* timestamp, so every card read "just now"
      // however old the story was — a nine-year-old article and one filed ten
      // minutes ago were captioned identically. Empty string when the item is
      // genuinely undated: the UI then shows no time at all, which is honest,
      // where falling back to the curation clock would re-invent the very
      // freshness this replaced.
      time: n.published ?? "",
      summary: n.snippet ?? n.summary ?? "",
      tickers: Array.isArray(n.tickers) ? n.tickers.slice(0, 4) : [],
      // Prefer the derived category — Earnings/Sector/Flows/Corporate are
      // finer than anything the curator emits; fall back to its label.
      category: category(text) === "Markets"
        ? (BACKEND_CATS[n.source] ?? "Markets")
        : category(text),
      region: REGIONS.has(n.region) ? n.region : "india",
      impact: IMPACTS.has(n.impact) ? n.impact : "low",
    };
  });
  return NextResponse.json({
    ok: true, items,
    briefing: live.briefing ?? null,
    phase: live.phase ?? "post_close",
  });
}
