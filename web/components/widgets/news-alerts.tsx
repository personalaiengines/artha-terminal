"use client";
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Bell, ExternalLink, Globe2, X } from "lucide-react";
import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge, ImpactBadge } from "@/components/ui/badge";
import { NewsItem } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

// News alerts are not user-created rows, so they don't live in the `alerts`
// table — they are whatever the news curator flagged high-impact in the current
// cycle. The only state worth persisting is "I have already read this one", and
// that is per-browser, so localStorage is the whole store. NewsItem.id is a
// hash of the article URL (see web/app/api/news/route.ts), so it survives the
// feed re-ranking between polls.
const SEEN_KEY = "artha:news-alerts-seen";
const SEEN_CAP = 200;

function readSeen(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const v = JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeSeen(ids: string[]) {
  try {
    window.localStorage.setItem(SEEN_KEY, JSON.stringify(ids.slice(-SEEN_CAP)));
  } catch {
    // Private mode / quota — the alerts simply keep showing as unread.
  }
}

function AlertDetail({ item, onClose }: { item: NewsItem; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <motion.div className="fixed inset-0 z-[100] flex items-start justify-center p-4 pt-[12vh]"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-abyss/70 backdrop-blur-sm" onClick={onClose} />
      <motion.div role="dialog" aria-modal="true" aria-label="News alert"
        initial={{ y: -12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -8, opacity: 0 }}
        className="relative w-full max-w-2xl overflow-hidden rounded-[var(--radius-lg)] bg-elevated hairline shadow-[var(--shadow-lg)]">
        <div className="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AlertTriangle size={15} className="text-down" />
          <span className="text-[12px] font-semibold uppercase tracking-wide text-mist">News Alert</span>
          <ImpactBadge impact={item.impact} />
          <button onClick={onClose} className="ml-auto text-muted hover:text-frost" aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4">
          <div className="mb-2.5 flex flex-wrap items-center gap-2 text-[11px]">
            <Badge tone="neutral">{item.category}</Badge>
            <Badge tone={item.region === "global" ? "accent" : "neutral"}>
              {item.region === "global" ? <Globe2 size={10} /> : null}{item.region}
            </Badge>
            <span className="font-semibold text-mist">{item.source}</span>
            <span className="text-faint">{timeAgo(item.time)}</span>
          </div>

          <h2 className="text-[18px] font-semibold leading-snug tracking-tight text-frost">{item.headline}</h2>

          {item.summary && (
            <div className="mt-3 rounded-[var(--radius-sm)] bg-ai-soft/25 p-3.5 hairline">
              <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-ai">Why it matters</p>
              <p className="text-[13.5px] leading-relaxed text-mist">{item.summary}</p>
            </div>
          )}

          {item.tickers.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-[11px] text-muted">Names in focus</span>
              {item.tickers.map((t) => (
                <a key={t} href={`/stocks/${t}`}
                  className="rounded-md bg-raised px-2 py-0.5 text-[11.5px] font-medium text-mist tnum hover:text-accent">{t}</a>
              ))}
            </div>
          )}

          <div className="mt-4 flex items-center gap-2 border-t border-line pt-4">
            {item.url && (
              <a href={item.url} target="_blank" rel="noopener noreferrer"
                className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-sm)] bg-accent px-3.5 text-[13px] font-medium text-abyss">
                <ExternalLink size={13} />Read at {item.source}
              </a>
            )}
            <Button variant="ghost" size="sm" onClick={onClose}>Dismiss</Button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

export function NewsAlerts() {
  const items = useApi<NewsItem[]>("/api/news", [], (j) => j.items ?? [], POLL.news);
  // `null` until localStorage has been read — on the first paint everything
  // would otherwise look unread and the toast would flash for already-dismissed
  // alerts. localStorage isn't available during SSR, hence the effect.
  const [seen, setSeen] = useState<string[] | null>(null);
  const [open, setOpen] = useState<NewsItem | null>(null);
  const [toastOff, setToastOff] = useState(false);

  useEffect(() => { setSeen(readSeen()); }, []);

  const alerts = useMemo(() => items.filter((n) => n.impact === "high"), [items]);
  const seenSet = useMemo(() => new Set(seen ?? []), [seen]);
  const unread = seen === null ? [] : alerts.filter((a) => !seenSet.has(a.id));

  const markSeen = (ids: string[]) => {
    setSeen((prev) => {
      const next = [...new Set([...(prev ?? []), ...ids])];
      writeSeen(next);
      return next;
    });
  };

  const view = (item: NewsItem) => { setOpen(item); markSeen([item.id]); };

  if (alerts.length === 0) return null;

  return (
    <>
      <Card className={cn("mb-6", unread.length > 0 && "border-down/30")}>
        <CardBody className="pt-5">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle size={15} className="text-down" />
            <h3 className="text-[14px] font-semibold text-frost">Needs Attention</h3>
            {unread.length > 0 && <Badge tone="down">{unread.length} new</Badge>}
            <span className="text-[11px] text-muted">High-impact headlines flagged by the news curator</span>
            {unread.length > 0 && (
              <button onClick={() => markSeen(alerts.map((a) => a.id))}
                className="ml-auto text-[11.5px] text-muted hover:text-frost">Mark all read</button>
            )}
          </div>

          <div className="space-y-2">
            {alerts.map((a) => {
              const isNew = seen !== null && !seenSet.has(a.id);
              return (
                <button key={a.id} onClick={() => view(a)}
                  className="flex w-full items-center gap-3 rounded-[var(--radius-sm)] bg-void p-3 text-left hairline transition-colors hover:border-accent/40">
                  <span className={cn("h-2 w-2 shrink-0 rounded-full", isNew ? "bg-down" : "bg-line")} />
                  <div className="min-w-0 flex-1">
                    <p className={cn("truncate text-[13px] leading-snug", isNew ? "font-semibold text-frost" : "text-mist")}>
                      {a.headline}
                    </p>
                    <p className="mt-0.5 text-[11px] text-muted">
                      {[a.source, a.region === "global" ? "International" : "India", timeAgo(a.time)]
                        .filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  <span className="shrink-0 text-[11px] text-accent">View</span>
                </button>
              );
            })}
          </div>
        </CardBody>
      </Card>

      {/* Toast — the "you have something to look at" nudge. One per batch: it
          hides as soon as everything is read or the user waves it off. */}
      <AnimatePresence>
        {unread.length > 0 && !toastOff && !open && (
          <motion.div
            initial={{ y: 24, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 16, opacity: 0 }}
            className="fixed bottom-5 right-5 z-[90] w-[min(22rem,calc(100vw-2.5rem))] overflow-hidden rounded-[var(--radius-lg)] bg-elevated hairline shadow-[var(--shadow-lg)]">
            <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
              <Bell size={14} className="text-down" />
              <span className="text-[12px] font-semibold text-frost">
                {unread.length} news alert{unread.length > 1 ? "s" : ""}
              </span>
              <button onClick={() => setToastOff(true)} className="ml-auto text-muted hover:text-frost" aria-label="Dismiss">
                <X size={14} />
              </button>
            </div>
            <div className="px-4 py-3">
              <p className="line-clamp-2 text-[12.5px] leading-snug text-mist">{unread[0].headline}</p>
              <div className="mt-3 flex gap-2">
                <Button variant="primary" size="sm" onClick={() => view(unread[0])}>View full</Button>
                <Button variant="ghost" size="sm" onClick={() => markSeen(alerts.map((a) => a.id))}>Mark all read</Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && <AlertDetail item={open} onClose={() => setOpen(null)} />}
      </AnimatePresence>
    </>
  );
}
