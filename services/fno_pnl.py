"""
ARTHA Terminal - F&O P&L tracker (daily record + per-contract breakdown)

Why a table: Upstox's short-term-positions API is intraday-only. It reports
today's realised and unrealised P&L and forgets it at the next reset, so a
tracker that spans sessions has to keep its own record. `snapshot()` upserts the
current day on every positions read — the last write of a day is that day's
close — and `history()` reads the record back with the running curve.

Two grains are kept: the day (fno_pnl_daily, drives the curve and the stats) and
the day-by-contract (fno_pnl_contract_daily, drives attribution and every filter
the UI offers). The second is what makes "NIFTY only", "puts only" or "losers
only" answerable over a window rather than only for whatever is open right now.

Read-only with respect to the broker: this records what the book already did.
Nothing here places, modifies or cancels an order.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from db import get_connection

logger = logging.getLogger("services.fno_pnl")

IST = ZoneInfo("Asia/Kolkata")

def parse_contract(symbol: str) -> tuple[str, str | None]:
    """NIFTY26AUG24400CE -> ("NIFTY", "CE"). Used by the API so the UI filters
    on parsed fields instead of re-deriving them from the string.

    The right is stripped before the underlying is read, or the leading-letters
    match on an all-alphabetic symbol would swallow it. A future has no right
    and still resolves to its underlying rather than dropping out of the
    filters.
    """
    s = (symbol or "").strip().upper()
    right = s[-2:] if s.endswith(("CE", "PE")) else None
    body = s[:-2] if right else s
    m = re.match(r"[A-Z]+", body)
    return (m.group(0) if m else body), right


# NSE/BSE trading calendar. Same library services.global_markets already uses,
# so holidays are real holidays rather than a weekday guess.
_CAL_CODE = "XBOM"
_OPEN = time(9, 15)


def session_date(now: datetime | None = None) -> str:
    """The trading session the *current* book belongs to.

    Not the wall date. Upstox's intraday book still holds the last session's
    positions after midnight, so recording against the calendar date wrote the
    same numbers a second time under the new day and the curve counted a
    session that never traded. The book belongs to the most recent session that
    has actually opened: before 09:15 IST, on a weekend, or on a holiday, that
    is the previous trading day, and the write updates that row instead of
    inventing one.

    Falls back to a weekday rule if the calendar library is unavailable — a
    wrong holiday is survivable, a phantom session is not.
    """
    now = now or datetime.now(IST)
    today = now.date()
    try:
        import exchange_calendars as xc
        cal = xc.get_calendar(_CAL_CODE)
        session = cal.date_to_session(today, direction="previous").date()
        if session == today and now.time() < _OPEN:
            session = cal.previous_session(cal.date_to_session(today, direction="previous")).date()
        return session.isoformat()
    except Exception:
        d = today
        if d.weekday() < 5 and now.time() >= _OPEN:
            return d.isoformat()
        while True:
            d -= timedelta(days=1)
            if d.weekday() < 5:
                return d.isoformat()


def snapshot(positions: list[dict]) -> dict:
    """Record today's F&O P&L, in total and per contract. Idempotent — a later
    read the same day overwrites it. Returns the totals it wrote.

    Never raises: this rides along on the live positions read, and a tracker
    write failing must not take the user's book down with it.
    """
    realized = round(sum(p.get("realized") or 0.0 for p in positions), 2)
    unrealized = round(sum(p.get("unrealized") or 0.0 for p in positions), 2)
    totals = {"realized": realized, "unrealized": unrealized,
              "net": round(realized + unrealized, 2)}
    try:
        now, day = datetime.now(IST).isoformat(), session_date()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO fno_pnl_daily
                    (date, realized, unrealized, net, open_count, closed_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    realized=excluded.realized, unrealized=excluded.unrealized,
                    net=excluded.net, open_count=excluded.open_count,
                    closed_count=excluded.closed_count, updated_at=excluded.updated_at
                """,
                (day, realized, unrealized, totals["net"],
                 sum(1 for p in positions if p.get("qty")),
                 sum(1 for p in positions if not p.get("qty")), now),
            )
            conn.executemany(
                """
                INSERT INTO fno_pnl_contract_daily
                    (date, symbol, realized, unrealized, net, qty, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    realized=excluded.realized, unrealized=excluded.unrealized,
                    net=excluded.net, qty=excluded.qty, updated_at=excluded.updated_at
                """,
                [(day, p["symbol"], p.get("realized") or 0.0, p.get("unrealized") or 0.0,
                  (p.get("realized") or 0.0) + (p.get("unrealized") or 0.0),
                  p.get("qty") or 0, now)
                 for p in positions if p.get("symbol")],
            )
    except Exception as e:
        logger.warning(f"F&O P&L snapshot failed: {e}")
    return totals


