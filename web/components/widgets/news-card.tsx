"use client";
import { motion } from "framer-motion";
import { ShieldCheck } from "lucide-react";
import { SentimentBadge, AiBadge } from "@/components/ui/badge";
import { NewsItem } from "@/lib/data";
import { timeAgo } from "@/lib/format";

export function NewsCard({ item, featured = false }: { item: NewsItem; featured?: boolean }) {
  return (
    <motion.article
      whileHover={{ y: -2 }}
      className={`group rounded-[var(--radius-lg)] bg-elevated hairline p-4 transition-shadow hover:shadow-[var(--shadow-md)] ${featured ? "md:p-6" : ""}`}
    >
      <div className="mb-2.5 flex items-center gap-2 text-[11px]">
        <span className="font-semibold text-mist">{item.source}</span>
        <span className="flex items-center gap-0.5 text-up"><ShieldCheck size={11} />{item.credibility}</span>
        <span className="text-faint">·</span>
        <span className="text-muted">{timeAgo(item.time)}</span>
        <span className="ml-auto"><SentimentBadge s={item.sentiment} /></span>
      </div>
      <h3 className={`font-semibold text-frost tracking-tight ${featured ? "text-[19px] leading-snug" : "text-[14px] leading-snug"}`}>
        {item.headline}
      </h3>
      <p className={`mt-2 text-muted ${featured ? "text-[13.5px]" : "text-[12.5px] line-clamp-2"}`}>{item.summary}</p>
      <div className="mt-3 flex items-center gap-2">
        <AiBadge>AI Summary</AiBadge>
        {item.tickers.slice(0, 3).map((t) => (
          <span key={t} className="rounded-md bg-raised px-1.5 py-0.5 text-[10.5px] font-medium text-mist tnum">{t}</span>
        ))}
        <span className="ml-auto rounded-md bg-void px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">{item.category}</span>
      </div>
    </motion.article>
  );
}
