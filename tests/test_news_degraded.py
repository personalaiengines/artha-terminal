"""
ARTHA Terminal — news curation must never ship a short list silently.

Regression: Groq 429'd mid-curation, `_curate` parsed 2 items out of a
truncated reply, and `get_live_market_news` returned those 2 with ok:true.
The API layer cached it for 15 minutes; 2 of 18 is indistinguishable from a
quiet news day. The old guard only fired when curation returned *nothing*.
"""

import collections
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.market_news import get_live_market_news

_RAW = [{"title": f"t{i}", "link": f"https://x.test/{i}", "snippet": f"s{i}",
         "region": "global" if i % 2 else "india"}
        for i in range(18)]


def _run(curated_count: int) -> dict:
    with patch("services.market_news._gather", return_value=_RAW), \
         patch("services.market_news.session_phase", return_value="open"), \
         patch("services.market_news._curate",
               side_effect=lambda raw, limit, phase: ([
                   {"title": r["title"], "link": r["link"],
                    "snippet": r["snippet"], "source": "x.test",
                    "region": r["region"], "impact": "low", "tickers": []}
                   for r in raw[:curated_count]], None)):
        return get_live_market_news(limit=18)


def test_partial_curation_is_topped_up_and_flagged():
    res = _run(2)
    assert res["count"] == 18, "short LLM reply must be topped up from raw hits"
    assert res["degraded"] is True
    assert len({i["link"] for i in res["items"]}) == 18, "top-up must not duplicate"


def test_empty_curation_still_falls_back():
    res = _run(0)
    assert res["count"] == 18
    assert res["llm_used"] is False
    assert res["degraded"] is True


def test_full_curation_is_not_flagged_degraded():
    res = _run(18)
    assert res["count"] == 18
    assert res["llm_used"] is True
    assert res["degraded"] is False


def test_international_coverage_is_guaranteed():
    """The News page has a Global tab and a Global Wire panel. Some cycles the
    curator returns an all-India list however plainly the prompt asks for a mix
    — the feed still has to carry international news."""
    raw = [{"title": f"i{n}", "link": f"https://in.test/{n}", "snippet": "s",
            "region": "india"} for n in range(10)]
    raw += [{"title": f"g{n}", "link": f"https://gl.test/{n}", "snippet": "s",
             "region": "global"} for n in range(5)]
    all_india = [{"title": r["title"], "link": r["link"], "snippet": "s",
                  "source": "x", "region": "india", "impact": "low", "tickers": []}
                 for r in raw[:10]]

    with patch("services.market_news._gather", return_value=raw), \
         patch("services.market_news.session_phase", return_value="open"), \
         patch("services.market_news._curate", return_value=(all_india, None)):
        res = get_live_market_news(limit=10)

    assert res["count"] == 10, "the floor must not grow the feed past its limit"
    # Tracks the constant rather than restating it — the floor is also the
    # target the curation prompt is given, so the two move together.
    assert sum(1 for i in res["items"] if i["region"] == "global") == mn._MIN_GLOBAL
    assert len({i["link"] for i in res["items"]}) == 10


def test_total_curation_failure_still_leads_with_indian_news():
    """The international floor is a minimum, not an ordering. Reserving the
    shortfall is right; sorting the whole top-up queue global-first filled an
    empty feed with 14 international items — an Indian terminal with no Indian
    headlines on it."""
    raw = [{"title": f"i{n}", "link": f"https://in.test/{n}", "snippet": "s",
            "region": "india"} for n in range(20)]
    raw += [{"title": f"g{n}", "link": f"https://gl.test/{n}", "snippet": "s",
             "region": "global"} for n in range(20)]

    with patch("services.market_news._gather", return_value=raw), \
         patch("services.market_news.session_phase", return_value="open"), \
         patch("services.market_news._curate", return_value=([], None)):
        res = get_live_market_news(limit=14)

    counts = collections.Counter(i["region"] for i in res["items"])
    assert counts["global"] == mn._MIN_GLOBAL, "exactly the shortfall, no more"
    assert counts["india"] == 14 - mn._MIN_GLOBAL
    assert len({i["link"] for i in res["items"]}) == 14


