// Overlaying live ticks onto the REST F&O position book.
//
// Pure and separate from the component (components/widgets/positions-panel.tsx)
// for one reason: it moves P&L figures, and the arithmetic that does that should
// be readable and testable without standing up React.
//
// /api/positions is server-cached for 30s on top of a 30s client poll, so the
// book's LTP and P&L sat visibly frozen while the index tape directly above them
// ticked. The tick stream fixes the LTP; the P&L has to follow it, or the two
// columns disagree on screen.

import type { LiveTick } from "./use-live-prices";
import type { Position, PositionBook } from "@/components/widgets/positions-panel";

/** Adjust a book's open rows to the latest ticks. Returns the SAME object when
 *  nothing changed, so callers can use identity to skip re-renders.
 *
 *  Ticks are keyed by the Upstox instrument key, upper-cased — which is how
 *  `useLivePrices` keys everything it returns.
 */
export function applyLiveTicks(
  book: PositionBook | null,
  live: Record<string, LiveTick>
): PositionBook | null {
  if (!book?.ok || !book.items.length) return book;

  let delta = 0;
  const items: Position[] = book.items.map((p) => {
    const t = p.key ? live[p.key.toUpperCase()] : undefined;
    if (!t || !Number.isFinite(t.price) || !Number.isFinite(p.ltp) || !Number.isFinite(p.pnl)) {
      return p;
    }
    // P&L moves by the DIFFERENCE from this snapshot's own LTP — it is not
    // recomputed as (ltp − avg) × qty. Upstox books a partly squared-off
    // contract's realised profit into `pnl` too, and recomputing would silently
    // delete it. Realised cannot change between polls, so the difference is
    // exact for both legs. `qty` is signed, so a short's P&L correctly falls as
    // its premium rises.
    const d = (t.price - p.ltp) * p.qty * (p.multiplier ?? 1);
    if (!Number.isFinite(d)) return p;
    delta += d;
    return {
      ...p,
      ltp: t.price,
      pnl: p.pnl + d,
      unrealized: p.unrealized == null ? p.unrealized : p.unrealized + d,
      isLive: true,
    };
  });

  if (items.every((p, i) => p === book.items[i])) return book;

  return {
    ...book,
    items,
    // Realised is untouched by a mark-to-market move, by definition. Only the
    // unrealised leg and the net move.
    unrealized: book.unrealized == null ? book.unrealized : book.unrealized + delta,
    net: book.net == null ? book.net : book.net + delta,
  };
}
