"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { Sparkles, ArrowUp, ShieldCheck, ChevronDown, TrendingUp, BarChart3, Wallet, Newspaper } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AiBadge, RatingBadge } from "@/components/ui/badge";
import { ScoreRing, DeltaPill } from "@/components/ui/stat";
import { Avatar } from "@/components/ui/primitives";
import { Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

type Msg = { role: "user" | "ai"; text: string; streaming?: boolean; error?: boolean; cards?: string[]; tools?: string[] };

const SUGGESTIONS = [
  { icon: TrendingUp, text: "What's driving Bank Nifty today?" },
  { icon: Wallet, text: "Analyse the risk in my portfolio" },
  { icon: BarChart3, text: "Compare TCS vs Infosys fundamentals" },
  { icon: Newspaper, text: "Summarise this week's market-moving news" },
];

export default function AIAnalystPage() {
  return (
    <Suspense fallback={<div className="py-20 text-center text-muted">Loading…</div>}>
      <AIAnalyst />
    </Suspense>
  );
}

function AIAnalyst() {
  const sp = useSearchParams();
  const initial = sp.get("q");
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);
  const uniMap = new Map(universe.map((s) => [s.symbol, s]));
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);
  const streamIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clear any in-flight typewriter interval on unmount so it doesn't keep
  // calling setState after the component is gone.
  useEffect(() => () => {
    if (streamIntervalRef.current) clearInterval(streamIntervalRef.current);
  }, []);

  // Typewriter that streams a finished answer into the last AI message.
  const streamInto = (full: string, meta: Partial<Msg>) => {
    setMessages((m) => [...m, { role: "ai", text: "", streaming: true, ...meta }]);
    let i = 0;
    const id = setInterval(() => {
      i += 4;
      setMessages((m) => {
        const c = [...m];
        const l = c[c.length - 1];
        if (!l || l.role !== "ai") { clearInterval(id); return c; }
        c[c.length - 1] = { ...l, text: full.slice(0, i), streaming: i < full.length };
        return c;
      });
      if (i >= full.length) clearInterval(id);
    }, 12);
    streamIntervalRef.current = id;
  };

  const send = async (text: string) => {
    if (!text.trim() || thinking) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    setThinking(true);
    try {
      const res = await fetch("/api/ai", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: text }),
      }).then((r) => r.json());
      setThinking(false);
      if (res?.ok && res.answer) {
        streamInto(res.answer, {
          cards: res.cards?.length ? res.cards.filter((c: string) => uniMap.has(c)) : undefined,
          tools: res.tools?.length ? res.tools : undefined,
        });
      } else {
        setMessages((m) => [...m, { role: "ai", text: "ARTHA couldn't produce an answer — the AI backend may be unreachable or out of quota. Try again in a moment.", error: true }]);
      }
    } catch {
      setThinking(false);
      setMessages((m) => [...m, { role: "ai", text: "Network error reaching the ARTHA API. Check that the api container is running.", error: true }]);
    }
  };

  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages, thinking]);
  useEffect(() => { if (initial && !started.current) { started.current = true; send(initial); } }, [initial]);

  const empty = messages.length === 0;

  return (
    <div className="mx-auto flex h-[calc(100vh-8rem)] max-w-3xl flex-col">
      {empty ? (
        <div className="flex flex-1 flex-col items-center justify-center text-center">
          <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="relative mb-6">
            <div className="absolute inset-0 blur-2xl bg-ai/30 rounded-full" />
            <div className="relative flex h-16 w-16 items-center justify-center rounded-[var(--radius-lg)] bg-gradient-to-br from-ai to-accent shadow-[var(--shadow-glow-ai)]">
              <Sparkles size={28} className="text-white" />
            </div>
          </motion.div>
          <h1 className="text-[24px] font-bold tracking-tight text-frost">ARTHA AI Analyst</h1>
          <p className="mt-2 max-w-md text-[14px] text-muted">Ask anything about markets, a stock, or your portfolio. Answers are grounded in live data with inline citations.</p>
          <div className="mt-8 grid w-full max-w-lg grid-cols-1 gap-2.5 sm:grid-cols-2">
            {SUGGESTIONS.map((s) => (
              <button key={s.text} onClick={() => send(s.text)}
                className="group flex items-center gap-3 rounded-[var(--radius-md)] bg-elevated p-3.5 text-left hairline transition-colors hover:bg-raised">
                <span className="flex h-8 w-8 items-center justify-center rounded-[8px] bg-void text-accent"><s.icon size={16} /></span>
                <span className="text-[13px] font-medium text-mist group-hover:text-frost">{s.text}</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div ref={scrollRef} className="flex-1 space-y-6 overflow-y-auto scrollbar-slim pb-4">
          {messages.map((m, i) => m.role === "user" ? (
            <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
              <div className="max-w-[80%] rounded-[var(--radius-lg)] rounded-br-md bg-accent px-4 py-2.5 text-[14px] text-white">{m.text}</div>
            </motion.div>
          ) : (
            <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3">
              <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px]", m.error ? "bg-down-soft text-down" : "bg-gradient-to-br from-ai to-accent")}>
                {m.error ? <ShieldCheck size={15} /> : <Sparkles size={15} className="text-white" />}
              </span>
              <div className="min-w-0 flex-1 space-y-4">
                <div className="flex items-center gap-2"><AiBadge>{m.error ? "ARTHA — Error" : "ARTHA AI"}</AiBadge></div>
                <div className={cn("whitespace-pre-wrap text-[14px] leading-relaxed", m.error ? "text-down" : "text-mist")}>
                  {m.text}{m.streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-ai align-middle" />}
                </div>

                {!m.streaming && m.cards && (
                  <div className="grid gap-2.5 sm:grid-cols-3">
                    {m.cards.map((sym) => { const s = uniMap.get(sym)!; return (
                      <Link key={sym} href={`/stocks/${sym}`} className="rounded-[var(--radius-md)] bg-elevated p-3 hairline transition-colors hover:bg-raised">
                        <div className="flex items-center gap-2"><Avatar symbol={sym} size={26} /><span className="text-[12.5px] font-semibold text-frost">{sym}</span><span className="ml-auto"><ScoreRing value={s.aiScore} size={30} tone="ai" /></span></div>
                        <div className="mt-2 flex items-center justify-between"><span className="text-[13px] font-semibold text-frost tnum">{inr(s.price)}</span><DeltaPill pct={s.changePct} /></div>
                        <div className="mt-2"><RatingBadge rating={s.aiRating} /></div>
                      </Link>
                    ); })}
                  </div>
                )}

                {!m.streaming && m.tools && (
                  <details className="group rounded-[var(--radius-md)] bg-void/40 hairline">
                    <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-[12px] font-medium text-muted">
                      <ChevronDown size={14} className="transition-transform group-open:rotate-180" />{m.tools.length} tool call{m.tools.length === 1 ? "" : "s"} used
                    </summary>
                    <div className="flex flex-wrap gap-1.5 px-3.5 pb-3">
                      {m.tools.map((s, j) => <span key={s + j} className="rounded-md bg-elevated px-2 py-1 text-[11px] text-mist hairline"><span className="text-accent mr-1">{j + 1}</span>{s}</span>)}
                    </div>
                  </details>
                )}

                {!m.streaming && !m.error && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    {["Show me valuations", "What are the risks?", "Add to watchlist"].map((f) => (
                      <button key={f} onClick={() => send(f)} className="rounded-full bg-elevated px-3 py-1.5 text-[12px] font-medium text-mist hairline transition-colors hover:text-frost hover:bg-raised">{f}</button>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          ))}
          {thinking && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-gradient-to-br from-ai to-accent"><Sparkles size={15} className="text-white" /></span>
              <div className="flex items-center gap-1.5 pt-1.5">
                {[0, 1, 2].map((d) => (
                  <span key={d} className="h-1.5 w-1.5 rounded-full bg-ai animate-pulse" style={{ animationDelay: `${d * 150}ms` }} />
                ))}
                <span className="ml-2 text-[12px] text-muted">ARTHA is analysing…</span>
              </div>
            </motion.div>
          )}
        </div>
      )}

      {/* Composer */}
      <div className="pt-3">
        <form onSubmit={(e) => { e.preventDefault(); send(input); }}
          className="flex items-end gap-2 rounded-[var(--radius-lg)] bg-elevated p-2 hairline-strong shadow-[var(--shadow-md)] focus-within:border-accent/50">
          <textarea
            value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            rows={1} placeholder="Ask ARTHA AI anything…"
            className="max-h-32 flex-1 resize-none bg-transparent px-3 py-2 text-[14px] text-frost outline-none placeholder:text-muted"
          />
          <Button type="submit" variant="ai" size="icon" disabled={!input.trim()} aria-label="Send"><ArrowUp size={17} /></Button>
        </form>
        <p className="mt-2 text-center text-[11px] text-faint">ARTHA AI grounds answers in tool data · Research only, not investment advice.</p>
      </div>
    </div>
  );
}