def test_topped_up_items_keep_region_and_never_claim_high_impact():
    """A top-up item has been judged by nothing, so it must not be able to
    raise a "needs your attention" alert — and it must keep the region of the
    query that found it, or a Fed headline lands on the India tab."""
    res = _run(2)
    assert {i["impact"] for i in res["items"][2:]} == {"low"}
    assert {i["region"] for i in res["items"]} == {"india", "global"}


# --- only real publishers reach the feed ----------------------------------
import services.market_news as mn  # noqa: E402


def test_social_links_never_become_news_sources():
    """Search engines rank Instagram/YouTube posts for these queries, and a card
    bylined "Instagram" over a Fed headline is not a source anyone can check."""
    with patch.object(mn, "_search", side_effect=lambda q, limit=6: [
            {"title": "Dow tumbles", "link": "https://www.instagram.com/p/abc", "snippet": ""},
            {"title": "Fed holds", "link": "https://youtube.com/watch?v=1", "snippet": ""},
            {"title": "Nifty ends higher", "link": "https://www.moneycontrol.com/n/1", "snippet": ""},
         ] if q == mn._QUERIES[0][0] else []), \
         patch("services.finnhub_news.get_finnhub_general_news", return_value=[]):
        links = [r["link"] for r in mn._gather()]
    assert links == ["https://www.moneycontrol.com/n/1"]
    # Subdomains of a blocked host are blocked; a lookalike host is not.
    assert mn._is_publisher("https://m.facebook.com/x") is False
    assert mn._is_publisher("https://notx.com/x") is True
    assert mn._is_publisher("") is False


def _phase(state: str, note: str, hhmm: tuple[int, int]) -> str:
    from datetime import datetime as _dt, time as _t
    from zoneinfo import ZoneInfo
    fake = _dt(2026, 8, 3, *hhmm, tzinfo=ZoneInfo("Asia/Kolkata"))

    class _Clock(_dt):
        @classmethod
        def now(cls, tz=None):
            return fake

    with patch("services.global_markets.market_status",
               return_value={"state": state, "note": note, "local_time": ""}), \
         patch.object(mn, "datetime", _Clock):
        return mn.session_phase()


def test_session_phase_reads_the_exchange_calendar():
    assert _phase("open", "closes 15:30 IST", (11, 0)) == "open"
    # Shut, and the calendar says the next open is TODAY -> pre-open window.
    assert _phase("closed", "opens 09:15 IST", (8, 0)) == "pre_open"
    assert _phase("closed", "opens 09:15 IST", (16, 0)) == "post_close"
    # Holiday/weekend: global_markets emits a dated note, never a clock time,
    # so 08:00 on a non-session day must not read as "pre-open".
    assert _phase("closed", "opens Mon 04 Aug", (8, 0)) == "post_close"


# --- curation parser: items + briefing out of one reply -------------------
from services.market_news import _curate  # noqa: E402

_CURATE_RAW = [
    {"title": "RBI holds repo", "link": "https://x.test/1", "snippet": "s", "region": "india"},
    {"title": "Fed cuts", "link": "https://x.test/2", "snippet": "s", "region": "global"},
]

_REPLY = """Here you go:
{"briefing": {"headline": "Rates in focus", "points": ["p1", "p2"], "watch": ["w1"]},
 "items": [
   {"n": 1, "headline": "RBI holds repo", "why": "policy",
    "category": "Macro", "region": "india", "impact": "high", "tickers": ["hdfcbank"]},
   {"n": 2, "headline": "Fed cuts", "why": "global",
    "category": "Global", "region": "global", "impact": "banana"},
   {"n": 1, "headline": "RBI holds repo (again)", "why": "dup",
    "category": "Macro", "region": "india", "impact": "high"},
   {"n": 99, "headline": "Off the end", "why": "x", "category": "Markets"},
   {"headline": "Invented", "why": "x", "source_url": "https://evil.test/9",
    "category": "Markets", "region": "india", "impact": "high"}
 ]}"""


def _curated(reply: str):
    with patch("services.market_news.complete", create=True, return_value=reply), \
         patch("agent.llm_client.complete", return_value=reply):
        return _curate(_CURATE_RAW, 10, "pre_open")


