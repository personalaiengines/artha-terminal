"use client";

import Link from "next/link";
import { useState } from "react";
import { Activity, Database, Lock, ShieldCheck, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Public landing page.
 *
 * The hero demonstrates the product's one claim rather than asserting it: the
 * figure is clickable and unfolds its own provenance. Every competitor says
 * "trusted data" — this shows the receipt, which is the only version of that
 * claim a reader can check.
 *
 * The numbers below are a static illustration and are labelled as such. Wiring
 * a live quote into a page served to signed-out visitors would leak market data
 * the rest of the app requires a session to see.
 */

const TRACE = [
  { k: "SOURCE", v: <>Upstox WebSocket tick · <b className="text-frost font-[560]">received 0.4s ago</b></> },
  { k: "FALLBACK", v: <>Yahoo Finance REST, used only when the stream goes stale</> },
  { k: "STORED", v: <>Written to <code className="font-mono text-[11px] text-mist">prices_intraday</code></> },
  { k: "IF STALE", v: <>Last confirmed value, <b className="text-frost font-[560]">visibly badged</b> — never a guess</> },
];

const PILLARS = [
  {
    icon: Database,
    title: "Deterministic engines decide",
    body: "Red flags and the 0–10 scorecard are plain Python — auditable and reproducible. The model presents them and cannot recompute, override or soften a finding.",
  },
  {
    icon: Activity,
    title: "Degradation you can see",
    body: "When a feed fails, the last confirmed value stays on screen behind a staleness badge. Never a blank panel, never a plausible-looking invention.",
  },
  {
    icon: Lock,
    title: "Read-only by design",
    body: "Order-placement APIs are never wired. The broker integration can read your book. It cannot trade it.",
  },
];

export default function LandingPage() {
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-abyss text-frost">
      <div className="mx-auto max-w-[1180px] px-6">
        <nav className="flex items-center justify-between py-7">
          <div className="flex items-center gap-2.5">
            <div className="grid h-7 w-7 place-items-center rounded-[var(--radius-xs)] bg-gradient-to-br from-accent to-ai font-mono text-[13px] font-bold text-white">
              A
            </div>
            <b className="text-[15px] font-[640] tracking-[-0.01em]">ARTHA</b>
          </div>
          <div className="flex items-center gap-5">
            <a href="#principles" className="text-[13.5px] text-mist hover:text-frost">
              How it works
            </a>
            <Link href="/login">
              <Button variant="ghost" size="md">Sign in</Button>
            </Link>
          </div>
        </nav>

        <section className="grid items-center gap-14 py-12 lg:grid-cols-[1.05fr_0.95fr]">
          <div>
            <div className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-accent">
              Indian markets · self-hosted
            </div>
            <h1 className="my-4 text-balance text-[clamp(34px,4.6vw,54px)] font-[660] leading-[1.06] tracking-[-0.03em]">
              Every number on screen
              <br />
              <span className="bg-gradient-to-r from-accent to-ai bg-clip-text text-transparent">
                knows where it came from.
              </span>
            </h1>
            <p className="max-w-[46ch] text-[16.5px] leading-relaxed text-mist">
              Live NSE and BSE data, an F&amp;O option-chain and level engine, and an AI
              analyst that reads your database instead of its own memory. It cannot invent
              a figure — that isn&rsquo;t a policy, it&rsquo;s the architecture.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link href="/register">
                <Button variant="primary" size="lg">Create your terminal</Button>
              </Link>
              <Link href="/login">
                <Button variant="secondary" size="lg">Sign in</Button>
              </Link>
            </div>
            <div className="mt-3.5 font-mono text-[12px] tracking-[0.03em] text-faint">
              Free · self-hosted · read-only broker access
            </div>
          </div>

          <div className="rounded-[var(--radius-lg)] bg-elevated p-5 hairline shadow-[var(--shadow-md)]">
            <div className="mb-4 flex items-center justify-between border-b border-line pb-3.5">
              <span className="text-[13px] font-[560] text-mist">NIFTY 50</span>
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                Illustration
              </span>
            </div>

            <button
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="-mx-3 flex w-[calc(100%+1.5rem)] items-baseline gap-3 rounded-[var(--radius-sm)] px-3 py-2.5 text-left transition-colors hover:bg-raised ring-focus"
            >
              <span className="text-[30px] font-[640] leading-none tracking-[-0.025em] tabular-nums">
                24,570.65
              </span>
              <span className="text-[14px] font-[590] leading-none text-up tabular-nums">
                +118.40 · +0.48%
              </span>
              <span className="ml-auto flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.08em] text-faint">
                {open ? "Provenance" : "Click to trace"}
                <ChevronDown size={12} className={open ? "rotate-180 transition-transform" : "transition-transform"} />
              </span>
            </button>

            {open && (
              <div className="mt-3.5">
                <div className="flex flex-col gap-2.5 border-l-2 border-accent-soft pl-4">
                  {TRACE.map((t) => (
                    <div key={t.k} className="flex items-start gap-3 text-[12.5px]">
                      <span className="min-w-[52px] whitespace-nowrap pt-0.5 font-mono text-[10px] tracking-[0.06em] text-accent">
                        {t.k}
                      </span>
                      <span className="text-mist">{t.v}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 rounded-[var(--radius-sm)] border border-ai/30 bg-ai-soft px-3 py-2.5 text-[12px] text-[#cdbdf5]">
                  The AI analyst may explain this figure. It is structurally prevented from
                  producing one.
                </div>
              </div>
            )}
          </div>
        </section>

        <section id="principles" className="grid gap-4 py-16 md:grid-cols-3">
          {PILLARS.map(({ icon: Icon, title, body }) => (
            <div key={title} className="rounded-[var(--radius-lg)] bg-elevated p-6 hairline">
              <div className="mb-3.5 grid h-8 w-8 place-items-center rounded-[var(--radius-xs)] border border-accent/30 bg-accent-soft">
                <Icon size={15} className="text-accent" />
              </div>
              <h3 className="mb-2 text-[15px] font-[600] tracking-[-0.01em]">{title}</h3>
              <p className="text-[13.5px] leading-relaxed text-muted">{body}</p>
            </div>
          ))}
        </section>

        <footer className="flex flex-wrap items-center gap-3 border-t border-line py-7 text-[12px] text-faint">
          <ShieldCheck size={13} />
          <span>
            Research and education only, not investment advice. Signals are soft — HOLD,
            WATCH, REVIEW — never buy or sell.
          </span>
        </footer>
      </div>
    </div>
  );
}
