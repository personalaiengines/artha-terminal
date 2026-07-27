"use client";
import Link from "next/link";
import { FlaskConical, Sparkles, FileText, Clock, ArrowRight, Plus } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RatingBadge, Badge } from "@/components/ui/badge";
import { Avatar, EmptyState } from "@/components/ui/primitives";
import { ScoreRing } from "@/components/ui/stat";
import { Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";

const TEMPLATES = [
  { title: "Full Deep-Dive", desc: "Fundamentals, technicals, peers, SWOT & verdict", icon: FlaskConical,
    q: "Run a full deep-dive on a high-conviction Indian stock: fundamentals, technicals, peers, SWOT and a clear verdict." },
  { title: "SWOT Analysis", desc: "Strengths, weaknesses, opportunities, threats", icon: FileText,
    q: "Do a SWOT analysis (strengths, weaknesses, opportunities, threats) on a leading Indian large-cap." },
  { title: "Risk Scan", desc: "Deterministic red-flag audit + AI commentary", icon: Sparkles,
    q: "Scan the Indian market for the biggest red-flag risks right now and explain why each matters." },
];

export default function Research() {
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);
  return (
    <div>
      <PageHeader eyebrow="Intelligence" title="AI Research Workspace"
        description="Generate, save, and revisit institutional-grade research reports powered by ARTHA AI."
        actions={<Link href="/ai-analyst"><Button variant="ai" size="sm"><Plus size={14} />New Report</Button></Link>} />

      {/* Templates */}
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {TEMPLATES.map((t) => (
          <Link key={t.title} href={`/ai-analyst?q=${encodeURIComponent(t.q)}`}>
            <Card interactive className="p-5">
              <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-[10px] bg-ai-soft text-ai"><t.icon size={17} /></div>
              <div className="text-[14px] font-semibold text-frost">{t.title}</div>
              <p className="mt-1 text-[12px] text-muted">{t.desc}</p>
              <div className="mt-3 flex items-center gap-1 text-[12px] font-medium text-accent">Start <ArrowRight size={13} /></div>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Recent research */}
        <div className="xl:col-span-2">
          <h3 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-frost"><Clock size={16} className="text-muted" />Recent Research</h3>
          <Card><CardBody><EmptyState icon={<FlaskConical size={22} />} title="No saved reports yet"
            description="ARTHA doesn't persist research reports yet — run a Deep-Dive from AI Analyst or a stock page to generate one live."
            action={<Link href="/ai-analyst"><Button variant="primary" size="sm"><Plus size={14} />New Report</Button></Link>} /></CardBody></Card>
        </div>

        {/* Quick pick */}
        <Card>
          <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="Research a Stock" subtitle="Pick a name to start" />
          <CardBody className="space-y-1">
            {universe.slice(0, 6).map((s) => (
              <Link key={s.symbol} href={`/stocks/${s.symbol}`} className="flex items-center gap-3 rounded-[var(--radius-sm)] px-2.5 py-2 hover:bg-raised/60">
                <Avatar symbol={s.symbol} size={28} />
                <div className="min-w-0"><div className="text-[13px] font-semibold text-frost">{s.symbol}</div><div className="text-[11px] text-muted truncate max-w-[120px]">{s.name}</div></div>
                <RatingBadge rating={s.aiRating} />
              </Link>
            ))}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
