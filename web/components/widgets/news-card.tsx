"use client";
import { motion } from "framer-motion";
import { ExternalLink } from "lucide-react";
import { SentimentBadge, AiBadge } from "@/components/ui/badge";
import { NewsItem } from "@/lib/data";
import { timeAgo } from "@/lib/format";

// The whole card links to the publisher. Previously nothing here was clickable
// — the feed showed an AI one-liner about an article with no way to reach it —
// and the byline was the curation model's category ("Markets") next to a
// fabricated "credibility" score behind a shield icon.
export function NewsCard({ item, featured = false }: { item: NewsItem; featured?: boolean }) {
  const Wrapper: any = item.url ? motion.a : motion.article;
  const linkProps = item.url ? { href: item.url, target: "_blank", rel: "noopener noreferrer" } : {};

  return (
    <Wrapper
      {...linkProps}
      whileHover={{ y: -2 }}
      className={`group flex flex-col rounded-[var(--radius-lg)] bg-elevated hairline p-4 transition-shadow hover:shadow-[var(--shadow-md)] ${
        featured ? "md:p-6" : ""
      } ${item.url ? "cursor-pointer" : ""}`}
    >
      <div className="mb-2.5 flex items-center gap-2 text-[11px]">
        <span className="shrink-0 rounded-md bg-void px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
          {item.category}
        </span>
        <span className="truncate font-semibold text-mist">{item.source}</span>
        <span className="ml-auto shrink-0"><SentimentBadge s={item.sentiment} /></span>
      </div>

      <h3
        className={`font-semibold tracking-tight text-frost ${
          featured ? "text-[19px] leading-snug" : "text-[14px] leading-snug"
        } ${item.url ? "group-hover:text-accent" : ""}`}
      >
        {item.headline}
      </h3>

      {/* The backend's "why it matters" line is the point of the card, so it
          gets room to breathe instead of being clamped to two lines. */}
      {item.summary && (
        <p className={`mt-2 text-muted ${featured ? "text-[13.5px] leading-relaxed" : "text-[12.5px] leading-relaxed line-clamp-4"}`}>
          {item.summary}
        </p>
      )}

      <div className="mt-3 flex items-center gap-2 pt-1">
        <AiBadge>Why it matters</AiBadge>
        {item.tickers.slice(0, 3).map((t) => (
          <span key={t} className="rounded-md bg-raised px-1.5 py-0.5 text-[10.5px] font-medium text-mist tnum">{t}</span>
        ))}
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-[11px] text-faint">
          {/* The article's own publication time. `title` carries the exact
              local timestamp, because "6h ago" is the wrong unit for deciding
              whether a story predates the session you are trading. */}
          {timeAgo(item.time) && (
            <time dateTime={item.time} title={new Date(item.time).toLocaleString("en-IN")}>
              {timeAgo(item.time)}
            </time>
          )}
          {item.url && (
            <span className="flex items-center gap-0.5 text-muted group-hover:text-accent">
              <ExternalLink size={11} />Read
            </span>
          )}
        </span>
      </div>
    </Wrapper>
  );
}
