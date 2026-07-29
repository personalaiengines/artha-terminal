"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Search, CornerDownLeft, Sparkles } from "lucide-react";
import { useUI } from "./ui-store";
import { NAV } from "@/lib/nav";
import { Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { changeText, trendClass } from "@/lib/format";
import { Avatar } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export function CommandPalette() {
  const { cmdkOpen, setCmdk, changeMode } = useUI();
  const router = useRouter();
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmdk(true); }
      if (e.key === "Escape") setCmdk(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setCmdk]);

  useEffect(() => { if (!cmdkOpen) { setQ(""); setSel(0); } }, [cmdkOpen]);

  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    const stocks = universe.filter((x) => !s || x.symbol.toLowerCase().includes(s) || x.name.toLowerCase().includes(s))
      .slice(0, 6).map((x) => ({ type: "stock" as const, x }));
    const pages = NAV.filter((n) => !s || n.label.toLowerCase().includes(s))
      .slice(0, 5).map((n) => ({ type: "page" as const, n }));
    const ai = s ? [{ type: "ai" as const, q: s }] : [];
    return [...ai, ...stocks, ...pages];
  }, [q, universe]);

  const go = (i: number) => {
    const r = results[i];
    if (!r) return;
    if (r.type === "stock") router.push(`/stocks/${r.x.symbol}`);
    else if (r.type === "page") router.push(r.n.href);
    else router.push(`/ai-analyst?q=${encodeURIComponent(r.q)}`);
    setCmdk(false);
  };

  return (
    <AnimatePresence>
      {cmdkOpen && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-start justify-center p-4 pt-[12vh]"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-abyss/70 backdrop-blur-sm" onClick={() => setCmdk(false)} />
          <motion.div
            initial={{ opacity: 0, scale: 0.98, y: -8 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.98, y: -8 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="relative w-full max-w-xl overflow-hidden rounded-[var(--radius-lg)] glass hairline-strong shadow-[var(--shadow-lg)]"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(results.length - 1, s + 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(0, s - 1)); }
              if (e.key === "Enter") { e.preventDefault(); go(sel); }
            }}
          >
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search size={17} className="text-muted" />
              <input
                autoFocus value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }}
                placeholder="Search symbols, pages, or ask AI…"
                className="h-13 w-full bg-transparent py-4 text-[14px] text-frost outline-none placeholder:text-muted"
              />
            </div>
            <div className="max-h-80 overflow-y-auto scrollbar-slim p-2">
              {results.map((r, i) => (
                <button
                  key={i}
                  onMouseEnter={() => setSel(i)}
                  onClick={() => go(i)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-[var(--radius-sm)] px-3 py-2.5 text-left transition-colors",
                    sel === i ? "bg-raised" : "hover:bg-raised/50"
                  )}
                >
                  {r.type === "ai" && (
                    <><span className="flex h-8 w-8 items-center justify-center rounded-[8px] bg-ai-soft text-ai"><Sparkles size={16} /></span>
                      <div><div className="text-[13px] font-medium text-frost">Ask AI Analyst</div><div className="text-[11px] text-muted">“{r.q}”</div></div></>
                  )}
                  {r.type === "stock" && (
                    <><Avatar symbol={r.x.symbol} size={32} />
                      <div className="min-w-0"><div className="text-[13px] font-medium text-frost">{r.x.symbol}</div><div className="text-[11px] text-muted truncate">{r.x.name}</div></div>
                      <span className={cn("ml-auto text-[12px] font-medium tnum", trendClass(r.x.changePct))}>{changeText(r.x.changePct, r.x.change, changeMode)}</span></>
                  )}
                  {r.type === "page" && (
                    <><span className="flex h-8 w-8 items-center justify-center rounded-[8px] bg-elevated text-muted hairline"><r.n.icon size={16} /></span>
                      <div className="text-[13px] font-medium text-frost">{r.n.label}</div>
                      <span className="ml-auto text-[10px] uppercase tracking-wide text-faint">Page</span></>
                  )}
                  {sel === i && <CornerDownLeft size={14} className="text-muted ml-1" />}
                </button>
              ))}
              {results.length === 0 && <div className="py-10 text-center text-[13px] text-muted">No results for “{q}”</div>}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