def contract_key(t: dict) -> str:
    """A stable name for the contract a historical trade refers to.

    Trade history gives the parts (scrip, expiry, strike, right) but not the
    exchange trading symbol, and reconstructing Upstox's weekly/monthly symbol
    encoding from them is a guess that breaks on the months it abbreviates
    differently. A readable key is honest and still parses into underlying and
    right for the filters — see parse_contract.
    """
    scrip = (t.get("scrip_name") or t.get("symbol") or "?").strip().upper()
    right = (t.get("option_type") or "").strip().upper()
    expiry = (t.get("expiry") or "").strip()
    try:
        expiry = datetime.fromisoformat(expiry).strftime("%d%b%y").upper()
    except Exception:
        pass
    strike = (t.get("strike_price") or "").strip()
    try:
        strike = f"{float(strike):g}"
    except Exception:
        pass
    parts = [scrip, expiry, strike, right if right in ("CE", "PE") else "FUT"]
    return " ".join(p for p in parts if p)


def _fifo_realized(trades: list[dict]) -> dict[tuple[str, str], float]:
    """Realised P&L per (session date, contract), matched FIFO.

    Trade history is a list of fills, not a P&L statement — the P&L only exists
    once a buy is matched against a sell. Matching has to run across days, or a
    position carried overnight books its entire profit on the day it was
    *closed* with no cost basis, or is dropped entirely.

    A long lot closed at q having opened at p books (q − p) × qty; a short lot
    is the mirror. Whatever is left open at the end simply carries — its P&L is
    still unrealised and is not attributed to any day here.
    """
    from collections import defaultdict, deque

    by_contract: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_contract[contract_key(t)].append(t)

    out: dict[tuple[str, str], float] = defaultdict(float)
    for key, rows in by_contract.items():
        # exchange order within a day is not in the payload; trade_id is
        # monotonic per account, so it is the best available tiebreak.
        rows.sort(key=lambda r: (r.get("trade_date") or "", str(r.get("trade_id") or "")))
        lots: deque[list] = deque()  # [signed_qty, price] — sign is the direction
        for r in rows:
            qty = abs(float(r.get("quantity") or 0))
            price = float(r.get("price") or 0)
            if not qty:
                continue
            side = 1 if (r.get("transaction_type") or "").upper() == "BUY" else -1
            date = r.get("trade_date") or ""
            while qty and lots and (lots[0][0] > 0) != (side > 0):
                lot = lots[0]
                take = min(qty, abs(lot[0]))
                # closing a long: (exit − entry); closing a short: (entry − exit)
                out[(date, key)] += (price - lot[1]) * take * (1 if lot[0] > 0 else -1)
                lot[0] -= take * (1 if lot[0] > 0 else -1)
                qty -= take
                if not lot[0]:
                    lots.popleft()
            if qty:
                lots.append([qty * side, price])
    return {k: round(v, 2) for k, v in out.items() if round(v, 2)}


def _fy_chunks(start: date, end: date) -> list[tuple[str, str]]:
    """Split a range on Indian financial years (1 Apr – 31 Mar). Upstox rejects
    any query that crosses one with UDAPI1093."""
    out = []
    cur = start
    while cur <= end:
        fy_start = date(cur.year if cur.month >= 4 else cur.year - 1, 4, 1)
        fy_end = date(fy_start.year + 1, 3, 31)
        out.append((max(cur, fy_start).isoformat(), min(end, fy_end).isoformat()))
        cur = fy_end + timedelta(days=1)
    return out


