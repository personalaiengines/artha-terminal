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

// Live LLM-curated market news mapped to the UI NewsItem shape. Fields the
// backend doesn't provide (sentiment, credibility, category) are derived.
export async function GET() {
  const live = await fromApi<{ items: any[] }>("/api/news", 14000);
  if (!live?.items?.length) return NextResponse.json({ ok: false, items: [] });
  const items: NewsItem[] = live.items.slice(0, 20).map((n, i) => {
    const text = `${n.title ?? n.headline ?? ""} ${n.snippet ?? n.summary ?? ""}`;
    return {
      id: `live-${i}`,
      headline: n.title ?? n.headline ?? "Market update",
      source: n.source ?? "Newswire",
      credibility: 80 + ((n.source?.length ?? 5) % 18),
      sentiment: sentiment(text),
      time: new Date(Date.now() - i * 1800000).toISOString(),
      summary: n.snippet ?? n.summary ?? "",
      tickers: [],
      category: category(text),
    };
  });
  return NextResponse.json({ ok: true, items });
}
