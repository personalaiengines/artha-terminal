"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Activity, AlertTriangle, Eye, Globe2, Moon, Newspaper, Sparkles, Sunrise, TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Segmented, LiveDot, EmptyState } from "@/components/ui/primitives";
import { AiBadge, Badge, ImpactBadge } from "@/components/ui/badge";
import { NewsCard } from "@/components/widgets/news-card";
import { NewsBriefing, NewsItem, SessionPhase } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const CATS = ["All", "Markets", "Macro", "Earnings", "Sector", "Flows", "Corporate"];
const REGIONS = [
  { label: "All", value: "all" },
  { label: "India", value: "india" },
  { label: "Global", value: "global" },
];

// The briefing answers a different question in each session phase, so the card
// says which one it is answering. `phase` is stamped live by the API; the
// briefing carries the phase it was actually written in, and they can differ
// for one curation cycle around the bell — say so rather than pretend.
const PHASE: Record<SessionPhase, { chip: string; title: string; sub: string; tone: "accent" | "up" | "neutral" }> = {
  pre_open: { chip: "Pre-Open", title: "Pre-Open Briefing", tone: "accent",
    sub: "Before the bell — overnight cues and what to watch at 09:15 IST" },
  open: { chip: "Market Open", title: "Mid-Session Briefing", tone: "up",
    sub: "Live — what is actually moving the tape right now" },
  post_close: { chip: "Closed", title: "Post-Close Wrap", tone: "neutral",
    sub: "After the bell — what mattered today, and what carries into tomorrow" },
};
const PHASE_ICON: Record<SessionPhase, typeof Sunrise> = { pre_open: Sunrise, open: Activity, post_close: Moon };

type Feed = { items: NewsItem[]; briefing: NewsBriefing | null; phase: SessionPhase };
const EMPTY: Feed = { items: [], briefing: null, phase: "post_close" };