def backfill(years: int = 3) -> dict:
    """Rebuild the daily record from the broker's own trade history.

    The positions API only ever knows today, so without this the tracker starts
    empty and every window shows the same single session. Trade history goes
    back further (Upstox serves the current and previous financial years), and
    FIFO matching turns those fills into realised P&L per session per contract.

    Two things it deliberately does not do:
      * it never touches the current session — the live book owns that row, and
        it is the only one that can also report unrealised P&L;
      * it does not invent an unrealised figure for a past day. Marking a
        carried position to a historical close would need EOD prices per
        contract that nothing here has, so backfilled sessions are booked-only
        and are marked source='trades' so the UI can say so.
    """
    import asyncio
    from services.upstox import UpstoxClient

    today = datetime.now(IST).date()
    start = date(today.year - years, today.month, 1)
    current = session_date()

    trades: list[dict] = []
    errors: list[str] = []
    client = UpstoxClient()
    for s, e in _fy_chunks(start, today):
        res = asyncio.run(client.get_historical_trades(s, e))
        if res.get("status") == "ok":
            trades.extend(res.get("data") or [])
        elif res.get("status") == "expired":
            return {"ok": False, "status": "expired",
                    "message": "Access token expired — reconnect Upstox to backfill."}
        else:
            errors.append(f"{s}..{e}: {res.get('message')}")

    if not trades:
        return {"ok": False, "status": "empty", "sessions": 0, "trades": 0,
                "message": "Upstox returned no F&O trades for this period.",
                "errors": errors}

    realized = _fifo_realized(trades)
    per_day: dict[str, float] = {}
    for (day, _), v in realized.items():
        per_day[day] = round(per_day.get(day, 0.0) + v, 2)

    now = datetime.now(IST).isoformat()
    written = 0
    try:
        with get_connection() as conn:
            for day, total in sorted(per_day.items()):
                if day >= current:
                    continue  # the live book owns the open session
                conn.execute(
                    """
                    INSERT INTO fno_pnl_daily
                        (date, realized, unrealized, net, open_count, closed_count, updated_at, source)
                    VALUES (?, ?, 0, ?, 0, ?, ?, 'trades')
                    ON CONFLICT(date) DO UPDATE SET
                        realized=excluded.realized, net=excluded.net,
                        closed_count=excluded.closed_count, updated_at=excluded.updated_at,
                        source='trades'
                    WHERE fno_pnl_daily.source != 'live'
                    """,
                    (day, total, total,
                     sum(1 for (d, _) in realized if d == day), now),
                )
                written += 1
            conn.executemany(
                """
                INSERT INTO fno_pnl_contract_daily
                    (date, symbol, realized, unrealized, net, qty, updated_at)
                VALUES (?, ?, ?, 0, ?, 0, ?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    realized=excluded.realized, net=excluded.net, updated_at=excluded.updated_at
                """,
                [(day, key, v, v, now) for (day, key), v in realized.items() if day < current],
            )
    except Exception as e:
        logger.warning(f"F&O P&L backfill write failed: {e}")
        return {"ok": False, "status": "error", "message": str(e)}

    days_seen = sorted(per_day)
    return {"ok": True, "status": "ok", "trades": len(trades), "sessions": written,
            "contracts": len({k for _, k in realized}),
            "from": days_seen[0] if days_seen else None,
            "to": days_seen[-1] if days_seen else None,
            "errors": errors}


