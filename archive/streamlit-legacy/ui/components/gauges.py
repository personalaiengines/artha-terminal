"""
ARTHA Terminal - Gauge Components
Score gauge, sub-score bars, and percentile visualizations.
"""

import plotly.graph_objects as go
from typing import List, Optional

from ui.theme import PALETTE, RGB


def score_gauge(
    score: float,
    title: str = "Analysis Score",
    height: int = 350,
) -> go.Figure:
    """
    Build a radial gauge for the 0-10 analysis score.

    Args:
        score: Score value (0-10)
        title: Gauge title
        height: Chart height

    Returns:
        Plotly Figure with a radial gauge
    """
    # Color based on score
    if score >= 8:
        color = PALETTE["surge"]
        rating = "Strong"
    elif score >= 6.5:
        color = PALETTE["surge"]
        rating = "Favorable"
    elif score >= 5:
        color = PALETTE["volt"]
        rating = "Neutral"
    elif score >= 3.5:
        color = PALETTE["flare"]
        rating = "Cautious"
    else:
        color = PALETTE["flare"]
        rating = "Weak"

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number=dict(
            font=dict(color=color, size=48, family="JetBrains Mono"),
            suffix="",
        ),
        title=dict(
            text=f"{title}<br><span style='color:{color};font-size:14px'>{rating}</span>",
            font=dict(color=PALETTE["frost"], size=16),
        ),
        gauge={
            "axis": {
                "range": [0, 10],
                "tickcolor": PALETTE["haze"],
                "tickfont": dict(color=PALETTE["haze"], size=10),
                "tickwidth": 1,
            },
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": PALETTE["abyss"],
            "borderwidth": 2,
            "bordercolor": PALETTE["grid"],
            "steps": [
                {"range": [0, 3.5], "color": f"rgba({RGB['flare']}, 0.10)"},
                {"range": [3.5, 5], "color": f"rgba({RGB['volt']}, 0.10)"},
                {"range": [5, 6.5], "color": f"rgba({RGB['volt']}, 0.10)"},
                {"range": [6.5, 8], "color": f"rgba({RGB['surge']}, 0.10)"},
                {"range": [8, 10], "color": f"rgba({RGB['surge']}, 0.20)"},
            ],
            "threshold": {
                "line": {"color": PALETTE["frost"], "width": 2},
                "thickness": 0.8,
                "value": score,
            },
        },
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig


def subscore_bars(
    sub_scores: List[dict],
    height: int = 300,
) -> go.Figure:
    """
    Build a horizontal bar chart of sub-scores.

    Args:
        sub_scores: List of dicts with name, weight, score
    """
    if not sub_scores:
        fig = go.Figure()
        fig.update_layout(height=height)
        return fig

    names = [f"{s['name']}<br>({int(s['weight']*100)}%)" for s in sub_scores]
    scores = [s["score"] for s in sub_scores]

    # Color each bar by score
    colors = []
    for sc in scores:
        if sc >= 7:
            colors.append(PALETTE["surge"])
        elif sc >= 5:
            colors.append(PALETTE["volt"])
        else:
            colors.append(PALETTE["flare"])

    fig = go.Figure(go.Bar(
        x=scores,
        y=names,
        orientation="h",
        marker_color=colors,
        text=[f"{s['score']:.1f}" for s in sub_scores],
        textposition="outside",
        textfont=dict(color=PALETTE["frost"], size=12),
        xaxis="x",
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PALETTE["haze"]),
        height=height,
        margin=dict(l=20, r=60, t=20, b=20),
        xaxis=dict(
            range=[0, 10],
            gridcolor=PALETTE["grid"],
            tickfont=dict(color=PALETTE["haze"]),
        ),
        yaxis=dict(
            gridcolor=PALETTE["grid"],
            tickfont=dict(color=PALETTE["frost"]),
        ),
        showlegend=False,
    )

    return fig


def percentile_gauge(
    percentile: float,
    label: str = "Price Percentile (5Y)",
    height: int = 120,
    inverted: bool = False,
) -> go.Figure:
    """
    Build a small horizontal gauge for percentile display.

    Args:
        percentile: Value 0-100
        label: Label text
        inverted: If True, low percentile is "good" (e.g., for valuation)
    """
    if inverted:
        color = PALETTE["surge"] if percentile < 40 else (
            PALETTE["volt"] if percentile < 70 else PALETTE["flare"]
        )
    else:
        color = PALETTE["surge"] if percentile > 60 else (
            PALETTE["volt"] if percentile > 40 else PALETTE["flare"]
        )

    fig = go.Figure(go.Bar(
        x=[percentile],
        y=[label],
        orientation="h",
        marker_color=color,
        text=[f"{percentile:.0f}th"],
        textposition="outside",
        textfont=dict(color=PALETTE["frost"]),
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PALETTE["haze"]),
        height=height,
        margin=dict(l=20, r=50, t=10, b=10),
        xaxis=dict(
            range=[0, 100],
            showgrid=False,
            showticklabels=False,
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(color=PALETTE["frost"]),
        ),
        showlegend=False,
    )

    # Add background track
    fig.add_shape(
        type="rect",
        x0=0, x1=100,
        y0=-0.4, y1=0.4,
        line=dict(width=0),
        fillcolor=f"rgba({RGB['grid']}, 0.40)",
        layer="below",
    )

    return fig


def concentration_bar(
    positions: List[dict],
    title: str = "Position Concentration",
    height: int = 250,
) -> go.Figure:
    """
    Bar chart showing portfolio position weights.

    Args:
        positions: List of dicts with symbol, weight_pct
    """
    if not positions:
        fig = go.Figure()
        fig.update_layout(height=height)
        return fig

    symbols = [p["symbol"] for p in positions]
    weights = [p["weight_pct"] for p in positions]

    # Color the largest position with warning if > 25%
    colors = [
        PALETTE["volt"] if w > 25 else PALETTE["laser"]
        for w in weights
    ]

    fig = go.Figure(go.Bar(
        x=symbols,
        y=weights,
        marker_color=colors,
        text=[f"{w:.1f}%" for w in weights],
        textposition="outside",
        textfont=dict(color=PALETTE["frost"]),
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PALETTE["haze"]),
        title=dict(text=title, font=dict(color=PALETTE["frost"], size=14)),
        height=height,
        margin=dict(l=20, r=20, t=40, b=40),
        xaxis=dict(
            gridcolor=PALETTE["grid"],
            tickfont=dict(color=PALETTE["frost"], size=10),
            tickangle=-45,
        ),
        yaxis=dict(
            title="% of Portfolio",
            gridcolor=PALETTE["grid"],
            tickfont=dict(color=PALETTE["haze"]),
        ),
        showlegend=False,
    )

    # Add 25% concentration threshold line
    fig.add_hline(
        y=25,
        line_dash="dash",
        line_color=PALETTE["volt"],
        annotation_text="25% threshold",
        annotation_font_color=PALETTE["volt"],
    )

    return fig


__all__ = [
    "score_gauge",
    "subscore_bars",
    "percentile_gauge",
    "concentration_bar",
]