export default function News() {
  const [cat, setCat] = useState("All");
  const [region, setRegion] = useState("all");
  const feed = useApi<Feed>("/api/news", EMPTY, (j) => ({
    items: j.items ?? [], briefing: j.briefing ?? null, phase: j.phase ?? "post_close",
  }), POLL.news);
  const { items: NEWS, briefing, phase } = feed;

  const items = NEWS.filter(
    (n) => (cat === "All" || n.category === cat) && (region === "all" || n.region === region)
  );
  const [featured, ...rest] = items;
  const attention = NEWS.filter((n) => n.impact === "high");
  const globalWire = NEWS.filter((n) => n.region === "global");

  const senti = {
    pos: NEWS.filter((n) => n.sentiment === "positive").length,
    neg: NEWS.filter((n) => n.sentiment === "negative").length,
    neu: NEWS.filter((n) => n.sentiment === "neutral").length,
  };

  // Which companies today's coverage is actually about. Nothing else in the
  // app derives this — the movers boards rank by price, this ranks by column
  // inches, and the two disagreeing is itself the signal.
  const mentions = useMemo(() => {
    const c = new Map<string, number>();
    for (const n of NEWS) for (const t of n.tickers) c.set(t, (c.get(t) ?? 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [NEWS]);

  const meta = PHASE[phase];
  const Icon = PHASE_ICON[phase];
  const written = briefing ? PHASE[briefing.phase] : null;
  const stalePhase = briefing != null && briefing.phase !== phase;

  return (
    <div>
      <PageHeader eyebrow="Intelligence" title="News Intelligence"
        description="Indian and international coverage, ranked by an AI editor — each headline carries why it matters, who it hits, and a link to the publisher."
        actions={<><Badge tone={meta.tone}><Icon size={11} />{meta.chip}</Badge><LiveDot /></>} />

      {/* Session briefing — the centrepiece. Everything below it is evidence. */}
      <Card variant="ai" className="mb-6">
        <CardHeader
          icon={<Sparkles size={16} className="text-ai" />}
          title={written ? written.title : meta.title}
          subtitle={written ? written.sub : meta.sub}
          action={<AiBadge>{NEWS.length ? `${NEWS.length} headlines read` : "Waiting"}</AiBadge>}
        />
        <CardBody>
          {briefing ? (
            <div className="space-y-4">
              <p className="text-[15px] font-semibold leading-snug tracking-tight text-frost">
                {briefing.headline}
              </p>
              {briefing.points.length > 0 && (
                <ul className="space-y-2">
                  {briefing.points.map((p, i) => (
                    <li key={i} className="flex gap-2.5 text-[13px] leading-relaxed text-mist">
                      <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ai" />
                      <span>{p}</span>
                    </li>
                  ))}
                </ul>
              )}
              {briefing.watch.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 border-t border-line/60 pt-3">
                  <span className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted">
                    <Eye size={12} />Watch next
                  </span>
                  {briefing.watch.map((w, i) => (
                    <span key={i} className="rounded-md bg-void px-2 py-1 text-[12px] text-mist hairline">{w}</span>
                  ))}
                </div>
              )}
              {stalePhase && (
                <p className="text-[11px] text-faint">
                  Written {PHASE[briefing.phase].chip.toLowerCase()}; the session has since moved to {meta.chip.toLowerCase()}. Refreshes on the next curation cycle.
                </p>
              )}
            </div>
          ) : (
            <p className="text-[13px] leading-relaxed text-muted">
              No AI briefing right now — the curation model is unavailable, so the feed below is
              showing raw coverage rather than a ranked read of it.
            </p>
          )}
        </CardBody>
      </Card>

      {/* Needs attention — the same items the Alerts page raises a popup for. */}
      {attention.length > 0 && (
        <Card className="mb-6 border-down/30">
          <CardHeader
            icon={<AlertTriangle size={16} className="text-down" />}
            title="Needs Attention"
            subtitle="Flagged high-impact by the curator"
            action={<Link href="/alerts" className="text-[12px] font-medium text-accent hover:underline">Open in Alerts →</Link>}
          />
          <CardBody className="grid gap-2.5 sm:grid-cols-2">
            {attention.map((n) => (
              <a key={n.id} href={n.url} target="_blank" rel="noopener noreferrer"
                className="group rounded-[var(--radius-sm)] bg-void p-3 hairline transition-colors hover:border-down/50">
                <div className="mb-1.5 flex items-center gap-2 text-[10.5px]">
                  <ImpactBadge impact="high" />
                  <span className="truncate text-muted">{n.source}</span>
                  <span className="ml-auto shrink-0 uppercase tracking-wide text-faint">{n.region}</span>
                </div>
                <p className="text-[13px] font-medium leading-snug text-frost group-hover:text-accent">{n.headline}</p>
                {n.summary && <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-muted">{n.summary}</p>}
              </a>
            ))}
          </CardBody>
        </Card>
      )}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Segmented value={region} onChange={setRegion} options={REGIONS} />
        <Segmented value={cat} onChange={setCat} options={CATS.map((c) => ({ label: c, value: c }))} />
        <span className="text-[11.5px] text-faint">{items.length} of {NEWS.length}</span>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          {featured ? (
            <>
              <NewsCard item={featured} featured />
              <div className="grid gap-3 sm:grid-cols-2">
                {rest.map((n) => <NewsCard key={n.id} item={n} />)}
              </div>
            </>
          ) : (
            <Card><CardBody><EmptyState icon={<Newspaper size={22} />} title="Nothing in this slice"
              description="No headlines match this region and category right now." /></CardBody></Card>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader icon={<TrendingUp size={16} />} title="In the Headlines"
              subtitle="Most-covered names today" />
            <CardBody>
              {mentions.length === 0 ? (
                <p className="text-[12.5px] text-muted">No company was named often enough to rank.</p>
              ) : (
                <div className="space-y-2">
                  {mentions.map(([sym, n]) => (
                    <Link key={sym} href={`/stocks/${sym}`}
                      className="flex items-center gap-2.5 rounded-[var(--radius-sm)] px-1.5 py-1 transition-colors hover:bg-raised">
                      <span className="text-[12.5px] font-semibold text-frost tnum">{sym}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                        <div className="h-full rounded-full bg-accent" style={{ width: `${(n / mentions[0][1]) * 100}%` }} />
                      </div>
                      <span className="w-6 text-right text-[11px] text-muted tnum">{n}</span>
                    </Link>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader icon={<Globe2 size={16} />} title="Global Wire"
              subtitle="International coverage" action={<Badge tone="neutral">{globalWire.length}</Badge>} />
            <CardBody className="space-y-2">
              {globalWire.length === 0 ? (
                <p className="text-[12.5px] text-muted">No international headlines in this cycle.</p>
              ) : globalWire.slice(0, 6).map((n) => (
                <a key={n.id} href={n.url} target="_blank" rel="noopener noreferrer"
                  className="group flex gap-2.5 border-b border-line/50 pb-2 last:border-0">
                  <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                    n.sentiment === "positive" ? "bg-up" : n.sentiment === "negative" ? "bg-down" : "bg-muted")} />
                  <div>
                    <p className="line-clamp-2 text-[12px] font-medium leading-snug text-frost group-hover:text-accent">{n.headline}</p>
                    {/* Undated items exist (a search hit carries no publication
                        time), so the separator has to go with the timestamp. */}
                    <p className="mt-0.5 text-[10.5px] text-muted">
                      {[n.source, timeAgo(n.time)].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                </a>
              ))}
            </CardBody>
          </Card>

          <Card>
            <CardHeader icon={<Activity size={16} />} title="Tone of Coverage" subtitle="Across today's headlines" />
            <CardBody className="space-y-3">
              {([["Positive", senti.pos, "bg-up"], ["Neutral", senti.neu, "bg-muted"], ["Negative", senti.neg, "bg-down"]] as const).map(([k, v, c]) => (
                <div key={k}>
                  <div className="mb-1 flex justify-between text-[12px]"><span className="text-muted">{k}</span><span className="font-semibold text-frost tnum">{v}</span></div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-line"><div className={cn("h-full rounded-full", c)} style={{ width: `${(v / (NEWS.length || 1)) * 100}%` }} /></div>
                </div>
              ))}
              <p className="pt-1 text-[11px] leading-relaxed text-faint">
                Language of the coverage, not a price signal — headlines skew negative in a flat tape.
              </p>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
