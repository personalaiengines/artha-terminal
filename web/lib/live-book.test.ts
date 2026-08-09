import { describe, it, expect } from "vitest";
import { applyLiveTicks } from "./live-book";
import type { Position, PositionBook } from "@/components/widgets/positions-panel";
import type { LiveTick } from "./use-live-prices";

const tick = (price: number): LiveTick => ({ price, changePct: null, at: 0 });

const pos = (over: Partial<Position> = {}): Position => ({
  symbol: "NIFTY2681124600PE", key: "NSE_FO|41016", multiplier: 1,
  qty: 75, side: "LONG", avg: 100, ltp: 110, pnl: 750,
  realized: 0, unrealized: 750, product: "D", exchange: "NFO", ...over,
});

const bookOf = (items: Position[], over: Partial<PositionBook> = {}): PositionBook => ({
  ok: true, status: "ok", items, closed: 0, closedItems: [],
  realized: 0,
  unrealized: items.reduce((a, p) => a + (p.unrealized ?? 0), 0),
  net: items.reduce((a, p) => a + p.pnl, 0),
  ...over,
});

describe("applyLiveTicks", () => {
  it("moves LTP and P&L together by qty x the price difference", () => {
    const out = applyLiveTicks(bookOf([pos()]), { "NSE_FO|41016": tick(112) })!;
    expect(out.items[0].ltp).toBe(112);
    // +2 on 75 units = +150 on top of the snapshot's 750.
    expect(out.items[0].pnl).toBe(900);
    expect(out.items[0].unrealized).toBe(900);
    expect(out.items[0].isLive).toBe(true);
  });

  it("takes a short's P&L DOWN as its premium rises", () => {
    // qty is signed — this is the whole reason the delta is not abs().
    const out = applyLiveTicks(bookOf([pos({ qty: -75, side: "SHORT", pnl: -750, unrealized: -750 })]),
      { "NSE_FO|41016": tick(112) })!;
    expect(out.items[0].pnl).toBe(-900);
  });

  it("preserves realised profit already booked into pnl", () => {
    // A partly squared-off contract: 500 of the 750 is realised and can no
    // longer move. Recomputing pnl as (ltp - avg) x qty would return
    // (112-100)x75 = 900 and silently delete that 500.
    const out = applyLiveTicks(
      bookOf([pos({ pnl: 1250, realized: 500, unrealized: 750 })]),
      { "NSE_FO|41016": tick(112) })!;
    expect(out.items[0].pnl).toBe(1400);
    expect(out.items[0].unrealized).toBe(900);
    expect(out.items[0].realized).toBe(500);
  });

  it("multiplies by the contract multiplier when the broker sends one", () => {
    const out = applyLiveTicks(bookOf([pos({ multiplier: 2 })]), { "NSE_FO|41016": tick(112) })!;
    expect(out.items[0].pnl).toBe(750 + 2 * 75 * 2);
  });

  it("rolls the book totals but never touches realised", () => {
    const b = bookOf([pos(), pos({ symbol: "X", key: "NSE_FO|99", qty: -50, pnl: -200, unrealized: -200 })],
      { realized: 4000, unrealized: 550, net: 4550 });
    const out = applyLiveTicks(b, { "NSE_FO|41016": tick(112), "NSE_FO|99": tick(112) })!;
    // +150 on the long, -100 on the short.
    expect(out.unrealized).toBe(600);
    expect(out.net).toBe(4600);
    expect(out.realized).toBe(4000);
  });

  it("returns the same object when no tick applies, so renders can skip", () => {
    const b = bookOf([pos()]);
    expect(applyLiveTicks(b, {})).toBe(b);
    // A row with no instrument key can never be matched.
    const noKey = bookOf([pos({ key: null })]);
    expect(applyLiveTicks(noKey, { "NSE_FO|41016": tick(112) })).toBe(noKey);
  });

  it("leaves a row alone rather than producing NaN from junk", () => {
    const b = bookOf([pos({ ltp: NaN })]);
    expect(applyLiveTicks(b, { "NSE_FO|41016": tick(112) })).toBe(b);
    const b2 = bookOf([pos()]);
    expect(applyLiveTicks(b2, { "NSE_FO|41016": tick(NaN) })).toBe(b2);
  });

  it("passes an errored or empty book straight through", () => {
    const bad: PositionBook = { ok: false, status: "expired", items: [] };
    expect(applyLiveTicks(bad, { "NSE_FO|41016": tick(112) })).toBe(bad);
    expect(applyLiveTicks(null, {})).toBe(null);
  });

  it("keeps null totals null instead of turning them into numbers", () => {
    const b = bookOf([pos()], { unrealized: null, net: null });
    const out = applyLiveTicks(b, { "NSE_FO|41016": tick(112) })!;
    expect(out.unrealized).toBe(null);
    expect(out.net).toBe(null);
  });
});
