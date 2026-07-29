"""
ARTHA Terminal - Conversational analyst

Replaces api/server.py::_ai's "any symbol substring -> full deep dive" path.
Three problems it fixes:

  1. Symbol detection was `if s in question.upper()` over an unordered set of
     5173 symbols. Verified live before this rewrite: "Summarise this week's
     market-moving news" matched MARIS (inside "SUMMARISE") and "is the market
     overvalued right now?" matched VALUE (inside "OVERVALUED") — each then ran
     a 15-iteration deep dive on a random microcap and answered a question
     nobody asked. Set iteration order also made the pick nondeterministic
     across restarts. Now: word-boundary matching over symbols AND company
     names, longest-match-first, returning every symbol mentioned.

  2. Every detected symbol ran `deep_dive` — 8 tools, 10 fixed sections and a
     3-call debate — even for "what's TCS's P/E". Slow, and the one fact asked
     for was buried in section 3 of 10. Now the intent picks the depth.

  3. "Compare TCS vs Infosys" deep-dived TCS and silently dropped Infosys;
     "analyse my portfolio" had no portfolio data wired in at all and fell
     through to a generic web search. Both are real intents now.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator, Optional

from agent.prompts import COMPLIANCE, GROUNDING

logger = logging.getLogger("agent.chat")

MAX_SYMBOLS = 4
MAX_HISTORY_TURNS = 12

# Deep analysis is expensive (8 tools + 3 debate calls). Only run it when the
# question actually asks for a full workup, not merely because it names a stock.
_DEEP_RE = re.compile(
    r"\b(deep[\s-]?dive|full (?:analysis|report|breakdown)|analyse|analyze|"
    r"research|scorecard|red flags?|swot|should i (?:buy|sell|hold)|"
    r"investment case|bull case|bear case|verdict)\b",
    re.I,
)
_COMPARE_RE = re.compile(r"\b(vs\.?|versus|compare[d]?|better than|against)\b", re.I)
_PORTFOLIO_RE = re.compile(
    r"\b(my|our) (portfolio|holdings|book|positions|stocks|investments)\b|"
    r"\bportfolio (risk|health|allocation|performance|concentration)\b",
    re.I,
)

# "Show me pharma stocks" / "best IT stocks" / "which banks are cheapest".
#
# These used to route to `market`, which grounds on a breadth-and-flows snapshot
# plus a web search — nothing that lists individual companies. Verified live
# before this change: "Show me pharma stocks" answered "*No individual Indian
# pharma stock prices were in the provided feed*" and then recommended Johnson &
# Johnson, AbbVie and Merck off a web result, while 5,173 Indian symbols with
# sector, price, P/E, ROE and score sat unqueried in the local DB.
#
# Only the asking-for-a-list phrasing lives here. The *subject* is decided by
# screen_group(), which route_intent also requires — so "Which banks are
# cheapest?" qualifies without needing to name a noun like "stocks", while
# "What are the top gainers today?" resolves no group and stays a market
# question.
_SCREEN_RE = re.compile(
    r"\b(show me|list|screen(?:er)?|find me|give me|which|what are|top|best|"
    r"worst|cheapest|expensive|highest|lowest|most|biggest|largest|strongest|"
    r"weakest|leading|lagging|suggest)\b",
    re.I,
)

# Words that are also real ticker symbols on NSE/BSE. Matching these as symbols
# turns an ordinary English question into a deep dive on a microcap.
_STOPWORD_TICKERS = {
    "A", "AN", "THE", "IT", "IS", "IN", "ON", "AT", "TO", "OF", "OR", "SO", "UP",
    "ALL", "AND", "ANY", "ARE", "BUY", "CAN", "DID", "FOR", "HAS", "HOW", "NOW",
    "ONE", "OUT", "SEE", "TOP", "TWO", "WAS", "WHO", "WHY", "YES", "BEST", "BULL",
    "BEAR", "CASH", "DOWN", "GAIN", "GOOD", "HIGH", "HOLD", "LONG", "MORE", "NEXT",
    "OVER", "RISE", "SELL", "TIME", "VERY", "WELL", "WHAT", "WHEN", "WITH", "YEAR",
    "VALUE", "GROWTH", "INDIA", "MARKET", "MONEY", "PRICE", "SHARE", "STOCK", "TREND",
}

# Live tickers that are also ordinary English words a market question uses in
# its non-ticker sense. "What's the dollar rupee rate?" resolved DOLLAR (Dollar
# Industries, a hosiery maker) and routed to a single-stock lookup.
#
# Blanket-blocking them would break the legitimate "What is OIL trading at?",
# so instead these require case evidence: matched only when the raw question
# actually spells them in caps, or when the full company name matched. Every
# other ticker still matches case-insensitively, since users type "tcs price".
_AMBIGUOUS_TICKERS = {
    "ACE", "ALPHA", "APEX", "BETA", "DOLLAR", "ENERGY", "GLOBAL", "OIL",
    "SIGMA", "SILVER", "STAR", "TECH", "WEALTH",
}


# ----------------------------------------------------------------------
# Symbol resolution
# ----------------------------------------------------------------------
_INDEX: Optional[list[tuple[str, str]]] = None  # (needle, symbol), longest first

# Corporate boilerplate that appears in the register but not in how anyone
# refers to a company, so "Infosys" has to match "Infosys Limited".
_SUFFIX_RE = re.compile(
    r"\b(limited|ltd|india|indian|corporation|corp|company|co|"
    r"industries|enterprises|holdings|group|the)\b\.?", re.I)


def _normalize(text: str) -> str:
    """Shared normal form for both index needles and the incoming question.

    Both sides must go through this. Normalising only the index meant a needle
    like "FIRST CUSTODIAN FUND I" could never match the raw text it came from
    ("The First Custodian Fund (I) Ltd."), so any company whose name carried
    punctuation was unreachable by name.
    """
    t = _SUFFIX_RE.sub(" ", text)
    t = re.sub(r"[^\w\s&]", " ", t)
    return re.sub(r"\s+", " ", t).strip().upper()


def _index() -> list[tuple[str, str]]:
    """Searchable (needle, symbol) pairs from symbol_master, longest needle first.

    Includes company names so "Compare Tata Consultancy with Infosys" resolves,
    not just the ticker form. Built once — the universe only changes on an ETL run.
    """
    global _INDEX
    if _INDEX is not None:
        return _INDEX

    from db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT symbol, company_name FROM symbol_master WHERE symbol IS NOT NULL"
        ).fetchall()

    pairs: dict[str, str] = {}
    for r in rows:
        sym = (r["symbol"] or "").strip().upper()
        if not sym or sym in _STOPWORD_TICKERS:
            continue
        pairs.setdefault(sym, sym)
        name = (r["company_name"] or "").strip()
        if not name:
            continue
        core = _normalize(name)
        # Single short words are too collision-prone to match on ("POWER", "TATA").
        if len(core) >= 6 and core not in _STOPWORD_TICKERS:
            pairs.setdefault(core, sym)

    _INDEX = sorted(pairs.items(), key=lambda kv: -len(kv[0]))
    return _INDEX


def _mask_instructions(text: str) -> str:
    """Blank out the phrases that express intent, keeping string length.

    These words tell us what to DO, never what to do it to — but several are
    also live tickers, so leaving them in makes the instruction its own subject.
    Caught in testing: "Do a deep dive on TCS" resolved DEEP (a real BSE symbol)
    ahead of TCS and analysed a Basic Materials microcap instead. Same failure
    shape as the MARIS/VALUE substring bug, arriving by a different route.
    """
    for rx in (_DEEP_RE, _COMPARE_RE, _PORTFOLIO_RE):
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return text


def extract_symbols(question: str, limit: int = MAX_SYMBOLS) -> list[str]:
    """Every symbol mentioned, in the order mentioned, word-boundary matched."""
    up = _normalize(_mask_instructions(question))
    found: list[tuple[int, str]] = []
    claimed: list[tuple[int, int]] = []

    for needle, sym in _index():
        # A bare ambiguous ticker needs the user to have actually capitalised it.
        # Checked against the raw question, not the upper-cased form, which is
        # where that evidence is destroyed.
        if needle in _AMBIGUOUS_TICKERS and not re.search(
                rf"(?<![\w&]){re.escape(needle)}(?![\w&])", question):
            continue
        for m in re.finditer(rf"(?<![\w&]){re.escape(needle)}(?![\w&])", up):
            # A longer name already covered this span (e.g. don't also match
            # "INFO" inside a matched "INFOSYS").
            if any(s < m.end() and m.start() < e for s, e in claimed):
                continue
            claimed.append((m.start(), m.end()))
            found.append((m.start(), sym))
            break

    seen, out = set(), []
    for _, sym in sorted(found):
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out[:limit]


def route_intent(question: str, symbols: list[str]) -> str:
    """lookup | deep | compare | portfolio | screen | market."""
    if _PORTFOLIO_RE.search(question):
        return "portfolio"
    if len(symbols) >= 2 and _COMPARE_RE.search(question):
        return "compare"
    # Screening beats a bare lookup: "best IT stocks" wants the list, even
    # though INFY happens to be nameable. It must not beat an explicit deep
    # dive or comparison on named companies.
    if _SCREEN_RE.search(question) and screen_group(question):
        return "screen"
    if not symbols:
        return "market"
    if _DEEP_RE.search(question):
        return "deep"
    return "lookup"


def resolve(question: str, history: list[dict] | None = None) -> tuple[list[str], str]:
    """(symbols, intent) for a turn — the single router both callers share.

    Resolving without history routed "What about its debt?" as a market
    question and fired a web search, because the pronoun carries the subject.
    Callers must not re-derive this.
    """
    symbols = extract_symbols(question)
    if not symbols:
        for m in reversed(trim_history(history or [])):
            prior = extract_symbols(m["content"])
            if prior:
                symbols = prior[:1]
                break
    return symbols, route_intent(question, symbols)


# ----------------------------------------------------------------------
# Grounding
# ----------------------------------------------------------------------
def _fmt(v, unit: str = "") -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:,.2f}{unit}"
    return f"{v}{unit}"


# No plausibility filter on the ratios here, deliberately.
#
# An earlier revision dropped any P/E outside -100..500 after finding TCS at
# 45,597 and HDFC Bank at 123,617 in db/artha.db. That file is a stale
# development copy: it holds 20 rows scraped by the screener.in path, whose
# label matching is by substring, so "pe" also caught "Expenses". The running
# container reads /data/db/artha.db (the artha-db volume) — 3,016 rows from
# yfinance, HDFC Bank at 16.41, TCS at 17.41.
#
# Against real data the filter only hid truth: the 75 values above 500 are
# near-zero-earnings microcaps (IMAGICAA 4,629, NETPIX 3,360) whose P/E really
# is that number. Showing n/a there is a worse lie than showing 4,629.


def symbol_facts(symbol: str) -> str:
    """Compact factsheet for one symbol, straight from the DB. No LLM, no network.

    This is what makes `lookup` fast: the numbers the model needs are already
    computed and stored, so a P/E question doesn't need an 8-tool agent loop.
    """
    from db import get_connection
    with get_connection() as conn:
        row = conn.execute("""
            SELECT m.symbol, m.company_name, m.market_cap_cr,
                   COALESCE(m.sector, cm.sector, 'Other') AS sector, m.industry,
                   f.pe_ratio, f.pb_ratio, f.roe, f.roce, f.debt_to_equity,
                   f.dividend_yield, f.net_margin, f.current_ratio,
                   f.sales_cagr_3y, f.profit_cagr_3y, f.date_updated,
                   cm.analysis_score, cm.rsi_14, cm.beta, cm.dma_50, cm.dma_200,
                   cm.ath, cm.atl, cm.distance_from_ath,
                   cm.return_1d, cm.return_1m, cm.return_6m, cm.return_1y, cm.return_3y
            FROM symbol_master m
            LEFT JOIN fundamentals f ON f.symbol = m.symbol
            LEFT JOIN computed_metrics cm ON cm.symbol = m.symbol
            WHERE m.symbol = ?
        """, (symbol,)).fetchone()
        last = conn.execute(
            "SELECT date, close, volume FROM prices_daily WHERE symbol = ? "
            "ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()

    if not row:
        return f"{symbol}: not found in the ARTHA universe."

    d = dict(row)
    lines = [
        f"### {d['symbol']} — {d.get('company_name') or 'name unavailable'}",
        f"Sector: {d.get('sector')}{' / ' + d['industry'] if d.get('industry') else ''}"
        f" | Market cap: {_fmt(d.get('market_cap_cr'))} Cr",
    ]
    if last:
        lines.append(f"Last close: Rs {_fmt(last['close'])} on {last['date']}"
                     f" | Volume: {_fmt(last['volume'])}")
    lines.append(
        "Returns %: "
        f"1D {_fmt(d.get('return_1d'))} | 1M {_fmt(d.get('return_1m'))} | "
        f"6M {_fmt(d.get('return_6m'))} | 1Y {_fmt(d.get('return_1y'))} | "
        f"3Y {_fmt(d.get('return_3y'))}"
    )
    lines.append(
        "Technicals: "
        f"50DMA {_fmt(d.get('dma_50'))} | 200DMA {_fmt(d.get('dma_200'))} | "
        f"RSI14 {_fmt(d.get('rsi_14'))} | Beta {_fmt(d.get('beta'))} | "
        f"ATH {_fmt(d.get('ath'))} ({_fmt(d.get('distance_from_ath'))}% away) | "
        f"ATL {_fmt(d.get('atl'))}"
    )
    lines.append(
        "Fundamentals: "
        f"P/E {_fmt(d.get('pe_ratio'))} | P/B {_fmt(d.get('pb_ratio'))} | "
        f"ROE {_fmt(d.get('roe'))}% | ROCE {_fmt(d.get('roce'))}% | "
        f"D/E {_fmt(d.get('debt_to_equity'))} | Net margin {_fmt(d.get('net_margin'))}% | "
        f"Div yield {_fmt(d.get('dividend_yield'))}% | "
        f"Sales CAGR 3Y {_fmt(d.get('sales_cagr_3y'))}% | "
        f"Profit CAGR 3Y {_fmt(d.get('profit_cagr_3y'))}%"
    )
    score = d.get("analysis_score")
    lines.append(
        f"ARTHA Analysis Score: {_fmt(score)}/10"
        if score is not None else
        "ARTHA Analysis Score: not computed (insufficient fundamental coverage for this symbol)"
    )
    if d.get("date_updated"):
        lines.append(f"Fundamentals last refreshed: {d['date_updated']}")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Screening
# ----------------------------------------------------------------------
# Longest phrase first — "psu bank" must beat "bank", "oil and gas" must beat
# "gas". Keys are NSE index_key values already in index_members, so membership
# comes from the weekly NSE constituent pull rather than a list maintained here.
_GROUPS: list[tuple[str, str, str]] = [
    (r"psu bank(?:s|ing)?|public sector bank(?:s)?", "psubank", "Nifty PSU Bank"),
    (r"oil (?:and |& ?)?gas|oilgas|refiner(?:y|ies)", "oilgas", "Nifty Oil & Gas"),
    (r"consumer durable(?:s)?|white goods", "consumerdurables", "Nifty Consumer Durables"),
    (r"pharma(?:ceutical)?(?:s)?|drug ?maker(?:s)?", "pharma", "Nifty Pharma"),
    (r"health ?care|hospital(?:s)?|diagnostic(?:s)?", "healthcare", "Nifty Healthcare"),
    (r"\bit\b|info ?tech|software|tech(?:nology)? (?:stocks?|companies|sector|space)",
     "it", "Nifty IT"),
    (r"bank(?:s|ing)?", "banknifty", "Bank Nifty"),
    (r"auto(?:mobile|motive)?(?:s)?|car ?maker(?:s)?|two ?wheeler(?:s)?", "auto", "Nifty Auto"),
    (r"fmcg|consumer staple(?:s)?|consumer good(?:s)?", "fmcg", "Nifty FMCG"),
    (r"metal(?:s)?|steel|mining", "metal", "Nifty Metal"),
    (r"realty|real ?estate|propert(?:y|ies)|housing", "realty", "Nifty Realty"),
    (r"infra(?:structure)?", "infra", "Nifty Infrastructure"),
    (r"financial(?: services)?|nbfc(?:s)?|lender(?:s)?", "finance", "Nifty Financial Services"),
    (r"power|utilit(?:y|ies)|electricit(?:y)?", "energy", "Nifty Energy"),
    (r"energy", "energy", "Nifty Energy"),
    (r"commodit(?:y|ies)", "commodities", "Nifty Commodities"),
    (r"next ?50", "niftynext50", "Nifty Next 50"),
    (r"mid ?cap(?:s)?", "niftymidcap150", "Nifty Midcap 150"),
    (r"nifty ?50|large ?cap(?:s)?|blue ?chip(?:s)?", "nifty50", "NIFTY 50"),
]

# How to rank, keyed on what the question asked for. (column, direction, label)
_ORDERS: list[tuple[str, str, str, str]] = [
    (r"cheap(?:est)?|lowest (?:p/?e|valuation)|undervalued", "f.pe_ratio", "ASC", "lowest P/E"),
    (r"expensive|highest (?:p/?e|valuation)|overvalued", "f.pe_ratio", "DESC", "highest P/E"),
    (r"highest roe|most profitable|best roe", "f.roe", "DESC", "highest ROE"),
    (r"dividend|yield", "f.dividend_yield", "DESC", "highest dividend yield"),
    (r"gainer(?:s)?|rising|up today|best perform", "cm.return_1d", "DESC", "today's gain"),
    (r"loser(?:s)?|falling|down today|worst perform", "cm.return_1d", "ASC", "today's fall"),
    (r"best|top|strongest|highest scor", "cm.analysis_score", "DESC", "ARTHA Analysis Score"),
    (r"big(?:gest)?|large(?:st)?", "m.market_cap_cr", "DESC", "market cap"),
]

SCREEN_LIMIT = 15


def screen_group(question: str) -> tuple[str, str] | None:
    """(index_key, display label) the question is asking about, or None."""
    for pattern, key, label in _GROUPS:
        if re.search(pattern, question, re.I):
            return key, label
    return None


# SQL column -> the row key it lands in, for checking whether a ranking is real.
_RANK_KEY = {"f.pe_ratio": "pe_ratio", "f.roe": "roe",
             "f.dividend_yield": "dividend_yield", "cm.return_1d": "return_1d",
             "cm.analysis_score": "analysis_score", "m.market_cap_cr": "market_cap_cr"}


def _rank_value(row: dict, col: str):
    key = _RANK_KEY.get(col)
    return row.get(key) if key else None


def _screen_order(question: str) -> tuple[str, str, str]:
    for pattern, col, direction, label in _ORDERS:
        if re.search(pattern, question, re.I):
            return col, direction, label
    return "m.market_cap_cr", "DESC", "market cap"


def screen_facts(question: str) -> str:
    """Real constituents of the sector/index the question named, from the DB.

    The whole point: a list question must be answered from the 5,173-symbol
    local universe, not from whatever a web search turns up. Membership comes
    from index_members (the weekly NSE constituent pull), so nothing here is a
    hand-maintained list of names.
    """
    group = screen_group(question)
    if not group:
        return ""
    key, label = group
    col, direction, order_label = _screen_order(question)

    from db import get_connection
    with get_connection() as conn:
        # {col}/{direction} come from _ORDERS above, never from user text.
        rows = conn.execute(f"""
            SELECT im.symbol, im.index_name, m.company_name,
                   m.market_cap_cr, f.pe_ratio, f.roe, f.dividend_yield,
                   cm.analysis_score, cm.return_1d, cm.return_1y, cm.rsi_14,
                   p.close, p.date AS price_date
              FROM index_members im
              LEFT JOIN symbol_master m     ON m.symbol = im.symbol
              LEFT JOIN fundamentals f      ON f.symbol = im.symbol
              LEFT JOIN computed_metrics cm ON cm.symbol = im.symbol
              LEFT JOIN (SELECT symbol, close, date FROM (
                            SELECT symbol, close, date,
                                   ROW_NUMBER() OVER (PARTITION BY symbol
                                                      ORDER BY date DESC) rn
                              FROM prices_daily) WHERE rn = 1) p
                     ON p.symbol = im.symbol
             WHERE im.index_key = ?
             ORDER BY ({col} IS NULL), {col} {direction}
             LIMIT ?
        """, (key, SCREEN_LIMIT)).fetchall()
        total = conn.execute("SELECT COUNT(*) n FROM index_members WHERE index_key = ?",
                             (key,)).fetchone()["n"]

    if not rows:
        return (f"### {label}\nNo constituents are stored for {label}. Say the index "
                f"membership has not been ingested yet rather than naming companies "
                f"from memory.")

    label = dict(rows[0]).get("index_name") or label   # NSE's own name for it
    data = [dict(r) for r in rows]

    # Only columns that actually carry a value get printed. A column of fifteen
    # "n/a"s costs prompt space, adds nothing, and reads to a model as a blank
    # worth being helpful about.
    optional = [("1D%", "return_1d"), ("1Y%", "return_1y"), ("P/E", "pe_ratio"),
                ("ROE%", "roe"), ("Div%", "dividend_yield"),
                ("Mcap Cr", "market_cap_cr"), ("Score", "analysis_score")]
    present = [(head, key) for head, key in optional
               if any(d.get(key) is not None for d in data)]
    missing = [head for head, key in optional if (head, key) not in present]

    heads = ["Symbol", "Company", "Close"] + [h for h, _ in present]
    lines = [
        f"### {label} — {len(data)} of {total} constituents, ranked by {order_label}",
        "| " + " | ".join(heads) + " |",
        "|" + "---|" * len(heads),
    ]
    ranked = 0
    for d in data:
        ranked += _rank_value(d, col) is not None
        cells = [d["symbol"], (d.get("company_name") or "")[:28], _fmt(d.get("close"))]
        cells += [_fmt(d.get(key)) for _, key in present]
        lines.append("| " + " | ".join(cells) + " |")

    if missing:
        lines.append(
            f"\nNOT AVAILABLE for these names: {', '.join(missing)}. Those columns "
            f"are absent above because the data has not been ingested, not because "
            f"they are zero. State that they are unavailable if asked — do not "
            f"supply, estimate or recall a value for any of them."
        )
    # Ranking by a column that is null for everyone silently degrades to
    # default order while the heading still claims a ranking. Say so.
    if ranked == 0:
        lines.append(
            f"\nNOTE: {order_label} is unavailable for every name above, so this "
            f"list is NOT ranked by it — it is the membership in default order. "
            f"Tell the user that metric has not been ingested yet instead of "
            f"presenting the order as a ranking."
        )
    elif ranked < len(data):
        lines.append(f"\nNOTE: {order_label} is available for only {ranked} of "
                     f"{len(data)} names; the rest are listed after them, unranked.")
    dates = {d["price_date"] for d in data if d.get("price_date")}
    if dates:
        lines.append(f"\nCloses as of {max(dates)}. This is the complete stored "
                     f"membership for {label} — do not add companies that are not "
                     f"in this table.")
    return "\n".join(lines)


def screen_display(block: str) -> str:
    """The heading + table rows of a screen block, for showing to the user as-is.

    The figures on screen come out of the DB rather than being re-typed by an
    LLM: the table is emitted verbatim and the model is asked for commentary
    only. Same principle the deep path already applies to its deterministic
    engines — present, don't re-derive. It also drops a 15-row table out of the
    generated tokens, which is most of what a screen answer would otherwise
    spend its time streaming.
    """
    out = []
    for line in block.splitlines():
        if line.startswith("###") or line.startswith("|"):
            out.append(line)
        elif out and not line.strip():
            continue
        elif out:
            break
    return "\n".join(out)


def portfolio_facts() -> tuple[str, list[str]]:
    """Real holdings + day P&L + concentration, for portfolio questions.

    Previously there was no portfolio grounding at all, so "analyse the risk in
    my portfolio" — one of the page's own suggestion chips — fell through to a
    generic web search and answered about the market instead of the user's book.
    """
    try:
        from api.server import _holdings
        res = _holdings()
    except Exception as e:
        logger.warning(f"portfolio grounding failed: {e}")
        return "", []

    if not res.get("ok") or not res.get("items"):
        return ("The user's brokerage account is not connected or holds no positions "
                "(Upstox status: %s). Say so plainly and do not invent holdings."
                % res.get("status", "unknown")), []

    items = res["items"]
    invested = sum(i["invested"] for i in items)
    current = sum(i["current"] for i in items)
    day = sum((i.get("dayChange") or 0) * i["qty"] for i in items)

    pnl_pct = f" ({(current - invested) / invested * 100:+.2f}%)" if invested else ""
    lines = [
        "### User's actual holdings (live from their broker)",
        f"Positions: {len(items)} | Invested: Rs {invested:,.0f} | "
        f"Current: Rs {current:,.0f} | Overall P&L: Rs {current - invested:,.0f}{pnl_pct}",
        f"Today's P&L: Rs {day:,.0f}",
        "",
        "| Symbol | Qty | Avg | LTP | Value | Weight% | Overall P&L | Day P&L |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i in sorted(items, key=lambda x: -x["current"]):
        w = i["current"] / current * 100 if current else 0
        lines.append(
            f"| {i['symbol']} | {i['qty']} | {i['avg']:,.2f} | {i['price']:,.2f} | "
            f"{i['current']:,.0f} | {w:.1f} | {i['pnl']:+,.0f} ({i['pnlPct']:+.1f}%) | "
            f"{(i.get('dayChange') or 0) * i['qty']:+,.0f} |"
        )
    return "\n".join(l for l in lines if l != ""), [i["symbol"] for i in items]


# ----------------------------------------------------------------------
# System prompt
# ----------------------------------------------------------------------
_STYLE = f"""You are ARTHA, an equity research analyst for Indian markets (NSE/BSE).

