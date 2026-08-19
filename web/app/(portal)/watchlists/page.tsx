"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Plus, Pin, Search, Trash2, X, ListChecks } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Segmented, Avatar, EmptyState } from "@/components/ui/primitives";
import { DataGrid, Column } from "@/components/ui/data-grid";
import { RatingBadge, Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { Stock, blankStock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { useLivePrices, withLivePrices } from "@/lib/use-live-prices";
import { POLL } from "@/lib/poll";
import { useSparklines } from "@/lib/use-sparklines";
import { useEnsureFresh } from "@/lib/use-fresh";
import { inr, compactCr, num, mcap, changeText, trendClass } from "@/lib/format";
import { useUI } from "@/components/layout/ui-store";
import { cn } from "@/lib/utils";

type WList = { id: number; name: string; symbols: string[] };

export default function Watchlists() {
  const { changeMode } = useUI();
  const router = useRouter();
  const universeRaw = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  const live = useLivePrices(universeRaw.slice(0, 120).map((s) => s.symbol));
  const universe = withLivePrices(universeRaw, live);
  const [lists, setLists] = useState<WList[]>([]);
  const [activeName, setActiveName] = useState<string | null>(null);
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [addQuery, setAddQuery] = useState("");
  const [showSuggest, setShowSuggest] = useState(false);

  const load = async () => {
    try {
      const j = await fetch("/api/watchlists").then((r) => r.json());
      if (j?.ok) {
        setLists(j.items);
        setActiveName((cur) => (cur && j.items.some((l: WList) => l.name === cur) ? cur : j.items[0]?.name ?? null));
      }
    } catch {}
  };
  useEffect(() => { load(); }, []);

  const active = lists.find((l) => l.name === activeName) ?? null;

  const createList = async () => {
    const name = newName.trim();
    if (!name) return;
    setNewName("");
    const res = await fetch("/api/watchlists", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
    }).then((r) => r.json()).catch(() => null);
    if (res?.ok) { setCreating(false); await load(); setActiveName(name); }
  };

  // Matches on symbol OR company name — typing "Reliance Industries" or
  // "RELIANCE" both find the same stock, so the add action always resolves
  // to the real trading symbol rather than requiring the exact instrument code.
  const suggestions = addQuery.trim()
    ? universe.filter((s) =>
        s.symbol.toLowerCase().includes(addQuery.toLowerCase()) ||
        s.name.toLowerCase().includes(addQuery.toLowerCase())
      ).slice(0, 8)
    : [];

  const addSymbol = async (sym: string) => {
    sym = sym.trim().toUpperCase();
    if (!sym || !active) return;
    setAddQuery(""); setShowSuggest(false);
    setLists((ls) => ls.map((l) => (l.id === active.id && !l.symbols.includes(sym) ? { ...l, symbols: [...l.symbols, sym] } : l)));
    try {
      await fetch(`/api/watchlists/${active.id}/items`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: sym }),
      });
    } catch {}
  };

  const submitAdd = () => {
    const exact = universe.find((s) => s.symbol.toLowerCase() === addQuery.trim().toLowerCase());
    const pick = exact ?? suggestions[0];
    if (pick) addSymbol(pick.symbol);
    else if (addQuery.trim()) addSymbol(addQuery); // no universe match — add the typed code as-is
  };

  const removeSymbol = async (sym: string) => {
    if (!active) return;
    setLists((ls) => ls.map((l) => (l.id === active.id ? { ...l, symbols: l.symbols.filter((s) => s !== sym) } : l)));
    try { await fetch(`/api/watchlists/${active.id}/items/${sym}`, { method: "DELETE" }); } catch {}
  };

  const deleteList = async (id: number) => {
    setLists((ls) => ls.filter((l) => l.id !== id));
    if (active?.id === id) setActiveName(null);
    try { await fetch(`/api/watchlists/${id}`, { method: "DELETE" }); } catch {}
  };

  const togglePin = (sym: string) => setPinned((p) => { const n = new Set(p); n.has(sym) ? n.delete(sym) : n.add(sym); return n; });

  const rows = (active?.symbols ?? [])
    .map((sym) => universe.find((s) => s.symbol === sym) ?? blankStock({ symbol: sym }))
    .filter((s) => !q || `${s.symbol} ${s.name}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (pinned.has(b.symbol) ? 1 : 0) - (pinned.has(a.symbol) ? 1 : 0));

  const spark = useSparklines(rows.map((s) => s.symbol));
  useEnsureFresh(rows.map((s) => s.symbol));

  const columns: Column<Stock>[] = [
    { key: "pin", header: "", width: "36px", cell: (s) => <button onClick={(e) => { e.stopPropagation(); togglePin(s.symbol); }} className={cn("transition-colors", pinned.has(s.symbol) ? "text-warn" : "text-faint hover:text-muted")}><Pin size={14} fill={pinned.has(s.symbol) ? "currentColor" : "none"} /></button> },
    { key: "symbol", header: "Symbol", width: "200px", sortable: true, sortValue: (s) => s.symbol, cell: (s) => <span className="flex items-center gap-2.5"><Avatar symbol={s.symbol} size={28} /><span><span className="block font-semibold text-frost leading-tight">{s.symbol}</span><span className="block text-[11px] text-muted truncate max-w-[130px]">{s.name}</span></span></span> },
    { key: "sector", header: "Sector", cell: (s) => <Badge tone="neutral">{s.sector}</Badge> },
    { key: "price", header: "LTP", align: "right", sortable: true, sortValue: (s) => s.price, cell: (s) => <span className="tnum font-medium">{inr(s.price)}</span> },
    { key: "chg", header: "Chg%", align: "right", sortable: true, sortValue: (s) => s.changePct, cell: (s) => <span className={cn("tnum font-semibold", trendClass(s.changePct))}>{changeText(s.changePct, s.change, changeMode)}</span> },
    { key: "spark", header: "Trend", align: "right", cell: (s) => {
        const d = spark[s.symbol];
        return d && d.length > 1
          ? <span className="inline-block"><Sparkline data={d} positive={d[d.length - 1] >= d[0]} width={84} height={24} /></span>
          : <span className="text-faint">—</span>;
      } },
    { key: "vol", header: "Volume", align: "right", sortable: true, sortValue: (s) => s.volume, cell: (s) => { const spike = (s.volume ?? 0) > 4e6; return <span className={cn("tnum", spike ? "text-warn font-semibold" : "text-mist")}>{compactCr(s.volume)}{spike && " ⚡"}</span>; } },
    { key: "mcap", header: "Mkt Cap", align: "right", sortable: true, sortValue: (s) => s.mcapCr, cell: (s) => <span className="tnum text-mist">{mcap(s.mcapCr)}</span> },
    { key: "ai", header: "AI", align: "right", sortable: true, sortValue: (s) => s.aiScore, cell: (s) => <span className="tnum font-bold text-ai">{num(s.aiScore, { decimals: 1 })}</span> },
    { key: "rating", header: "Rating", align: "right", cell: (s) => <RatingBadge rating={s.aiRating} /> },
    { key: "del", header: "", width: "36px", cell: (s) => <button onClick={(e) => { e.stopPropagation(); removeSymbol(s.symbol); }} className="text-faint transition-colors hover:text-down" aria-label="Remove from list"><Trash2 size={14} /></button> },
  ];

  return (
    <div>
      <PageHeader eyebrow="Workspace" title="Watchlists"
        description="Your saved symbol lists — create lists, add symbols, track live."
        actions={<Button variant="secondary" size="sm" onClick={() => setCreating((v) => !v)}><Plus size={14} />New List</Button>} />

      {creating && (
        <Card variant="elevated" className="mb-4">
          <CardBody className="pt-4">
            <div className="flex items-center gap-3">
              <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && createList()}
                placeholder="List name…" className="h-10 flex-1 rounded-[var(--radius-sm)] bg-void px-3 text-[13px] text-frost hairline outline-none focus:border-accent/50" />
              <Button variant="primary" size="md" onClick={createList} disabled={!newName.trim()}>Create</Button>
              <button onClick={() => setCreating(false)} className="text-muted hover:text-frost" aria-label="Close"><X size={16} /></button>
            </div>
          </CardBody>
        </Card>
      )}

      {lists.length === 0 ? (
        <Card><CardBody>
          <EmptyState icon={<ListChecks size={22} />} title="No watchlists yet"
            description="Create your first list to start tracking symbols."
            action={<Button variant="primary" size="sm" onClick={() => setCreating(true)}><Plus size={14} />New List</Button>} />
        </CardBody></Card>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <Segmented value={activeName ?? ""} onChange={setActiveName} options={lists.map((l) => ({ label: l.name, value: l.name }))} />
            {active && <button onClick={() => deleteList(active.id)} className="text-faint hover:text-down" title="Delete this list" aria-label="Delete list"><Trash2 size={14} /></button>}
            <div className="flex h-9 items-center gap-2 rounded-[var(--radius-sm)] bg-elevated px-3 hairline sm:ml-auto w-full sm:w-60">
              <Search size={15} className="text-muted" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" className="w-full bg-transparent text-[13px] text-frost outline-none placeholder:text-muted" />
            </div>
          </div>

          <div className="mb-4 flex items-center gap-2">
            <div className="relative">
              <input value={addQuery} onChange={(e) => { setAddQuery(e.target.value); setShowSuggest(true); }}
                onFocus={() => setShowSuggest(true)}
                onBlur={() => setTimeout(() => setShowSuggest(false), 150)}
                onKeyDown={(e) => e.key === "Enter" && submitAdd()}
                placeholder="Add by symbol or company name…"
                className="h-9 w-72 rounded-[var(--radius-sm)] bg-elevated px-3 text-[13px] text-frost hairline outline-none placeholder:text-muted" />
              {showSuggest && suggestions.length > 0 && (
                <div className="absolute z-10 mt-1 max-h-64 w-72 overflow-y-auto rounded-[var(--radius-sm)] bg-elevated hairline shadow-lg">
                  {suggestions.map((s) => (
                    <button key={s.symbol} type="button" onMouseDown={() => addSymbol(s.symbol)}
                      className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-raised">
                      <Avatar symbol={s.symbol} size={22} />
                      <span className="min-w-0">
                        <span className="block text-[12.5px] font-semibold text-frost">{s.symbol}</span>
                        <span className="block text-[11px] text-muted truncate">{s.name}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <Button variant="secondary" size="sm" onClick={submitAdd} disabled={!addQuery.trim()}><Plus size={14} />Add</Button>
          </div>

          {rows.length === 0 ? (
            <Card><CardBody>
              <EmptyState icon={<Search size={22} />} title="No symbols in this list" description="Add a symbol above to start tracking it." />
            </CardBody></Card>
          ) : (
            <DataGrid columns={columns} rows={rows} rowKey={(s) => s.symbol} onRowClick={(s) => router.push(`/stocks/${s.symbol}`)} pinnedFirstCol={false} />
          )}
        </>
      )}
    </div>
  );
}
