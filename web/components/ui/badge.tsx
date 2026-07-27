import { cn } from "@/lib/utils";
import { ReactNode } from "react";
import { Sparkles } from "lucide-react";

type Tone = "neutral" | "accent" | "ai" | "up" | "down" | "warn";
const TONE: Record<Tone, string> = {
  neutral: "bg-raised text-mist hairline",
  accent: "bg-accent-soft/60 text-accent hairline",
  ai: "bg-ai-soft/60 text-ai hairline",
  up: "bg-up-soft/50 text-up",
  down: "bg-down-soft/50 text-down",
  warn: "bg-warn-soft/60 text-warn",
};

export function Badge({
  tone = "neutral", className, children,
}: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
      TONE[tone], className
    )}>
      {children}
    </span>
  );
}

const RATING_TONE: Record<string, Tone> = {
  "Strong Buy": "up", Buy: "up", Hold: "warn", Reduce: "down", Sell: "down",
};
export function RatingBadge({ rating }: { rating: string }) {
  return (
    <Badge tone={RATING_TONE[rating] ?? "neutral"} className="lowercase">
      <span className="capitalize">{rating}</span>
    </Badge>
  );
}

export function AiBadge({ children = "AI" }: { children?: ReactNode }) {
  return (
    <Badge tone="ai"><Sparkles size={10} strokeWidth={2.5} />{children}</Badge>
  );
}

export function SentimentBadge({ s }: { s: "positive" | "negative" | "neutral" }) {
  const map = { positive: "up", negative: "down", neutral: "neutral" } as const;
  return <Badge tone={map[s]}>{s}</Badge>;
}

export function ImpactBadge({ impact }: { impact: "high" | "medium" | "low" }) {
  const map = { high: "down", medium: "warn", low: "neutral" } as const;
  return <Badge tone={map[impact]}>{impact}</Badge>;
}
