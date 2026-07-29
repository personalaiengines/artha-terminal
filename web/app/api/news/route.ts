import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";
import { NewsItem } from "@/lib/data";

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
function publisher(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
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

// Live LLM-curated market news mapped to the UI NewsItem shape. Sentiment and
// category are derived here; the headline, one-line "why it matters" and the
// source URL all come from the backend, which only keeps links it actually saw
// in the search results.
export async function GET() {
  const live = await fromApi<{ items: any[]; generated_ist?: string }>("/api/news", 14000);
  if (!live?.items?.length) return NextResponse.json({ ok: false, items: [] });

  const items: NewsItem[] = live.items.slice(0, 20).map((n, i) => {
    const url = n.link ?? n.url ?? "";
    const text = `${n.title ?? n.headline ?? ""} ${n.snippet ?? n.summary ?? ""}`;
    return {
      id: `live-${i}`,
      headline: n.title ?? n.headline ?? "Market update",
      source: url ? publisher(url) : (n.source ?? "Newswire"),
      url,
      sentiment: sentiment(text),
      // Curation timestamp, not a per-article publish time — the search
      // backends don't return one, and the old `now - i*30min` ladder was a
      // fabricated "2h ago" on every card.
      time: live.generated_ist ?? new Date().toISOString(),
      summary: n.snippet ?? n.summary ?? "",
      tickers: [],
      // Prefer the derived category — Earnings/Sector/Flows/Corporate are
      // finer than anything the curator emits; fall back to its label.
      category: category(text) === "Markets"
        ? (BACKEND_CATS[n.source] ?? "Markets")
        : category(text),
    };
  });
  return NextResponse.json({ ok: true, items });
}
