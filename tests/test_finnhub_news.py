"""
ARTHA Terminal - Finnhub general news tests

Finnhub's free tier is REST-only for news (no WS news channel — see the
module docstring in services/finnhub_news.py for why this isn't a WebSocket
client). Covers: no key -> empty list, malformed items skipped, well-formed
items mapped into the {title, link, snippet, source} shape _gather() expects.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from services.finnhub_news import get_finnhub_general_news


def test_no_key_returns_empty_list():
    config.search.finnhub_api_key = None
    assert get_finnhub_general_news() == []


def test_maps_and_skips_malformed_items():
    config.search.finnhub_api_key = "fh-key"
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = [
        {"headline": "Nifty hits record high", "url": "https://example.com/a", "summary": "why it matters"},
        {"headline": "", "url": "https://example.com/b"},  # missing headline -> skipped
        {"headline": "No URL here"},  # missing url -> skipped
    ]
    with patch("httpx.get", return_value=resp) as mock_get:
        items = get_finnhub_general_news()

    assert mock_get.call_args.kwargs["params"]["token"] == "fh-key"
    assert len(items) == 1
    assert items[0] == {
        "title": "Nifty hits record high",
        "link": "https://example.com/a",
        "snippet": "why it matters",
        "source": "finnhub",
        # No `datetime` on this fixture item -> undated, not a fabricated "now".
        "published": None,
    }


def test_finnhub_datetime_becomes_an_iso_timestamp():
    """Finnhub stamps every item with unix seconds and it used to be discarded,
    which is why the feed could not tell a two-hour-old wire story from a
    nine-year-old one."""
    config.search.finnhub_api_key = "fh-key"
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = [
        {"headline": "Fed holds", "url": "https://example.com/a",
         "datetime": 1786000000},                                    # real stamp
        {"headline": "Bad stamp", "url": "https://example.com/b", "datetime": 0},
        {"headline": "Junk stamp", "url": "https://example.com/c", "datetime": "yesterday"},
    ]
    with patch("httpx.get", return_value=resp):
        items = get_finnhub_general_news()

    assert items[0]["published"] == "2026-08-06T07:06:40+00:00"
    # A stamp that is absent, zero or non-numeric is "unknown", never epoch 0 —
    # 1970 would look like the oldest news on earth and sort accordingly.
    assert items[1]["published"] is None
    assert items[2]["published"] is None


def test_non_200_returns_empty_list():
    config.search.finnhub_api_key = "fh-key"
    resp = MagicMock()
    resp.status_code = 500
    with patch("httpx.get", return_value=resp):
        assert get_finnhub_general_news() == []
