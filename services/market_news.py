"""
ARTHA Terminal - Live Market News service

Pipeline (all live, no pre-populated cache required):
  1. Fetch  — open-source web search (SerpAPI primary → SearxNG fallback) across
              Indian-market AND international queries, plus a live Finnhub poll.
              SearchService already caches results.
  2. Curate — ONE LLM call ("quick" tier chain) that both ranks/dedupes the raw
              hits into the most market-relevant headlines (each with a one-line
              "why it matters", a region, an impact grade and any tickers named)
              and writes the session briefing. Strictly grounded: the model may
              only cite results it was given, by row number.
  3. Fallback — if the LLM is unavailable, we still return the raw search hits so
                the feed is never empty when search worked.

The briefing is session-aware: a pre-open plan before 09:15 IST, a read of what
is moving the tape while the NSE is open, and a wrap after the close. The phase
comes from the real exchange calendar, so holidays are handled.

Nothing here fabricates headlines or links — every item carries a real source URL
taken from the search results.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agent.prompts import COMPLIANCE, GROUNDING, HOUSE_STYLE

_SYSTEM = (
    f"{GROUNDING}\n\n{HOUSE_STYLE}\n\n{COMPLIANCE}\n\n"
    "You are a financial news editor for Indian markets: you rank and summarise "
    "the search results you were given. Return ONLY the JSON asked for."
)


# Queries span the whole market: indices, sectors, macro/policy, flows, earnings
# and corporate action — so the feed (and the UI category tabs) cover the full
# scope, not just headline indices. Each is one search credit, cached 6h.
_QUERIES_INDIA = [
    "Indian stock market news today Nifty Sensex",
    "India sector stocks news today gainers losers banking IT pharma auto metals",
    "India markets FII DII institutional flows mutual fund inflows today",
    "India RBI monetary policy inflation CPI GDP rupee crude macro news today",
    "India company earnings results Q results dividend buyback merger acquisition IPO today",
    "India global markets cues US Fed Dow Nasdaq Asian markets impact today",
]

# International coverage. An Indian desk trades the overnight gap, so what the
# US, Europe, Asia, oil, gold and the dollar did IS the pre-open story — the
# feed used to carry it only where an Indian outlet happened to mention it.
_QUERIES_GLOBAL = [
    "US stock market today Fed rate decision Wall Street Dow Nasdaq S&P 500",
    "Europe Asia stock markets today China Japan ECB Bank of Japan central bank",
    "crude oil gold dollar index bond yields commodity currency markets today",
    "global economy geopolitics tariffs trade war supply chain market impact today",
]

# ponytail: search stays on the 6h SearchService TTL — SerpAPI's free tier is
# ~100 credits/month and 10 queries/hour would burn that in half a day. The
# intraday freshness comes from Finnhub below, which is polled live every run.
_QUERIES: list[tuple[str, str]] = (
    [(q, "india") for q in _QUERIES_INDIA] + [(q, "global") for q in _QUERIES_GLOBAL]
)


def _search(query: str, limit: int = 6) -> list[dict]:
    """Blocking wrapper around the async SearchService (SerpAPI → SearxNG)."""
    import asyncio
    from services.search import SearchService

    async def _go():
        try:
            return await SearchService().search(query, limit=limit, ttl_hours=6)
        except Exception:
            return []

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_go())
        finally:
            loop.close()
    except Exception:
        return []


# Search engines return social posts and video pages alongside the wires, and
# they rank well for exactly the queries above. A card bylined "Instagram" over
# "Dow Jones tumbles 500 points" is not a source an investor can check, and the
# curator happily cites them because they look like any other result.
_NOT_A_PUBLISHER = (
    "facebook.com", "instagram.com", "youtube.com", "youtu.be", "twitter.com",
    "x.com", "linkedin.com", "reddit.com", "tiktok.com", "pinterest.com",
    "quora.com", "telegram.me", "t.me", "whatsapp.com",
)


def _is_publisher(url: str) -> bool:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    if not m:
        return False
    host = m.group(1).lower()
    return not any(host == d or host.endswith("." + d) for d in _NOT_A_PUBLISHER)


# A section front is not a story. Web search ranks these top for every "... news
# today" query — an outlet's markets landing page, a broker's quote page, a
# screener tool — and they never carry a date, so nothing downstream could age
# them out. Worse, handing one to the curator invites it to invent a headline:
# "Sensex gains modestly while Nifty declines in early trade" was written for
# thehindu.com/business/markets/, whose real title is just "Stock Market Today".
_SECTION_SLUGS = {
    "markets", "market", "equity", "equities", "news", "stocks", "stock",
    "business", "indices", "index", "quote", "quotes", "live", "home",
    "sector-performance", "top-gainers-today", "stocksmarketsindia",
}


def _is_article(url: str) -> bool:
    """True when a URL looks like one story rather than a section front.

    Judged on the last path segment: a story slug is long and hyphenated, or
    ends in a numeric article id (`/articleshow/12345678.cms`). A section is a
    short bare noun. Deliberately shape-based — there is no date in a search
    result to check, and fetching every candidate to find out would cost a
    round-trip per hit.
    """
    m = re.match(r"https?://[^/]+(/.*)?$", url or "")
    if not m:
        return False
    path = (m.group(1) or "/").split("?")[0].split("#")[0]
    segments = [s for s in path.split("/") if s]
    if not segments:
        return False  # bare domain: nseindia.com/
    last = segments[-1].lower()
    if "." in last:
        last = last.rsplit(".", 1)[0]  # strip .html/.cms/.ece
    if last in _SECTION_SLUGS:
        return False
    if re.search(r"\d{5,}", last):
        return True  # publisher article id
    return last.count("-") >= 3 or len(last) >= 28


def _age_hours(published: str | None) -> float | None:
    """Hours since `published`, or None when the item carries no date."""
    if not published:
        return None
    try:
        dt = datetime.fromisoformat(published)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


# Dated items older than this are dropped outright. A trading desk's feed is
# worthless at two days; it was carrying a 2017 CNBC article.
_MAX_AGE_HOURS = 48

# Article URLs often embed the publication date. It is the only age signal a
# search hit has — RSS and Finnhub carry a real timestamp, search carries none —
# and it is exactly what catches /amp/2017/07/19/.
_URL_DATE = re.compile(r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:[/-]|$)")


def _age_tag(published: str | None) -> str:
    """" (2h)" / " (3d)" / " (undated)" — shown against each row in the curation
    prompt so "select recent items" is something the model can actually see
    rather than a word it has to take on faith."""
    age = _age_hours(published)
    if age is None:
        return " (undated)"
    return f" ({int(age)}h)" if age < 48 else f" ({int(age / 24)}d)"


def _date_from_url(url: str) -> str | None:
    m = _URL_DATE.search(url or "")
    if not m:
        return None
    try:
        y, mo, d = (int(g) for g in m.groups())
        return datetime(y, mo, d, tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _domain(url: str) -> str:
    """Publisher name from a URL, e.g. 'economictimes.indiatimes.com' -> 'Economictimes'."""
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    if not m:
        return "Web"
    host = m.group(1).split(".")
    return (host[0] or "Web").capitalize()


def _gather() -> list[dict]:
    """Every source, deduped by link then title, freshest first.

    Order matters and is the opposite of what it used to be. RSS and Finnhub run
    BEFORE search because they are the only sources that carry a real
    publication time, and `_interleave` downstream takes a head slice: with
    search first, the 32 RSS articles gathered every cycle sat at India index 26
    and beyond, so **none of them ever reached the curator**. The feed was
    ranking search hits exclusively while the freshest, properly-dated,
    real-article source was collected and thrown away.

    Each hit carries the `region` of the source that found it, so the fallback
    path (LLM unavailable) still splits India vs. international correctly, plus
    `published` (ISO-8601 UTC, or None when nothing could date it).
    """
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict] = []

    def _add(title: str, link: str, snippet: str, region: str,
             published: str | None = None) -> None:
        title = (title or "").strip()
        link = (link or "").strip()
        if not title or not _is_publisher(link) or not _is_article(link):
            return
        tkey = title.lower()[:80]
        if (link and link in seen_links) or tkey in seen_titles:
            return
        # Search results have no date of their own; the URL is the only signal.
        published = published or _date_from_url(link)
        age = _age_hours(published)
        if age is not None and age > _MAX_AGE_HOURS:
            return
        if link:
            seen_links.add(link)
        seen_titles.add(tkey)
        out.append({"title": title, "link": link,
                    "snippet": (snippet or "").strip(), "region": region,
                    "published": published})

    try:
        from services.india_news import get_india_market_news
        # Publisher RSS: the freshest source there is (items minutes old) and
        # the only Indian one that survives SerpAPI's spent quota.
        for r in get_india_market_news():
            _add(r.get("title"), r.get("link"), r.get("snippet"), "india", r.get("published"))
    except Exception:
        pass

    try:
        from services.finnhub_news import get_finnhub_general_news
        # Finnhub's `general` category is US/world wire copy, not Indian.
        for r in get_finnhub_general_news():
            _add(r.get("title"), r.get("link"), r.get("snippet"), "global", r.get("published"))
    except Exception:
        pass

    for q, region in _QUERIES:
        for r in _search(q):
            _add(r.get("title"), r.get("link"), r.get("snippet"), region)

    # Newest first, undated last. Undated hits are search results, which are the
    # least trustworthy rung on recency — but they are not dropped, because "no
    # date found" is not evidence of being old.
    #
    # Sorted on the parsed instant, not the ISO string: string order is only
    # equivalent while every timestamp is UTC, and that is an invariant three
    # separate modules would have to keep.
    dated = [r for r in out if r["published"]]
    undated = [r for r in out if not r["published"]]
    dated.sort(key=lambda r: _age_hours(r["published"]) or 0.0)
    return dated + undated


def session_phase() -> str:
    """'pre_open' | 'open' | 'post_close' for the NSE session, holiday-aware.

    Reuses services.global_markets.market_status (real exchange calendar) rather
    than re-deriving a weekday+clock window here. When the market is shut, the
    calendar's note reads "opens 09:15 IST" only if the next open is *today*
    (it switches to "opens Mon 04 Aug" otherwise), so that plus a clock check
    separates the pre-open window from everything after the close.
    """
    from datetime import time as _time
    from services.global_markets import INDIA, market_status

    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    st = market_status(INDIA[0])
    if st["state"] == "open":
        return "open"
    note = st.get("note", "")
    return "pre_open" if ":" in note and now.time() < _time(9, 15) else "post_close"


# What the briefing is *for* changes completely with the session. Before the
# bell it is a plan; during the session it is a read of what is actually moving;
# after the close it is what carries into tomorrow.
_PHASE_BRIEF = {
    "pre_open": (
        "The Indian market has NOT opened yet (NSE opens 09:15 IST). Write a "
        "PRE-OPEN briefing: what happened overnight in the US, Europe, Asia, "
        "crude, gold and the rupee, what it implies for the open, and which "
        "sectors or stocks are most likely to be in focus today."
    ),
    "open": (
        "The Indian market is OPEN right now. Write a MID-SESSION briefing: "
        "which news is actually moving the tape, what has changed since the "
        "open, and what to watch for the rest of the session."
    ),
    "post_close": (
        "The Indian market has CLOSED for the day. Write a POST-CLOSE briefing: "
        "what mattered today, and what carries into the next session."
    ),
}

_REGIONS = {"india", "global"}
_IMPACTS = {"high", "medium", "low"}

# Ceiling on "high" impact per cycle. These are the items the Alerts page raises
# a notification for, so the number has to stay small enough that seeing one
# means something.
_MAX_HIGH_IMPACT = 3

# International items the finished feed must carry. It is both the target the
# curation prompt is given and the floor _ensure_global enforces afterwards, so
# the two can't drift: asking for a "real mix" and separately enforcing some
# other number is how the Global tab ended up near-empty. Overnight US/Europe/
# Asia, central banks, crude, gold and the dollar set the Indian open, so four
# of fourteen is a reasonable share of an Indian desk's feed, not a courtesy.
_MIN_GLOBAL_SHARE = 2 / 7


def _min_global(limit: int) -> int:
    """The international floor, as a share of the feed rather than a fixed count.

    It was 4, justified as "four of fourteen is a reasonable share of an Indian
    desk's feed". That reasoning is about the *proportion*, so a fixed 4 quietly
    breaks the moment `limit` moves — at 24 items it would have meant 17% where
    the author intended 29%.
    """
    return max(1, round(limit * _MIN_GLOBAL_SHARE))

# How many raw hits the curation prompt carries. The gather step now returns
# ~80 (ten queries plus the Finnhub poll); sending them all put the request over
# the leading free tier's per-request budget and every call came back
# "413 Payload Too Large", which the fallback then papered over as a full but
# entirely un-ranked feed. Measured: 30 hits ≈ 2.6k tokens in, which the tier
# accepts.
_PROMPT_HITS = 30


def _interleave(raw: list[dict]) -> list[dict]:
    """Pick the prompt's hits one-for-one across the two regions.

    `raw` comes out of _gather in query order — all six Indian queries, then the
    four international ones, then Finnhub. A flat head slice of that is 30
    Indian hits and zero international ones, so the curator could never rank a
    global headline no matter what the prompt asked for.

    The ratio was 2:1 in India's favour on the assumption that the domestic
    queries dominate the pool. Measured, they do not — a typical cycle gathers
    ~26 Indian hits against ~38 international ones (four global queries plus the
    Finnhub wire), so 2:1 threw away roughly 28 international hits before the
    model saw any of them, and the Global tab ran near-empty. One-for-one lets
    the curator judge on merit; the feed still leans domestic because the prompt
    and the "why it matters to an Indian investor" framing say so, not because
    the sample was rigged before it got there.

    Whichever side runs out, the other fills the remaining slots — a quiet
    overnight session should not shrink the prompt.
    """
    india = [r for r in raw if r.get("region") != "global"]
    glob = [r for r in raw if r.get("region") == "global"]
    out: list[dict] = []
    i = g = 0
    while len(out) < _PROMPT_HITS and (i < len(india) or g < len(glob)):
        if i < len(india) and len(out) < _PROMPT_HITS:
            out.append(india[i]); i += 1
        if g < len(glob) and len(out) < _PROMPT_HITS:
            out.append(glob[g]); g += 1
    return out


def _curate(raw: list[dict], limit: int, phase: str) -> tuple[list[dict], dict | None]:
    """Rank + summarise headlines AND write the session briefing in ONE call.

    The model has already read every headline to rank them, so asking for the
    briefing in the same response costs nothing extra — a second call would
    have doubled this job's LLM spend for context it already had.

    Returns ([items], briefing|None). Either half can come back empty; the
    caller tops items up from the raw hits and treats a missing briefing as
    "no AI briefing right now" rather than an error.
    """
    from agent.llm_client import complete

    if not raw:
        return [], None

    pool = _interleave(raw)
    lines = "\n".join(
        f"{i+1}. [{r.get('region','india')}]{_age_tag(r.get('published'))} "
        f"{r['title']} | {r['snippet'][:120]}"
        for i, r in enumerate(pool)
    )
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
    prompt = (
        f"Today is {today}, {now_ist} IST. Below are numbered web search results "
        f"about financial markets — the tag in brackets is the region the search "
        f"targeted.\n\n{lines}\n\n"
        f"{_PHASE_BRIEF.get(phase, _PHASE_BRIEF['post_close'])}\n\n"
        f"Return ONLY this JSON object, no preamble:\n"
        f'{{"briefing":{{"headline":"<one sentence, the single most important thing>",'
        f'"points":["<3-5 short points, each a concrete takeaway tied to a headline above>"],'
        f'"watch":["<2-3 specific things to watch next>"]}},'
        f'"items":[{{"n":<the number of the result above>,'
        f'"why":"<max 15 words on why it matters to an Indian investor>","category":'
        f'"<Markets|Stocks|Macro|Policy|Global>","region":"<india|global>",'
        f'"impact":"<high|medium|low>","tickers":["<NSE symbol>"]}}]}}\n\n'
        f"Rules: write the briefing FIRST, then select the {limit} MOST "
        f"market-relevant, distinct, recent items. Cite each item by its number "
        f"`n` only — never write out a URL. You do NOT write headlines: the "
        f"publisher's own headline is used verbatim, so pick the row and explain "
        f"why it matters, nothing more. Prefer rows marked with a smaller age. "
        f"At least {_min_global(limit)} of the "
        f"{limit} must be region \"global\": overnight US/Europe/Asia moves, "
        f"central banks, crude, gold and the dollar set the Indian open, so "
        f"they are market news here too. Mark at most 3 items \"high\" "
        f"impact, and only for news that genuinely demands attention today "
        f"(policy decisions, large earnings surprises, sharp commodity/currency "
        f"moves, market-wide events). `tickers` may be empty; only list NSE "
        f"symbols the headline names."
    )

    def _post() -> str:
        # "quick": ranking pre-fetched snippets, short output, latency matters.
        return complete(_SYSTEM, prompt, task_shape="quick")

    valid_links = {r["link"] for r in raw if r.get("link")}
    region_by_link = {r["link"]: r.get("region", "india") for r in raw if r.get("link")}
    # The gathered row behind each link — the source of the headline and the
    # publication time, neither of which the model is trusted to supply.
    by_link = {r["link"]: r for r in raw if r.get("link")}

    def _blocks(text: str) -> list:
        """Every top-level JSON value we can salvage from the reply."""
        out = []
        for pat in (r"\{.*\}", r"\[.*\]"):
            m = re.search(pat, text, re.DOTALL)
            if m:
                try:
                    out.append(json.loads(m.group(0)))
                except Exception:
                    pass
        # Last resort: individual objects, for a reply truncated mid-array.
        for b in re.findall(r"\{[^{}]*\}", text, re.DOTALL):
            try:
                out.append(json.loads(b))
            except Exception:
                continue
        return out

    def _clean_brief(b) -> dict | None:
        if not isinstance(b, dict):
            return None
        head = str(b.get("headline", "")).strip()
        pts = [str(p).strip() for p in (b.get("points") or []) if str(p).strip()]
        watch = [str(w).strip() for w in (b.get("watch") or []) if str(w).strip()]
        # `points` is what makes this a briefing rather than a news item — an
        # item object also carries "headline", and the salvage path below feeds
        # every loose object through here.
        if not pts:
            return None
        return {"headline": head, "points": pts[:6], "watch": watch[:4], "phase": phase}

    def _link_for(it: dict) -> str:
        """Resolve an item's citation to a link we actually searched.

        Preferred form is `n`, the 1-based row number in the prompt: it costs
        two output tokens instead of twenty (the reply was hitting
        finish_reason=length and losing the tail of the list), and it cannot be
        hallucinated the way a written-out URL can. `source_url` stays supported
        for models that ignore the instruction and echo the link anyway.
        """
        n = it.get("n")
        if isinstance(n, (int, float)) or (isinstance(n, str) and n.strip().isdigit()):
            idx = int(n) - 1
            if 0 <= idx < len(pool):
                return pool[idx].get("link") or ""
            return ""
        url = str(it.get("source_url", "")).strip()
        if not url.startswith("http"):
            return ""
        if url in valid_links:
            return url
        # tolerate trailing-slash / query differences
        return next((v for v in valid_links if v.rstrip("/").split("?")[0]
                     == url.rstrip("/").split("?")[0]), "")

    def _words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}

    def _near_dupe(head: str, kept: list[str]) -> bool:
        """One story, two outlets, different wording.

        Link dedup cannot see this — the URLs genuinely differ — and neither can
        the exact-title dedup in _gather. It surfaced once international items
        got a fair share of the slots: "S&P 500 slid 1.52% to end the day at
        7,316.15" and "S&P 500 declined 1.52% to end the session at 7,316.15
        points" both made the same feed. The prompt asks for distinct items;
        this is what makes that binding.

        The threshold is measured, not guessed: that pair shares 4 of 6
        significant words (0.67), while headlines that genuinely differ score
        far lower — "Nifty holds above 24,350 as auto stocks lead" against
        "Sensex rises 166 points as auto stocks lead" is 0.43. 0.6 separates
        them, and also catches the other common shape, one policy line reworded
        ("RBI keeps repo rate unchanged" vs "RBI holds repo rate steady", 0.6).

        ponytail: O(n²) word-overlap over at most `limit` headlines. Fine at 14;
        reach for shingling or MinHash only if this ever ranks hundreds.
        """
        words = _words(head)
        if not words:
            return False
        for other in map(_words, kept):
            if other and len(words & other) / min(len(words), len(other)) >= 0.6:
                return True
        return False

    def _clean_items(rows) -> list[dict]:
        items = []
        seen: set[str] = set()
        for it in rows if isinstance(rows, list) else []:
            if not isinstance(it, dict):
                continue
            url = _link_for(it)
            # No groundable source -> drop it. Index citation also makes
            # duplicates possible in a way free-text URLs weren't, since the
            # model can name the same row twice.
            if not url or url in seen:
                continue
            src = by_link.get(url)
            if not src:
                continue
            # The publisher's headline, verbatim — the model no longer writes
            # one. It used to, and against a section front with nothing to
            # summarise it simply invented the specifics: "Sensex gains modestly
            # while Nifty declines in early trade" was composed for a page whose
            # real title is "Stock Market Today: Sensex, Nifty, BSE, NSE Latest
            # Updates". A made-up market claim is worse than no headline.
            head = src["title"]
            if _near_dupe(head, [i["title"] for i in items]):
                continue
            seen.add(url)
            region = str(it.get("region", "")).strip().lower()
            impact = str(it.get("impact", "")).strip().lower()
            tickers = [str(t).strip().upper() for t in (it.get("tickers") or [])
                       if str(t).strip()][:4]
            items.append({
                "title": head,
                "link": url,
                "snippet": str(it.get("why", "")).strip(),
                "source": str(it.get("category", "") or _domain(url)).strip(),
                # Fall back to the region of the query that found the link, not
                # to "india" — mislabelling a Fed headline as domestic is worse
                # than trusting the search that surfaced it.
                "region": region if region in _REGIONS else region_by_link.get(url, "india"),
                "impact": impact if impact in _IMPACTS else "low",
                "tickers": tickers,
                "published": src.get("published"),
            })
        # The prompt asks for at most three "high" items; nothing made that
        # binding, and a run that flags ten turns the Alerts page from "these
        # need your attention" into a second copy of the feed. Keep the first
        # three the curator ranked and demote the rest.
        over = [i for i in items if i["impact"] == "high"][_MAX_HIGH_IMPACT:]
        for i in over:
            i["impact"] = "medium"
        return items

    def _parse(text: str) -> tuple[list[dict], dict | None]:
        if not text:
            return [], None
        items: list[dict] = []
        brief: dict | None = None
        loose: list[dict] = []
        for b in _blocks(text):
            if isinstance(b, dict) and ("items" in b or "briefing" in b):
                items = items or _clean_items(b.get("items"))
                brief = brief or _clean_brief(b.get("briefing"))
            elif isinstance(b, list):
                items = items or _clean_items(b)
            elif isinstance(b, dict):
                loose.append(b)
        # Truncated reply (finish_reason=length): neither the wrapper object nor
        # the array closes, so nothing above parses and all we have are the
        # individual objects scraped out of the middle. The briefing is written
        # first and is therefore the part most likely to have survived intact —
        # recover it from there rather than throwing the whole reply away.
        if loose:
            if not items:
                items = _clean_items(loose)
            if not brief:
                brief = next((c for b in loose if (c := _clean_brief(b))), None)
        return items, brief

    # The free tiers are variable — one reply comes back with both halves, the
    # next drops the briefing or truncates the item list. Retry until we hold
    # both, keeping the best of each attempt rather than the last: the old loop
    # retried only on missing *items*, so a reply that produced the briefing and
    # then truncated was thrown away for one that had neither.
    best_items: list[dict] = []
    best_brief: dict | None = None
    for _ in range(2):
        items, brief = _parse(_post())
        best_items = best_items or items
        best_brief = best_brief or brief
        if best_items and best_brief:
            break
    return best_items[:limit], best_brief


def _global_count(items: list[dict]) -> int:
    return sum(1 for i in items if i.get("region") == "global")


def _as_item(r: dict) -> dict:
    """A raw search hit shaped like a curated item.

    Un-curated top-ups are never flagged high impact: nothing has judged them,
    and a false "needs your attention" alert is worse than a missed one.
    """
    return {"title": r["title"], "link": r["link"], "snippet": r["snippet"],
            "source": _domain(r["link"]), "region": r.get("region", "india"),
            "impact": "low", "tickers": [], "published": r.get("published")}


def _ensure_global(items: list[dict], raw: list[dict], limit: int) -> list[dict]:
    """Guarantee at least _min_global(limit) international items, without growing the
    list — the lowest-ranked domestic items give up their slots."""
    need = _min_global(limit) - _global_count(items)
    if need <= 0:
        return items
    seen = {i["link"] for i in items}
    extra = [_as_item(r) for r in raw
             if r.get("region") == "global" and r["link"] not in seen][:need]
    if not extra:
        return items
    keep = list(items)
    while len(keep) + len(extra) > limit:
        idx = next((n for n in range(len(keep) - 1, -1, -1)
                    if keep[n].get("region") != "global"), None)
        if idx is None:
            break
        keep.pop(idx)
    return keep + extra


def get_live_market_news(limit: int = 24) -> dict:
    """
    Live, LLM-curated Indian + international market news, plus a session-aware
    AI briefing (pre-open / mid-session / post-close).

    Returns:
        {"items": [{title, link, snippet, source, region, impact, tickers}],
         "briefing": {headline, points, watch, phase} | None,
         "phase": str, "ok": bool, "llm_used": bool, "degraded": bool,
         "generated_ist": iso, "count": int}
    Never caches an empty result (callers should not cache failures either).

    `limit` was 14, because every free tier in the chain shares one ~4k
    completion budget with its own reasoning tokens and a longer ranked list
    came back finish_reason=length — the briefing survived (it is written
    first) but most of the items were lost and silently replaced by unranked
    raw hits.

    That ceiling moved when the curator stopped writing headlines. Each item is
    now `{n, why, category, region, impact, tickers}` and the publisher's own
    headline is used verbatim, so the largest per-item output cost is gone.
    Measured against the live pipeline afterwards: limit=30 returned 25 ranked
    items with an intact briefing in 11.7s. 24 sits inside that with margin and
    matches the slice in web/app/api/news/route.ts, so nothing is fetched only
    to be clipped by the UI.

    Two ceilings remain above it. `_PROMPT_HITS` (30) is a hard cap on ranked
    items — the curator cannot rank a row it was never shown — and raising THAT
    is what previously produced 413 Payload Too Large on the leading tier.
    """
    phase = session_phase()
    raw = _gather()
    if not raw:
        return {"items": [], "briefing": None, "phase": phase, "ok": False,
                "llm_used": False,
                "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                "count": 0}

    curated, briefing = _curate(raw, limit, phase)
    llm_used = bool(curated)
    from_llm = len(curated)

    # Top up from the raw hits whenever curation came back short — not only when
    # it came back empty. A *partial* LLM reply (output truncated, or a mid-call
    # 429 on the leading rung) used to fall through this guard: it returned the
    # two items that happened to parse, with ok:true, and the API layer cached
    # that for 15 minutes. Two of eighteen looks exactly like a quiet news day.
    if from_llm < limit:
        seen = {i["link"] for i in curated}
        pending = [r for r in raw if r["link"] not in seen]

        # Reserve exactly the international shortfall, then fill the rest in
        # natural (query) order. Sorting the WHOLE queue global-first instead
        # filled an entirely empty feed with 14 international items the one time
        # curation failed outright — an Indian terminal showing no Indian
        # headlines. The floor is a minimum, not an ordering.
        need = min(max(0, _min_global(limit) - _global_count(curated)), limit - len(curated))
        for r in [x for x in pending if x.get("region") == "global"][:need]:
            curated.append(_as_item(r))
            seen.add(r["link"])

        for r in pending:
            if len(curated) >= limit:
                break
            if r["link"] in seen:
                continue
            curated.append(_as_item(r))

    # Full-length but all-India curation skips the block above entirely, so the
    # floor has to be enforced once more against the finished list.
    curated = _ensure_global(curated, raw, limit)

    return {
        "items": curated,
        "briefing": briefing,
        "phase": phase,
        "ok": bool(curated),
        "llm_used": llm_used,
        # True when the LLM produced fewer than we could have shown, so callers
        # (and the UI) can say the list is partly unranked rather than implying
        # every item was chosen for relevance.
        "degraded": from_llm < min(limit, len(raw)),
        "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
        "count": len(curated),
    }


__all__ = ["get_live_market_news", "session_phase"]
