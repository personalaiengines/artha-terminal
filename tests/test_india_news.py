"""India RSS source: parsing and round-robin, no network."""

import services.india_news as N


FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Nifty ends higher</title><link>https://x.com/a</link>
      <description>&lt;p&gt;Banks &lt;b&gt;led&lt;/b&gt; gains&lt;/p&gt;</description></item>
<item><title>No link here</title><description>d</description></item>
<item><title>Rupee steady</title><link>https://x.com/b</link></item>
</channel></rss>"""


def test_parses_and_strips_html(monkeypatch):
    monkeypatch.setattr(N.httpx, "get", lambda *a, **k: type(
        "R", (), {"status_code": 200, "content": FEED.encode()})())
    out = N._one("u", 10)
    assert [i["title"] for i in out] == ["Nifty ends higher", "Rupee steady"]  # linkless dropped
    assert "<" not in out[0]["snippet"] and "Banks" in out[0]["snippet"]


def test_bad_feed_is_not_fatal(monkeypatch):
    monkeypatch.setattr(N.httpx, "get", lambda *a, **k: type(
        "R", (), {"status_code": 200, "content": b"not xml"})())
    assert N._one("u", 10) == []


def test_round_robins_publishers(monkeypatch):
    feeds = {"a": [{"t": 1}, {"t": 2}, {"t": 3}], "b": [{"t": 4}], "c": []}
    monkeypatch.setattr(N, "_FEEDS", list(feeds))
    monkeypatch.setattr(N, "_one", lambda u, n: feeds[u])
    # one from each publisher before a second from any, empties skipped
    assert N.get_india_market_news() == [{"t": 1}, {"t": 4}, {"t": 2}, {"t": 3}]
