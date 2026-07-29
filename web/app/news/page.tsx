"use client";
import { useState } from "react";
import { Newspaper, Sparkles, TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Segmented, LiveDot } from "@/components/ui/primitives";
import { AiBadge } from "@/components/ui/badge";
import { NewsCard } from "@/components/widgets/news-card";
import { NewsItem } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const CATS = ["All", "Markets", "Macro", "Earnings", "Sector", "Flows", "Corporate"];

export default function News() {
  const [cat, setCat] = useState("All");
  const NEWS = useApi<NewsItem[]>("/api/news", [], (j) => j.items, POLL.news);
  const items = NEWS.filter((n) => cat === "All" || n.category === cat);
  const [featured, ...rest] = items;

  const senti = { pos: NEWS.filter((n) => n.sentiment === "positive").length, neg: NEWS.filter((n) => n.sentiment === "negative").length, neu: NEWS.filter((n) => n.sentiment === "neutral").length };
  const net = senti.pos > senti.neg ? "constructive" : senti.neg > senti.pos ? "cautious" : "mixed";

  return (
    <div>
      <PageHeader eyebrow="Intelligence" title="News Intelligence"
        description="AI-curated market news — each headline carries why it matters and a link to the publisher."
        actions={<LiveDot />} />

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Segmented value={cat} onChange={setCat} options={CATS.map((c) => ({ label: c, value: c }))} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          {featured && <NewsCard item={featured} featured />}
          <div className="grid gap-3 sm:grid-cols-2">
            {rest.map((n) => <NewsCard key={n.id} item={n} />)}
          </div>
        </div>

        <div className="space-y-6">
          <Card variant="ai">
            <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="Sentiment Digest" subtitle="Derived from live coverage" action={<AiBadge>Live</AiBadge>} />
            <CardBody>
              <p className="text-[13px] leading-relaxed text-mist">
                {NEWS.length > 0
                  ? <>Across <span className="font-semibold text-frost">{NEWS.length}</span> live headlines, sentiment reads <span className="font-semibold text-up">{senti.pos}× positive</span> / <span className="font-semibold text-down">{senti.neg}× negative</span> / {senti.neu}× neutral — net <span className="font-semibold text-frost">{net}</span>.</>
                  : <>No live news is available to summarise right now.</>}
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader icon={<TrendingUp size={16} />} title="Sentiment" subtitle="Across today's coverage" />
            <CardBody className="space-y-3">
              {[["Positive", senti.pos, "bg-up"], ["Neutral", senti.neu, "bg-muted"], ["Negative", senti.neg, "bg-down"]].map(([k, v, c]) => (
                <div key={k as string}>
                  <div className="mb-1 flex justify-between text-[12px]"><span className="text-muted">{k}</span><span className="font-semibold text-frost tnum">{v as number}</span></div>
                  <div className="h-1.5 rounded-full bg-line overflow-hidden"><div className={cn("h-full rounded-full", c as string)} style={{ width: `${(v as number) / (NEWS.length || 1) * 100}%` }} /></div>
                </div>
              ))}
            </CardBody>
          </Card>

          <Card>
            <CardHeader icon={<Newspaper size={16} />} title="Live Wire" subtitle="Latest headlines" />
            <CardBody className="space-y-2">
              {NEWS.slice(0, 5).map((n) => (
                <div key={n.id} className="flex gap-2.5 border-b border-line/50 pb-2 last:border-0">
                  <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", n.sentiment === "positive" ? "bg-up" : n.sentiment === "negative" ? "bg-down" : "bg-muted")} />
                  <div><p className="text-[12px] font-medium text-frost leading-snug line-clamp-2">{n.headline}</p><p className="mt-0.5 text-[10.5px] text-muted">{n.source} · {timeAgo(n.time)}</p></div>
                </div>
              ))}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
