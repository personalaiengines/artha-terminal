"use client";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sparkles, ArrowUp, ChevronDown, TrendingUp, BarChart3, Wallet, Newspaper,
  Square, Copy, Check, RefreshCw, AlertTriangle, Database, Loader2, PlusCircle,
  MessageSquare, Trash2, Pencil, X, PanelLeft,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AiBadge, RatingBadge, Badge } from "@/components/ui/badge";
import { ScoreRing, DeltaPill } from "@/components/ui/stat";
import { Avatar } from "@/components/ui/primitives";
import { Markdown } from "@/components/ui/markdown";
import { Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { useChat, ChatMsg, ChatStatus, Thread } from "@/lib/use-chat";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  { icon: TrendingUp, text: "What's driving Bank Nifty today?" },
  { icon: Wallet, text: "Analyse the risk in my portfolio" },
  { icon: BarChart3, text: "Compare TCS vs INFY fundamentals" },
  { icon: Newspaper, text: "Summarise this week's market-moving news" },
];

// Follow-ups derived from what the answer was actually about. The old page
// showed the same three hardcoded chips after every message, including
// "Add to watchlist", which only ever sent that text to the LLM.
function followUps(m: ChatMsg): string[] {
  const sym = m.cards?.[0];
  switch (m.intent) {
    case "portfolio":
      return ["Which position is riskiest?", "How concentrated am I by sector?", "What should I watch tomorrow?"];
    case "compare":
      return m.cards && m.cards.length >= 2
        ? [`Which has better growth, ${m.cards[0]} or ${m.cards[1]}?`, "Compare their debt levels", "Which is cheaper on valuation?"]
        : ["Compare their valuations", "Which has less debt?"];
    case "deep":
      return sym ? [`How does ${sym} compare to peers?`, `Is ${sym} expensive right now?`, `What could go wrong with ${sym}?`] : [];
    case "market":
      return ["Which sectors led today?", "What are FIIs doing?", "Show me the top losers"];
    default:
      return sym ? [`Do a deep dive on ${sym}`, `What are the red flags on ${sym}?`, `How has ${sym} performed over 1 year?`] : [];
  }
}

