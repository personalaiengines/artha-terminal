"use client";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { AiBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

// Two grounded AI surfaces over the deterministic F&O game plan, one per page —
// they ask different questions, so neither is the other's copy (R2/R15):
//   oi-read        /fno     what CHANGED: where OI moved and which level flipped
//                           (services/fno_oi_read.py)
//   microstructure /options what the VOLATILITY SURFACE prices in: skew + term
//                           (services/fno_narrative.py)
// This component is only the markdown-fetching shell — real numbers, generated
// on demand (up to ~90s cold), no scripted text.
const SOURCES = {
  "oi-read": {
    path: "oi-read",
    title: "AI · What Changed in OI",
    subtitle: "Where the writers moved their defence since the prior session",
    loading: "Reading this session's OI shift…",
  },
  microstructure: {
    path: "narrative",
    title: "AI · Skew & Term Read",
    subtitle: "What the volatility surface prices in across strikes and expiries",
    loading: "Reading the volatility surface…",
  },
} as const;

export type NarrativeSource = keyof typeof SOURCES;

export function FnoNarrative({ idx, source }: { idx: string; source: NarrativeSource }) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [text, setText] = useState("");
  const cfg = SOURCES[source];

  const generate = async () => {
    setState("loading");
    try {
      const r = await fetch(`/api/fno/${idx}/${cfg.path}`).then((x) => x.json());
      if (r?.ok && r.markdown) { setText(r.markdown); setState("done"); }
      else setState("error");
    } catch {
      setState("error");
    }
  };

  return (
    <Card variant="ai">
      <CardHeader icon={<Sparkles size={16} className="text-ai" />} title={cfg.title} subtitle={cfg.subtitle} action={<AiBadge>On demand</AiBadge>} />
      <CardBody>
        {state === "idle" && (
          <Button variant="ai" size="md" className="w-full justify-center" onClick={generate}>
            <Sparkles size={14} />Generate analysis
          </Button>
        )}
        {state === "loading" && <p className="py-4 text-center text-[12.5px] text-muted">{cfg.loading} (up to ~90s)</p>}
        {state === "error" && <p className="py-4 text-center text-[12.5px] text-down">AI backend unreachable or out of quota.</p>}
        {state === "done" && (
          <div className="space-y-2 text-[12.5px] leading-relaxed text-mist">
            {text.split("\n").map((line, i) => line.startsWith("### ")
              ? <div key={i} className="pt-2 text-[12px] font-semibold uppercase tracking-wide text-accent">{line.slice(4)}</div>
              : line.trim() ? <p key={i}>{line}</p> : null)}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