def test_curate_parses_briefing_and_items_from_one_reply():
    items, brief = _curated(_REPLY)
    assert brief == {"headline": "Rates in focus", "points": ["p1", "p2"],
                     "watch": ["w1"], "phase": "pre_open"}
    # n=1 and n=2 resolve to real rows; the repeat of n=1, the out-of-range
    # n=99 and the invented URL all drop.
    assert [i["link"] for i in items] == ["https://x.test/1", "https://x.test/2"]
    assert items[0]["impact"] == "high" and items[0]["tickers"] == ["HDFCBANK"]
    assert items[1]["impact"] == "low", "an unknown impact value must not pass through"


def test_curate_still_reads_a_bare_array_reply():
    """Older/smaller models drop the wrapper object and emit just the array,
    and echo the URL instead of the row number. Both must still parse."""
    items, brief = _curated(
        '[{"headline":"RBI holds repo","why":"policy","source_url":"https://x.test/1",'
        '"category":"Macro"}]')
    assert brief is None
    assert len(items) == 1
    # No region in the reply -> fall back to the region of the query that found
    # the link, not to a hardcoded "india".
    assert items[0]["region"] == "india"


def test_same_story_from_two_outlets_appears_once():
    """Real pair from a live cycle. Different URLs and different wording, so
    neither the link dedup nor the exact-title dedup catches it."""
    raw = [
        {"title": "a", "link": "https://a.test/1", "snippet": "s", "region": "global"},
        {"title": "b", "link": "https://b.test/1", "snippet": "s", "region": "global"},
        {"title": "c", "link": "https://c.test/1", "snippet": "s", "region": "india"},
    ]
    reply = json.dumps({"items": [
        {"n": 1, "headline": "S&P 500 slid 1.52% to end the day at 7,316.15"},
        {"n": 2, "headline": "S&P 500 declined 1.52% to end the session at 7,316.15 points"},
        {"n": 3, "headline": "Nifty holds above 24,350 as auto stocks lead"},
    ]})
    with patch("agent.llm_client.complete", return_value=reply):
        items, _ = _curate(raw, 10, "open")
    # `n` indexes the interleaved prompt list, not `raw`, so assert on the
    # headlines: the first S&P line survives, the reworded one is dropped.
    assert [i["title"] for i in items] == [
        "S&P 500 slid 1.52% to end the day at 7,316.15",
        "Nifty holds above 24,350 as auto stocks lead",
    ]


def test_distinct_stories_are_not_collapsed():
    """The other half of the dedup: two real, different headlines that share a
    trailing clause must both survive. A too-eager threshold silently thins the
    feed, which is harder to notice than a duplicate."""
    raw = [{"title": t, "link": f"https://x.test/{n}", "snippet": "s", "region": "india"}
           for n, t in enumerate(["a", "b"])]
    reply = json.dumps({"items": [
        {"n": 1, "headline": "Nifty holds above 24,350 as auto stocks lead"},
        {"n": 2, "headline": "Sensex rises 166 points as auto stocks lead"},
    ]})
    with patch("agent.llm_client.complete", return_value=reply):
        items, _ = _curate(raw, 10, "open")
    assert len(items) == 2


def test_high_impact_is_capped():
    """Only high-impact items raise an Alerts notification, so an over-eager
    run must not turn that page into a second copy of the feed."""
    rows = ",".join(
        f'{{"n": {n}, "headline": "h{n}", "why": "w", "impact": "high"}}'
        for n in (1, 2, 3, 4, 5))
    raw = [{"title": f"t{n}", "link": f"https://x.test/{n}", "snippet": "s", "region": "india"}
           for n in range(1, 6)]
    with patch("agent.llm_client.complete", return_value=f'{{"items": [{rows}]}}'):
        items, _ = _curate(raw, 10, "open")
    assert [i["impact"] for i in items] == ["high", "high", "high", "medium", "medium"]


def test_briefing_survives_a_truncated_reply():
    """finish_reason=length: the wrapper object never closes, so neither it nor
    the item array parses. The briefing is written first, so it is intact in the
    middle of the text — losing it there is what made the whole feature flaky."""
    items, brief = _curated(
        '{"briefing": {"headline": "Rates in focus", "points": ["p1"], "watch": []},\n'
        ' "items": [\n'
        '   {"n": 2, "headline": "Fed cuts", "why": "global", "category": "Global"},\n'
        '   {"n": 1, "headline": "RBI ho')
    assert brief is not None and brief["points"] == ["p1"]
    assert [i["link"] for i in items] == ["https://x.test/2"]
