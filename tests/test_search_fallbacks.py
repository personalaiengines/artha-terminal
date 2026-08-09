"""Gemini grounded-search fallback (services/search.py).

The only thing worth testing here is the guard that keeps a hallucinated news
feed out of the terminal: Gemini must never contribute a "search result" that
did not come from a page Google actually returned. Everything else in the rung
is an HTTP call.
"""

import pytest

from services.search import SearchService


def _grounded(chunks, supports=None, answer="Reliance rose. TCS fell."):
    """A minimal generateContent response shaped like a grounded reply."""
    return {
        "candidates": [{
            "content": {"parts": [{"text": answer}]},
            "groundingMetadata": {
                "groundingChunks": chunks,
                "groundingSupports": supports or [],
            },
        }]
    }


# --- the guard -------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {},                                                       # nothing at all
    {"candidates": []},                                       # no candidate
    {"candidates": [{"content": {"parts": [{"text": "Reliance hit an all-time high."}]}}]},
    _grounded([]),                                            # searched, found nothing
    {"candidates": [{"content": {"parts": [{"text": "x"}]}, "groundingMetadata": {}}]},
])
def test_ungrounded_answers_yield_nothing(payload):
    """No grounding metadata -> no results. The model's own prose is never
    passed off as a search result, however confident it sounds."""
    assert SearchService._parse_grounding(payload, limit=10) == []


def test_source_without_a_link_is_dropped():
    """A grounding chunk with a title but no uri is not a search result."""
    out = SearchService._parse_grounding(
        _grounded([{"web": {"title": "Mint"}}, {"web": {"uri": "https://x.test/a", "title": "ET"}}]),
        limit=10,
    )
    assert [r["link"] for r in out] == ["https://x.test/a"]


# --- normal parsing --------------------------------------------------------

def test_snippets_follow_the_citation_not_the_whole_answer():
    """Each link gets the sentences that actually cited it, so two sources do
    not end up sharing one undifferentiated blob of summary."""
    out = SearchService._parse_grounding(
        _grounded(
            chunks=[
                {"web": {"uri": "https://x.test/reliance", "title": "Mint"}},
                {"web": {"uri": "https://x.test/tcs", "title": "ET"}},
            ],
            supports=[
                {"segment": {"text": "Reliance rose."}, "groundingChunkIndices": [0]},
                {"segment": {"text": "TCS fell."}, "groundingChunkIndices": [1]},
            ],
        ),
        limit=10,
    )
    assert out == [
        {"title": "Mint", "link": "https://x.test/reliance", "snippet": "Reliance rose."},
        {"title": "ET", "link": "https://x.test/tcs", "snippet": "TCS fell."},
    ]


def test_offset_only_supports_slice_the_answer():
    """Payloads that carry byte offsets instead of segment text still resolve."""
    out = SearchService._parse_grounding(
        _grounded(
            chunks=[{"web": {"uri": "https://x.test/a", "title": "Mint"}}],
            supports=[{"segment": {"startIndex": 0, "endIndex": 13}, "groundingChunkIndices": [0]}],
            answer="Reliance rose. TCS fell.",
        ),
        limit=10,
    )
    assert out[0]["snippet"] == "Reliance rose"


def test_limit_is_honoured_and_title_falls_back_to_the_url():
    chunks = [{"web": {"uri": f"https://x.test/{i}"}} for i in range(5)]
    out = SearchService._parse_grounding(_grounded(chunks), limit=2)
    assert len(out) == 2
    assert out[0]["title"] == "https://x.test/0"   # no title -> show the link
    assert out[0]["snippet"] == ""                 # uncited source -> no invented snippet


def test_shape_matches_the_other_providers():
    """Callers (services/market_news.py, sector_news, stock_news) read
    title/link/snippet regardless of which provider answered."""
    out = SearchService._parse_grounding(
        _grounded([{"web": {"uri": "https://x.test/a", "title": "Mint"}}]), limit=1
    )
    assert set(out[0]) == {"title", "link", "snippet"}


# --- jina rung -------------------------------------------------------------

def test_jina_maps_to_the_same_shape():
    out = SearchService._parse_jina({
        "code": 200,
        "data": [{
            "title": "NIFTY 50 (^NSEI) Charts, Data & News",
            "url": "https://finance.yahoo.com/quote/%5ENSEI/",
            "description": "NIFTY 50 24,614.90 -159.40 (-0.64%)",
            "content": "…entire scraped page…",
        }],
    }, limit=10)
    assert out == [{
        "title": "NIFTY 50 (^NSEI) Charts, Data & News",
        "link": "https://finance.yahoo.com/quote/%5ENSEI/",
        "snippet": "NIFTY 50 24,614.90 -159.40 (-0.64%)",
    }]
    # `content` is the full page body — it must never leak into the snippet.
    assert "scraped page" not in out[0]["snippet"]


@pytest.mark.parametrize("payload", [{}, {"data": []}, {"data": None}, {"code": 402}])
def test_jina_empty_payloads_yield_nothing(payload):
    assert SearchService._parse_jina(payload, limit=10) == []


def test_jina_drops_results_without_a_url_and_honours_limit():
    out = SearchService._parse_jina({"data": [
        {"title": "no link"},
        {"url": "https://x.test/1"},
        {"url": "https://x.test/2"},
        {"url": "https://x.test/3"},
    ]}, limit=2)
    assert [r["link"] for r in out] == ["https://x.test/1", "https://x.test/2"]
    assert out[0]["title"] == "https://x.test/1"   # no title -> show the link