const INTENT_LABEL: Record<string, string> = {
  lookup: "Quick look-up", deep: "Deep dive", compare: "Comparison",
  portfolio: "Your portfolio", market: "Market context",
};

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
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  const uniMap = useMemo(() => new Map(universe.map((s) => [s.symbol, s])), [universe]);
  const {
    threads, activeId, messages, busy, status,
    send, stop, regenerate, editMessage,
    newThread, selectThread, deleteThread, renameThread,
  } = useChat();

  const [input, setInput] = useState("");
  const [sidebar, setSidebar] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const started = useRef(false);
  const pinned = useRef(true);

  // Follow the stream only while the user is already at the bottom — yanking
  // them back down while they're reading earlier output is the classic
  // chat-UI annoyance.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinned.current) el.scrollTo({ top: el.scrollHeight });
  }, [messages, status]);

  useEffect(() => { if (initial && !started.current) { started.current = true; send(initial); } }, [initial, send]);

  const submit = (text: string) => {
    if (!text.trim() || busy) return;
    send(text);
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
  };

  const empty = messages.length === 0;

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-5">
      <ThreadSidebar
        threads={threads} activeId={activeId} open={sidebar} busy={busy}
        onClose={() => setSidebar(false)}
        onNew={() => { newThread(); setSidebar(false); }}
        onSelect={(id) => { selectThread(id); setSidebar(false); }}
        onDelete={deleteThread} onRename={renameThread}
      />

      <div className="mx-auto flex min-w-0 max-w-3xl flex-1 flex-col">
        <div className="flex items-center justify-between pb-3">
          <div className="flex items-center gap-2">
            <button onClick={() => setSidebar((v) => !v)} title="Conversations"
              className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] text-muted transition-colors hover:bg-raised hover:text-frost lg:hidden">
              <PanelLeft size={15} />
            </button>
            <AiBadge>ARTHA AI Analyst</AiBadge>
          </div>
          {!empty && (
            <button onClick={newThread} disabled={busy}
              className="flex items-center gap-1.5 rounded-full bg-elevated px-3 py-1.5 text-[12px] font-medium text-muted hairline transition-colors hover:text-frost disabled:opacity-40">
              <PlusCircle size={13} /> New chat
            </button>
          )}
        </div>

        {empty ? (
          <div className="flex flex-1 flex-col items-center justify-center text-center">
            <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="relative mb-6">
              <div className="absolute inset-0 rounded-full bg-ai/30 blur-2xl" />
              <div className="relative flex h-16 w-16 items-center justify-center rounded-[var(--radius-lg)] bg-gradient-to-br from-ai to-accent shadow-[var(--shadow-glow-ai)]">
                <Sparkles size={28} className="text-white" />
              </div>
            </motion.div>
            <h1 className="text-[24px] font-bold tracking-tight text-frost">ARTHA AI Analyst</h1>
            <p className="mt-2 max-w-md text-[14px] text-muted">
              Ask about a stock, compare companies, or dig into your own portfolio. Answers are grounded in the live ARTHA database — never estimated.
            </p>
            <div className="mt-8 grid w-full max-w-lg grid-cols-1 gap-2.5 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button key={s.text} onClick={() => submit(s.text)}
                  className="group flex items-center gap-3 rounded-[var(--radius-md)] bg-elevated p-3.5 text-left hairline transition-colors hover:bg-raised">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-void text-accent"><s.icon size={16} /></span>
                  <span className="text-[13px] font-medium text-mist group-hover:text-frost">{s.text}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div ref={scrollRef}
            onScroll={(e) => {
              const el = e.currentTarget;
              pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }}
            className="flex-1 space-y-6 overflow-y-auto scrollbar-slim pb-4">
            {messages.map((m, i) => m.role === "user" ? (
              <UserMessage key={i} m={m} busy={busy} onEdit={(t) => editMessage(i, t)} />
            ) : (
              <Answer key={i} m={m} uniMap={uniMap} busy={busy}
                onFollowUp={submit}
                onRegenerate={i === messages.length - 1 ? regenerate : undefined} />
            ))}

            {busy && status && <Working status={status} />}
          </div>
        )}

        {/* Composer */}
        <div className="pt-3">
          <form onSubmit={(e) => { e.preventDefault(); submit(input); }}
            className="flex items-end gap-2 rounded-[var(--radius-lg)] bg-elevated p-2 hairline-strong shadow-[var(--shadow-md)] focus-within:border-accent/50">
            <textarea
              ref={taRef} value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(input); } }}
              rows={1} placeholder="Ask about a stock, a comparison, or your portfolio…"
              className="max-h-40 flex-1 resize-none bg-transparent px-3 py-2 text-[14px] text-frost outline-none placeholder:text-muted"
            />
            {busy ? (
              <Button type="button" variant="ghost" size="icon" onClick={stop} aria-label="Stop generating"
                className="text-down hover:bg-down-soft"><Square size={15} fill="currentColor" /></Button>
            ) : (
              <Button type="submit" variant="ai" size="icon" disabled={!input.trim()} aria-label="Send"><ArrowUp size={17} /></Button>
            )}
          </form>
          <p className="mt-2 text-center text-[11px] text-faint">
            Grounded in the live ARTHA database · Research only, not investment advice.
          </p>
        </div>
      </div>
    </div>
  );
}

