// Poll intervals for useApi, in ms — one place so every page refreshes the
// same endpoint at the same rate.
//
// Each is matched to that endpoint's server-side cache TTL in api/server.py.
// Polling faster than the TTL only re-serves the identical cached payload, so
// these are the honest ceiling: to make one genuinely fresher, lower its TTL
// on the API side too. Polling continues while the market is closed, by design.
//
// Before this, every page fetched once on mount and never again — leave a tab
// open through a session and the P&L, movers and breadth stayed frozen at load
// time while the index tape kept moving.
export const POLL = {
  dataHealth: 60_000,  // /api/data-health — @cached 30
  indices: 30_000,     // /api/indices — @cached 20, plus WS ticks on top
  universe: 60_000,    // @cached(60)
  systemStatus: 60_000, // _cached_call("system_status", …, 60)
  holdings: 120_000,   // 120
  fnoPnl: 60_000,      // /api/fno/pnl — _cached_call_arg(…, 60), evicted early on a fresh positions snapshot
  // /api/positions is _cached_call(…, 30) — the open F&O book was polled on the
  // holdings interval, so it re-served the same payload three times before the
  // cache had anything new to give. Ticks ride on top of this baseline.
  positions: 30_000,   // 30
  stock: 120_000,      // _stock is @cached(120)
  fno: 120_000,        // build_game_plan cached 120
  pulse: 180_000,      // 180
  movers: 300_000,     // 300
  brief: 300_000,      // LLM brief, server-cached 900
  curve: 300_000,      // portfolio_curve 300
  globalBoard: 300_000, // 300
  watchlists: 300_000, // no server cache; edited on another page
  flows: 600_000,      // 600
  news: 900_000,       // 900
  history: 900_000,    // 900
  fnoNarrative: 900_000, // 900 (LLM)
  events: 3_600_000,   // 3600
} as const;