def history(start: str | None = None, end: str | None = None) -> dict:
    """Recorded sessions between `start` and `end` (inclusive, ISO dates),
    oldest first, with the running curve, the per-contract breakdown over the
    same slice, and summary stats.

    A date range rather than a session count: the UI filters by year and month,
    and asking for "the last N sessions" cannot answer "March 2026". `months`
    lists every year-month the record holds, which is what the filter is built
    from — an empty month is never offered.

    Days the terminal never ran are simply absent; they are not zero-filled,
    because "we did not look" is not "flat" (R17).
    """
    lo, hi = start or "0000-01-01", end or "9999-12-31"
    try:
        with get_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                """SELECT date, realized, unrealized, net, open_count, closed_count,
                          COALESCE(source, 'live') AS source
                   FROM fno_pnl_daily WHERE date BETWEEN ? AND ?
                   ORDER BY date""", (lo, hi)
            )]
            contracts = _contracts(conn, lo, hi)
            months = [r[0] for r in conn.execute(
                "SELECT DISTINCT substr(date, 1, 7) FROM fno_pnl_daily ORDER BY 1")]
    except Exception as e:
        logger.warning(f"F&O P&L history read failed: {e}")
        return {"days": [], "contracts": [], "months": [], "stats": _stats([])}

    run = 0.0
    for r in rows:
        run += r["net"] or 0.0
        r["cumulative"] = round(run, 2)
    return {"days": rows, "contracts": contracts, "months": months, "stats": _stats(rows)}


def _contracts(conn, lo: str, hi: str) -> list[dict]:
    """Per-contract totals over the window, biggest absolute mover first, each
    tagged with its underlying and right so the UI can filter without parsing
    symbols in the browser."""
    out = []
    for r in conn.execute(
        """SELECT symbol, SUM(realized) AS realized, SUM(unrealized) AS unrealized,
                  SUM(net) AS net, COUNT(*) AS sessions
           FROM fno_pnl_contract_daily WHERE date BETWEEN ? AND ?
           GROUP BY symbol ORDER BY ABS(SUM(net)) DESC LIMIT 60""", (lo, hi)
    ):
        underlying, right = parse_contract(r["symbol"])
        out.append({"symbol": r["symbol"], "underlying": underlying, "right": right,
                    "realized": round(r["realized"] or 0.0, 2),
                    "unrealized": round(r["unrealized"] or 0.0, 2),
                    "net": round(r["net"] or 0.0, 2), "sessions": r["sessions"]})
    return out


def _stats(rows: list[dict]) -> dict:
    """Window summary. `win_rate` counts green *days*, not trades — the broker
    gives no per-trade record here, and calling day-level accuracy a trade hit
    rate would be a different (and wrong) number."""
    nets = [r["net"] or 0.0 for r in rows]
    green = [n for n in nets if n > 0]
    red = [n for n in nets if n < 0]
    decided = len(green) + len(red)  # flat days settle nothing either way
    return {
        "sessions": len(rows),
        "total": round(sum(nets), 2),
        "realized": round(sum(r["realized"] or 0.0 for r in rows), 2),
        "unrealized": round(sum(r["unrealized"] or 0.0 for r in rows), 2),
        "best": round(max(nets), 2) if nets else None,
        "worst": round(min(nets), 2) if nets else None,
        "green_days": len(green),
        "red_days": len(red),
        "win_rate": round(100 * len(green) / decided, 1) if decided else None,
        "avg_green": round(sum(green) / len(green), 2) if green else None,
        "avg_red": round(sum(red) / len(red), 2) if red else None,
        # Largest peak-to-trough fall of the cumulative curve — the number that
        # says what the run actually felt like, which a total never does.
        "max_drawdown": _drawdown(nets),
        "streak": _streak(nets),
    }


def _drawdown(nets: list[float]) -> float:
    peak = run = 0.0
    worst = 0.0
    for n in nets:
        run += n
        peak = max(peak, run)
        worst = min(worst, run - peak)
    return round(worst, 2)


def _streak(nets: list[float]) -> int:
    """Consecutive green (+) or red (−) sessions ending today. 0 if the last
    session was flat. Sign carries the direction, magnitude the length."""
    if not nets or nets[-1] == 0:
        return 0
    sign = 1 if nets[-1] > 0 else -1
    n = 0
    for v in reversed(nets):
        if (v > 0) - (v < 0) != sign:
            break
        n += 1
    return n * sign


__all__ = ["snapshot", "history", "backfill", "parse_contract", "session_date"]