{GROUNDING}
- The data you were given is the DATA block below. You DO have live data — it is
  provided there. Never claim you cannot access real-time information.

STYLE:
- Answer the question that was asked, first, in the first sentence. Add context after.
- Markdown: **bold** for key figures, `##` headings only when the answer has
  genuinely separate sections, tables for any comparison of 3+ metrics.
- Short paragraphs and tight bullets. No filler preamble, no restating the question.
- Currency as Rs, returns as %, market cap in Cr — the units the data uses.
- Match the answer's length to the question's scope. A one-fact question gets a
  one-line answer, not a report.

{COMPLIANCE}
Do not append a disclaimer to every message — the interface already shows one."""

_INTENT_STEER = {
    "lookup": "Answer this specific question directly and briefly. Do not produce a "
              "full report or add sections that were not asked for.",
    "compare": "Compare the named companies side by side. Lead with a markdown table "
               "of the metrics that matter to the question, then 3-5 bullets on what "
               "the differences mean. Note explicitly where a metric is missing for "
               "one side, since that makes the comparison partial.",
    "portfolio": "Answer about THIS user's real book shown below — reference their "
                 "actual symbols, weights and P&L, never a hypothetical portfolio. "
                 "Call out concentration (any position above 25% of the book), "
                 "sector clustering, and the largest drawdown contributors.",
    "market": "Answer from the live market data and any web results provided. "
              "Be specific about breadth, flows and movers rather than general.",
    "screen": "The table below is the complete stored constituent list for the "
              "index the user asked about. Answer ONLY from it: never add a "
              "company that is not in the table, and never substitute foreign "
              "listings for Indian ones. Reproduce ONLY the columns the table "
              "actually has — if it carries no P/E, ROE, market cap or score "
              "column, your answer must not contain one either, and you must "
              "not derive rankings, concentration shares or valuation ranges "
              "from figures that are not there. Say plainly which metrics are "
              "unavailable. The constituent table is already on screen — write "
              "only the commentary beneath it: 3-5 bullets naming the specific "
              "companies that answer the question and what the available "
              "columns show, then one line on which metrics are missing. Output "
              "no table of your own.",
    "deep": "Give a structured workup with `##` headings, in this order: Snapshot "
            "(2 lines), Valuation, Growth & Profitability, Financial Health, "
            "Technical Position, Red Flags, Peer Context, then Verdict. Reproduce "
            "every red flag with its severity and every scorecard sub-score with "
            "its value — those come from deterministic engines and are the "
            "auditable core of the analysis, so never summarise them away. Close "
            "the Verdict with a genuinely two-sided read (why one might be "
            "constructive, why one might be cautious) and a soft signal only. "
            "Omit any section whose data is entirely unavailable rather than "
            "padding it.",
}


def build_system(intent: str, data_blocks: list[str]) -> str:
    steer = _INTENT_STEER.get(intent, _INTENT_STEER["lookup"])
    data = "\n\n".join(b for b in data_blocks if b)
    return f"{_STYLE}\n\nTASK:\n{steer}\n\n=== DATA ===\n{data or 'No data available.'}\n=== END DATA ==="


def trim_history(messages: list[dict]) -> list[dict]:
    """Keep the last N turns so follow-ups work without blowing the context.

    ponytail: plain tail-truncation. agent/context_window.py's summarising
    compressor already runs inside ModelRouter for the small-context tier, so
    this only needs to bound the obvious case.
    """
    clean = [
        {"role": "assistant" if m.get("role") in ("ai", "assistant") else "user",
         "content": str(m.get("content") or m.get("text") or "")[:6000]}
        for m in messages if (m.get("content") or m.get("text"))
    ]
    return clean[-MAX_HISTORY_TURNS:]


# ----------------------------------------------------------------------
# Deep dive tool run
# ----------------------------------------------------------------------
# The tools a full workup pulls, in the order the answer needs them. Each is
# reported to the UI as it runs — the deep path previously only ran red flags
# and the scorecard, and the non-streaming path ran the 15-iteration agent loop
# to completion behind a spinner before anything appeared on screen.
_DEEP_TOOLS = (
    ("scan_red_flags",    "Scanning for red flags",  "red flags"),
    ("compute_scorecard", "Computing the scorecard", "scorecard"),
    ("resolve_peers",     "Resolving sector peers",  "peer group"),
)

# Deterministic engine output must reach the model as-is: these two are the
# auditable core of the product and the LLM's job is to present, not re-derive.
_ENGINE_TOOLS = {"scan_red_flags", "compute_scorecard"}


async def _deep_tools(symbol: str):
    """Run the deep-dive tools, yielding (event, payload, block, source).

    A tuple with `block` set is data for the prompt; otherwise it's a UI event.
    Any single tool failing degrades that section only — a missing peer group
    shouldn't cost the user the whole analysis.
    """
    import agent.tools as tools

    for fn_name, label, section in _DEEP_TOOLS:
        yield "status", {"stage": "tool", "label": label}, None, None
        try:
            res = await asyncio.wait_for(getattr(tools, fn_name)(symbol), timeout=45)
        except Exception as e:
            logger.warning(f"{fn_name} failed for {symbol}: {e}")
            continue
        if res.get("status") != "OK":
            continue
        note = (" (deterministic engine output — present every finding faithfully; "
                "you cannot override, soften or recompute it)"
                if fn_name in _ENGINE_TOOLS else "")
        yield None, None, f"### {symbol} {section}{note}\n{res}", fn_name

    # Sector news needs the sector name, which the factsheet already resolved.
    sector = await asyncio.to_thread(_sector_of, symbol)
    if sector and sector != "Other":
        yield "status", {"stage": "tool", "label": f"Fetching {sector} sector news"}, None, None
        try:
            news = await asyncio.wait_for(tools.sector_news(sector, 6), timeout=30)
            items = news.get("results") or news.get("articles") or []
            if items:
                lines = "\n".join(
                    f"- {a.get('title', '')}: {a.get('snippet', a.get('description', ''))}"
                    for a in items[:6] if a.get("title"))
                if lines:
                    yield None, None, f"### Recent {sector} sector news\n{lines}", "sector_news"
        except Exception as e:
            logger.warning(f"sector_news failed for {sector}: {e}")


def _sector_of(symbol: str) -> str | None:
    from db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(m.sector, cm.sector) AS sector FROM symbol_master m "
            "LEFT JOIN computed_metrics cm ON cm.symbol = m.symbol WHERE m.symbol = ?",
            (symbol,)).fetchone()
    return row["sector"] if row else None


# ----------------------------------------------------------------------
# Turn
# ----------------------------------------------------------------------
async def answer(
    question: str,
    history: list[dict] | None = None,
    market_context: str = "",
    web_context: str = "",
) -> AsyncIterator[tuple[str, dict]]:
    """Stream one conversational turn as (event, payload) pairs.

    Events: `status` (what it's doing), `delta` (text chunk), `meta` (final).
    """
    raw_history = history or []
    history = trim_history(raw_history)
    symbols, intent = resolve(question, raw_history)
    yield "status", {"stage": "route", "intent": intent, "symbols": symbols}

    blocks: list[str] = []
    sources: list[str] = []
    cards: list[str] = list(symbols)

    if intent == "portfolio":
        yield "status", {"stage": "tool", "label": "Reading your live holdings"}
        # portfolio_facts -> _holdings uses asyncio.run() internally, which
        # throws if called on a running loop. Give it its own thread.
        pf, held = await asyncio.to_thread(portfolio_facts)
        if pf:
            blocks.append(pf)
            sources.append("Upstox holdings")
        cards = held[:6]
        for s in cards:
            blocks.append(await asyncio.to_thread(symbol_facts, s))
        if held:
            sources.append("ARTHA database")

    elif intent == "screen":
        group = screen_group(question)
        yield "status", {"stage": "tool",
                         "label": f"Screening {group[1]} constituents" if group
                                  else "Screening the universe"}
        block = await asyncio.to_thread(screen_facts, question)
        if block:
            blocks.append(block)
            sources.append("ARTHA database")
            # The table goes to the user straight from the DB, not via the
            # model — see screen_display(). The model writes only the prose.
            table = screen_display(block)
            if table:
                yield "delta", {"text": table + "\n\n"}
                blocks.append(
                    "The table above has ALREADY been shown to the user verbatim. "
                    "Do NOT output a table, do not restate its rows, and do not "
                    "add columns to it. Write only the commentary that follows it."
                )

    elif intent == "deep":
        sym = symbols[0]
        yield "status", {"stage": "tool", "label": f"Loading {sym} factsheet"}
        blocks.append(await asyncio.to_thread(symbol_facts, sym))
        sources.append("ARTHA database")
        async for ev, payload, block, src in _deep_tools(sym):
            if block:
                blocks.append(block)
                sources.append(src)
            else:
                yield ev, payload

    else:
        for s in symbols:
            yield "status", {"stage": "tool", "label": f"Fetching {s}"}
            blocks.append(await asyncio.to_thread(symbol_facts, s))
        if symbols:
            sources.append("ARTHA database")

    if market_context and intent in ("market", "portfolio", "deep", "screen"):
        blocks.append(f"### Live market context\n{market_context}")
    if web_context:
        blocks.append(f"### Live web search results\n{web_context}")

    yield "status", {"stage": "thinking"}

    from agent.llm_client import ModelRouter, AllTiersExhausted
    msgs = [{"role": "system", "content": build_system(intent, blocks)}]
    msgs += history
    msgs.append({"role": "user", "content": question})

    shape = "deep" if intent in ("deep", "compare", "portfolio") else "quick"
    text = ""
    try:
        async for delta in ModelRouter().stream(msgs, task_shape=shape):
            text += delta
            yield "delta", {"text": delta}
    except AllTiersExhausted as e:
        yield "error", {"message": "All free AI tiers are rate-limited right now. "
                                   "They reset within a few minutes — try again shortly.",
                        "detail": str(e)}
        return

    yield "meta", {"intent": intent, "symbols": symbols, "cards": cards,
                   "sources": sources, "chars": len(text)}


__all__ = ["answer", "resolve", "extract_symbols", "route_intent", "symbol_facts",
           "portfolio_facts", "screen_facts", "screen_group", "build_system",
           "trim_history"]
