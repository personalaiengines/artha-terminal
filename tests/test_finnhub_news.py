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
    }


def test_non_200_returns_empty_list():
    config.search.finnhub_api_key = "fh-key"
    resp = MagicMock()
    resp.status_code = 500
    with patch("httpx.get", return_value=resp):
        assert get_finnhub_general_news() == []
