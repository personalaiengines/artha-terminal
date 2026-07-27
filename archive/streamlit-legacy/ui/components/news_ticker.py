"""
ARTHA Terminal - News Ticker Component
Live news feed with timestamp chips.
"""

import streamlit as st
from datetime import datetime
from typing import List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.theme import PALETTE


def render_news_item(news_item: dict, index: int) -> None:
    """Render a single news item with timestamp chip."""
    title = news_item.get("title", "No title")
    link = news_item.get("link", "")
    snippet = news_item.get("snippet", "")
    source = news_item.get("source", "Unknown")
    published = news_item.get("published", "")

    # Time chip
    time_chip = ""
    if published:
        try:
            if isinstance(published, str):
                dt = datetime.fromisoformat(published.replace("Z", ""))
            else:
                dt = published
            time_chip = dt.strftime("%H:%M")
        except Exception:
            time_chip = str(published)[:5]

    with st.container():
        cols = st.columns([1, 8])
        with cols[0]:
            st.markdown(
                f"<div style='color:{PALETTE['volt']}; "
                f"font-family:JetBrains Mono; font-size:0.7rem; "
                f"text-align:right; padding-top:0.3rem;'>{time_chip}</div>",
                unsafe_allow_html=True,
            )
        with cols[1]:
            if link:
                st.markdown(
                    f"<a href='{link}' target='_blank' "
                    f"style='color:{PALETTE['frost']}; text-decoration:none; "
                    f"font-weight:500;'>📰 {title}</a>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"📰 {title}")

            if snippet:
                st.markdown(
                    f"<div style='color:{PALETTE['haze']}; "
                    f"font-size:0.8rem; margin-top:0.25rem;'>{snippet[:150]}...</div>",
                    unsafe_allow_html=True,
                )

            st.markdown(
                f"<div style='color:{PALETTE['haze']}; font-size:0.65rem; "
                f"margin-top:0.25rem;'>Source: {source}</div>",
                unsafe_allow_html=True,
            )


def render_news_feed(
    news_items: List[dict],
    title: str = "Live News",
    empty_message: str = "No news available",
) -> None:
    """
    Render a scrollable news feed.

    Args:
        news_items: List of news dicts with title, link, snippet, source, published
        title: Feed heading
        empty_message: Message shown when no news
    """
    st.markdown(f"#### {title}")

    if not news_items:
        st.markdown(
            f"<div style='color:{PALETTE['haze']}; "
            f"text-align:center; padding:2rem;'>{empty_message}</div>",
            unsafe_allow_html=True,
        )
        return

    for i, item in enumerate(news_items):
        render_news_item(item, i)
        if i < len(news_items) - 1:
            st.markdown(
                f"<div style='border-top:1px solid {PALETTE['grid']}; "
                f"margin:0.5rem 0;'></div>",
                unsafe_allow_html=True,
            )


def render_headline_ticker(news_items: List[dict]) -> None:
    """Render a compact horizontal scrolling ticker of headlines."""
    if not news_items:
        return

    headlines = "  •  ".join(
        f"📰 {n.get('title', '')[:60]}" for n in news_items[:8]
    )

    st.markdown(f"""
    <div style="
        background: {PALETTE['depth']};
        border: 1px solid {PALETTE['grid']};
        border-radius: 8px;
        padding: 0.75rem;
        margin-bottom: 1rem;
        overflow: hidden;
        white-space: nowrap;
        position: relative;
    ">
        <div style="
            display: inline-block;
            animation: tickerScroll 60s linear infinite;
            color: {PALETTE['frost']};
            font-size: 0.85rem;
            font-family: 'Inter', sans-serif;
        ">{headlines}</div>
    </div>
    <style>
    @keyframes tickerScroll {{
        0% {{ transform: translateX(100%); }}
        100% {{ transform: translateX(-100%); }}
    }}
    @media (prefers-reduced-motion: reduce) {{
        animation: none !important;
    }}
    </style>
    """, unsafe_allow_html=True)


__all__ = [
    "render_news_feed",
    "render_headline_ticker",
    "render_news_item",
]