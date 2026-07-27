"use client";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { AiBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

// Claude/NIM narrative over the deterministic F&O game plan (services/fno_narrative.py)
// — real numbers only, generated on demand (up to ~90s cold), no scripted text.
export function FnoNarrative({ idx }: { idx: string }) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [text, setText] = useState("");

  const generate = async () => {
    setState("loading");
    try {
      const r = await fetch(`/api/fno/${idx}/narrative`).then((x) => x.json());
      if (r?.ok && r.markdown) { setText(r.markdown); setState("done"); }
      else setState("error");
    } catch {
      setState("error");
    }
  };

  return (
    <Card variant="ai">
      <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="AI Derivatives Read" subtitle="Grounded in the live game plan · Claude/NIM" action={<AiBadge>On demand</AiBadge>} />
      <CardBody>
        {state === "idle" && (
          <Button variant="ai" size="md" className="w-full justify-center" onClick={generate}>
            <Sparkles size={14} />Generate analysis
          </Button>
        )}
        {state === "loading" && <p className="py-4 text-center text-[12.5px] text-muted">Analysing the option chain… (up to ~90s)</p>}
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