function ThreadSidebar({ threads, activeId, open, busy, onClose, onNew, onSelect, onDelete, onRename }: {
  threads: Thread[]; activeId: string | null; open: boolean; busy: boolean;
  onClose: () => void; onNew: () => void; onSelect: (id: string) => void;
  onDelete: (id: string) => void; onRename: (id: string, t: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const commit = () => {
    if (editing) onRename(editing, draft);
    setEditing(null);
  };

  const body = (
    <>
      <button onClick={onNew} disabled={busy}
        className="mb-3 flex w-full items-center gap-2 rounded-[var(--radius-md)] bg-elevated px-3 py-2.5 text-[13px] font-medium text-frost hairline transition-colors hover:bg-raised disabled:opacity-40">
        <PlusCircle size={14} className="text-ai" /> New chat
      </button>
      <div className="space-y-1 overflow-y-auto scrollbar-slim">
        {threads.length === 0 && (
          <p className="px-2 py-4 text-center text-[12px] text-faint">No saved conversations yet.</p>
        )}
        {threads.map((t) => (
          <div key={t.id}
            className={cn("group flex items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 py-2 transition-colors",
              t.id === activeId ? "bg-raised" : "hover:bg-elevated")}>
            <MessageSquare size={13} className={cn("shrink-0", t.id === activeId ? "text-ai" : "text-faint")} />
            {editing === t.id ? (
              <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
                onBlur={commit}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commit();
                  if (e.key === "Escape") setEditing(null);
                }}
                className="min-w-0 flex-1 bg-transparent text-[12.5px] text-frost outline-none" />
            ) : (
              <button onClick={() => onSelect(t.id)}
                className={cn("min-w-0 flex-1 truncate text-left text-[12.5px]",
                  t.id === activeId ? "text-frost" : "text-mist")}>
                {t.title}
              </button>
            )}
            <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
              <button onClick={() => { setEditing(t.id); setDraft(t.title); }} title="Rename"
                className="rounded p-1 text-faint hover:text-frost"><Pencil size={11} /></button>
              <button onClick={() => onDelete(t.id)} title="Delete"
                className="rounded p-1 text-faint hover:text-down"><Trash2 size={11} /></button>
            </span>
          </div>
        ))}
      </div>
    </>
  );

  return (
    <>
      {/* Persistent rail on wide screens */}
      <aside className="hidden w-60 shrink-0 flex-col lg:flex">{body}</aside>

      {/* Drawer below lg */}
      <AnimatePresence>
        {open && (
          <>
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={onClose} className="fixed inset-0 z-40 bg-void/70 lg:hidden" />
            <motion.aside initial={{ x: -280 }} animate={{ x: 0 }} exit={{ x: -280 }}
              transition={{ type: "tween", duration: 0.18 }}
              className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-base p-3 shadow-[var(--shadow-md)] hairline lg:hidden">
              <button onClick={onClose} aria-label="Close conversations"
                className="mb-2 self-end rounded p-1 text-muted hover:text-frost"><X size={15} /></button>
              {body}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}

function UserMessage({ m, busy, onEdit }: { m: ChatMsg; busy: boolean; onEdit: (t: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(m.content);

  if (editing) {
    return (
      <div className="flex justify-end">
        <div className="w-full max-w-[80%] rounded-[var(--radius-lg)] bg-elevated p-2 hairline-strong">
          <textarea autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); setEditing(false); onEdit(draft); }
              if (e.key === "Escape") { setEditing(false); setDraft(m.content); }
            }}
            rows={2}
            className="w-full resize-none bg-transparent px-2 py-1 text-[14px] text-frost outline-none" />
          <div className="flex justify-end gap-2 pt-1">
            <button onClick={() => { setEditing(false); setDraft(m.content); }}
              className="rounded-full px-3 py-1 text-[12px] text-muted hover:text-frost">Cancel</button>
            <button onClick={() => { setEditing(false); onEdit(draft); }} disabled={!draft.trim()}
              className="rounded-full bg-accent px-3 py-1 text-[12px] font-medium text-white disabled:opacity-40">
              Send
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="group flex items-start justify-end gap-1.5">
      <button onClick={() => { setDraft(m.content); setEditing(true); }} disabled={busy} title="Edit question"
        className="mt-1.5 rounded p-1 text-faint opacity-0 transition-opacity hover:text-frost group-hover:opacity-100 disabled:hidden">
        <Pencil size={12} />
      </button>
      <div className="max-w-[80%] whitespace-pre-wrap rounded-[var(--radius-lg)] rounded-br-md bg-accent px-4 py-2.5 text-[14px] text-white">{m.content}</div>
    </motion.div>
  );
}

function Working({ status }: { status: ChatStatus }) {
  const text = status.label
    ?? (status.stage === "route" ? "Working out what you're asking"
      : status.stage === "thinking" ? "Analysing"
      : "Starting");
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-gradient-to-br from-ai to-accent">
        <Sparkles size={15} className="text-white" />
      </span>
      <div className="flex items-center gap-2 pt-1.5 text-[12.5px] text-muted">
        <Loader2 size={13} className="animate-spin text-ai" />
        <AnimatePresence mode="wait">
          <motion.span key={text} initial={{ opacity: 0, y: 3 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -3 }}>
            {text}…
          </motion.span>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

function Answer({ m, uniMap, busy, onFollowUp, onRegenerate }: {
  m: ChatMsg; uniMap: Map<string, Stock>; busy: boolean;
  onFollowUp: (t: string) => void; onRegenerate?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const cards = (m.cards ?? []).filter((c) => uniMap.has(c)).slice(0, 3);
  const chips = m.streaming || m.error ? [] : followUps(m);

  const copy = () => {
    navigator.clipboard.writeText(m.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }).catch(() => {});
  };

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3">
      <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px]",
        m.error ? "bg-down-soft text-down" : "bg-gradient-to-br from-ai to-accent")}>
        {m.error ? <AlertTriangle size={15} /> : <Sparkles size={15} className="text-white" />}
      </span>

      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <AiBadge>{m.error ? "ARTHA — Unavailable" : "ARTHA AI"}</AiBadge>
          {m.intent && !m.error && <Badge tone="neutral">{INTENT_LABEL[m.intent] ?? m.intent}</Badge>}
          {m.stopped && <Badge tone="neutral">Stopped</Badge>}
        </div>

        {m.error
          ? <p className="text-[14px] leading-relaxed text-down">{m.content}</p>
          : <Markdown text={m.content} />}

        {m.streaming && (
          <span className="inline-block h-4 w-1.5 animate-pulse bg-ai align-middle" />
        )}

        {!m.streaming && cards.length > 0 && (
          <div className="grid gap-2.5 sm:grid-cols-3">
            {cards.map((sym) => {
              const s = uniMap.get(sym)!;
              return (
                <Link key={sym} href={`/stocks/${sym}`}
                  className="rounded-[var(--radius-md)] bg-elevated p-3 hairline transition-colors hover:bg-raised">
                  <div className="flex items-center gap-2">
                    <Avatar symbol={sym} size={26} />
                    <span className="truncate text-[12.5px] font-semibold text-frost">{sym}</span>
                    <span className="ml-auto"><ScoreRing value={s.aiScore} size={30} tone="ai" /></span>
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <span className="text-[13px] font-semibold text-frost tnum">{inr(s.price)}</span>
                    <DeltaPill value={s.change} pct={s.changePct} />
                  </div>
                  <div className="mt-2"><RatingBadge rating={s.aiRating} /></div>
                </Link>
              );
            })}
          </div>
        )}

        {!m.streaming && (m.sources?.length || m.steps?.length) ? (
          <details className="group rounded-[var(--radius-md)] bg-void/40 hairline">
            <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-[12px] font-medium text-muted">
              <ChevronDown size={14} className="transition-transform group-open:rotate-180" />
              <Database size={12} />
              Grounded in {m.sources?.length ? m.sources.join(", ") : "live data"}
            </summary>
            <div className="space-y-1 px-3.5 pb-3">
              {(m.steps ?? []).filter((s) => s.label).map((s, j) => (
                <div key={j} className="flex items-center gap-2 text-[11.5px] text-mist">
                  <Check size={11} className="text-up" />{s.label}
                </div>
              ))}
            </div>
          </details>
        ) : null}

        {!m.streaming && !m.error && (
          <div className="flex flex-wrap items-center gap-2 pt-0.5">
            <button onClick={copy} title="Copy answer"
              className="flex items-center gap-1.5 rounded-full bg-elevated px-2.5 py-1.5 text-[11.5px] text-muted hairline transition-colors hover:text-frost">
              {copied ? <Check size={12} className="text-up" /> : <Copy size={12} />}{copied ? "Copied" : "Copy"}
            </button>
            {onRegenerate && (
              <button onClick={onRegenerate} disabled={busy} title="Regenerate answer"
                className="flex items-center gap-1.5 rounded-full bg-elevated px-2.5 py-1.5 text-[11.5px] text-muted hairline transition-colors hover:text-frost disabled:opacity-40">
                <RefreshCw size={12} /> Retry
              </button>
            )}
          </div>
        )}

        {chips.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-0.5">
            {chips.map((f) => (
              <button key={f} onClick={() => onFollowUp(f)} disabled={busy}
                className="rounded-full bg-elevated px-3 py-1.5 text-[12px] font-medium text-mist hairline transition-colors hover:bg-raised hover:text-frost disabled:opacity-40">
                {f}
              </button>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
