"""
ARTHA Terminal - Chart Components
Plotly-based chart helpers with cyberpunk styling.
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from pathlib import Path
from typing import Optional, List, Tuple

from ui.theme import PALETTE, RGB

# A whisper of a grid, not a cage — haze at low opacity reads premium.
_GRID = f"rgba({RGB['haze']}, 0.10)"
_AXIS_LINE = f"rgba({RGB['haze']}, 0.22)"


def _base_layout(
    title: str = "",
    height: int = 400,
    show_legend: bool = True,
) -> go.Layout:
    """
    Base Plotly layout — premium cyberpunk theme.

    The plot area is transparent so the panel background (depth) shows through
    for a clean, layered look; the grid is a faint recessive mesh; hovering
    draws a neon crosshair spike. Applies to every chart via this one function.
    """
    return go.Layout(
        title=dict(
            text=title,
            font=dict(color=PALETTE["frost"], size=15, family="Inter, sans-serif"),
            x=0.012, xanchor="left", y=0.97,
        ),
        paper_bgcolor=PALETTE["depth"],
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PALETTE["haze"], family="JetBrains Mono, monospace", size=12),
        margin=dict(l=24, r=24, t=48 if title else 20, b=24),
        height=height,
        showlegend=show_legend,
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=PALETTE["haze"], size=11),
            orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1,
        ),
        hovermode="closest",
        modebar=dict(
            bgcolor="rgba(0,0,0,0)",
            color=PALETTE["haze"],
            activecolor=PALETTE["laser"],
        ),
        xaxis=dict(
            gridcolor=_GRID,
            zeroline=False,
            showline=True, linecolor=_AXIS_LINE, linewidth=1,
            tickfont=dict(color=PALETTE["haze"], size=11),
            showspikes=True, spikecolor=PALETTE["laser"], spikethickness=1,
            spikedash="dot", spikemode="across", spikesnap="cursor",
        ),
        yaxis=dict(
            gridcolor=_GRID,
            zeroline=False,
            showline=False,
            tickfont=dict(color=PALETTE["haze"], size=11),
        ),
        hoverlabel=dict(
            bgcolor=PALETTE["depth"],
            bordercolor=PALETTE["laser"],
            font=dict(color=PALETTE["frost"], family="JetBrains Mono, monospace"),
        ),
    )


def candlestick_chart(
    df: pd.DataFrame,
    title: str = "Price Action",
    show_dma: bool = True,
    dma_50_col: str = "dma_50",
    dma_200_col: str = "dma_200",
    height: int = 500,
) -> go.Figure:
    """
    Build a candlestick chart with optional DMAs.

    Args:
        df: DataFrame with columns date, open, high, low, close, volume
        show_dma: Whether to overlay 50/200 DMAs
        dma_50_col, dma_200_col: Column names for DMAs (if precomputed)
        height: Chart height in px

    Returns:
        Plotly Figure
    """
    if df is None or df.empty:
        fig = go.Figure()
        fig.update_layout(_base_layout(title, height))
        fig.add_annotation(
            text="No price data available",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False,
            font=dict(color=PALETTE["haze"], size=14),
        )
        return fig

    # Precompute DMAs if not present
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if show_dma and dma_50_col not in df.columns:
        df["dma_50"] = df["close"].rolling(window=50).mean()
    if show_dma and dma_200_col not in df.columns:
        df["dma_200"] = df["close"].rolling(window=200).mean()

    fig = go.Figure()

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=df["date"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="Price",
        increasing_line_color=PALETTE["surge"],
        decreasing_line_color=PALETTE["flare"],
        line_width=1,
    ))

    # DMAs
    if show_dma:
        if "dma_50" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["dma_50"],
                mode="lines",
                name="50 DMA",
                line=dict(color=PALETTE["volt"], width=1.5),
            ))
        if "dma_200" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["dma_200"],
                mode="lines",
                name="200 DMA",
                line=dict(color=PALETTE["laser"], width=1.5),
            ))

    fig.update_layout(_base_layout(title, height))
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


def returns_bar_chart(
    returns: dict,
    title: str = "Returns Analysis",
    height: int = 350,
) -> go.Figure:
    """
    Build a bar chart of returns across timeframes.

    Args:
        returns: Dict like {'1D': 1.2, '1W': 3.1, '1M': -2.4, ...}
    """
    all_tfs = ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"]
    # Keep only timeframes that actually have a value (None => not enough history).
    pairs = [(tf, returns.get(f"return_{tf.lower()}")) for tf in all_tfs]
    pairs = [(tf, v) for tf, v in pairs if v is not None]
    timeframes = [tf for tf, _ in pairs]
    values = [v for _, v in pairs]

    colors = [
        PALETTE["surge"] if v >= 0 else PALETTE["flare"]
        for v in values
    ]

    fig = go.Figure(go.Bar(
        x=timeframes,
        y=values,
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in values],
        textposition="outside",
        textfont=dict(color=PALETTE["frost"]),
    ))

    fig.update_layout(_base_layout(title, height))
    return fig


def ownership_stacked_area(
    ownership_df: pd.DataFrame,
    title: str = "Shareholding Pattern (8Q)",
    height: int = 350,
) -> go.Figure:
    """
    Build a stacked area chart of quarterly ownership.

    Args:
        ownership_df: DataFrame with columns quarter, promoter, fii, dii, public
    """
    if ownership_df is None or ownership_df.empty:
        fig = go.Figure()
        fig.update_layout(_base_layout(title, height))
        return fig

    fig = go.Figure()
    categories = [
        ("promoter_share", "Promoter", PALETTE["laser"]),
        ("fitl_share", "FII", PALETTE["surge"]),
        ("ditl_share", "DII", PALETTE["volt"]),
        ("public_share", "Public", PALETTE["haze"]),
    ]

    for col, name, color in categories:
        if col in ownership_df.columns:
            fig.add_trace(go.Scatter(
                x=ownership_df["quarter"],
                y=ownership_df[col],
                mode="lines",
                stackgroup="share",
                name=name,
                line=dict(width=0.5, color=color),
                fillcolor=color,
            ))

    fig.update_layout(_base_layout(title, height))
    fig.update_layout(yaxis_range=(0, 100))
    return fig


def peers_comparison_bar(
    peers_df: pd.DataFrame,
    metric: str = "return_6m",
    metric_label: str = "6M Return (%)",
    highlight: str = None,
    title: str = "Peer Comparison",
    height: int = 400,
) -> go.Figure:
    """
    Build a horizontal bar chart comparing peers.

    Args:
        peers_df: DataFrame with columns symbol, metric
        metric: Column name to compare
        highlight: Symbol to highlight (the stock being analyzed)
    """
    if peers_df is None or peers_df.empty:
        fig = go.Figure()
        fig.update_layout(_base_layout(title, height))
        return fig

    df = peers_df.sort_values(metric, ascending=True)

    colors = [
        PALETTE["laser"] if s == highlight else
        (PALETTE["surge"] if v >= 0 else PALETTE["flare"])
        for s, v in zip(df["symbol"], df[metric])
    ]

    fig = go.Figure(go.Bar(
        x=df[metric],
        y=df["symbol"],
        orientation="h",
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in df[metric]],
        textposition="outside",
        textfont=dict(color=PALETTE["frost"]),
    ))

    fig.update_layout(_base_layout(title, height))
    fig.update_layout(yaxis=dict(autorange="reversed"))
    return fig


def allocation_wheel(
    holdings_df: pd.DataFrame,
    title: str = "Portfolio Allocation",
    height: int = 450,
) -> go.Figure:
    """
    Build a donut/pie chart for portfolio allocation.

    Args:
        holdings_df: DataFrame with columns symbol, current_value
    """
    if holdings_df is None or holdings_df.empty:
        fig = go.Figure()
        fig.update_layout(_base_layout(title, height))
        return fig

    # Categorical palette — matches chartCategoricalColors in config.toml
    slice_colors = [
        PALETTE["laser"], PALETTE["surge"], "#A78BFA",
        PALETTE["flare"], PALETTE["volt"], "#38BDF8",
        PALETTE["haze"], "#FB923C", "#2DD4BF", "#F472B6",
    ]

    fig = go.Figure(go.Pie(
        labels=holdings_df["symbol"],
        values=holdings_df["current_value"],
        hole=0.6,
        marker=dict(colors=slice_colors[:len(holdings_df)]),
        textinfo="label+percent",
        textfont=dict(color=PALETTE["frost"], size=12),
        textposition="inside",
    ))

    fig.update_layout(_base_layout(title, height, show_legend=False))
    fig.update_layout(paper_bgcolor=PALETTE["abyss"])
    return fig


def volatility_radar(
    volatility_df: pd.DataFrame,
    title: str = "Volatility Radar",
    height: int = 400,
) -> go.Figure:
    """
    Build a radar/scatter chart showing high-volatility stocks.

    Args:
        volatility_df: DataFrame with columns symbol, volatility, return
    """
    if volatility_df is None or volatility_df.empty:
        fig = go.Figure()
        fig.update_layout(_base_layout(title, height))
        return fig

    fig = go.Figure()

    # Scatter of volatility vs return
    for _, row in volatility_df.iterrows():
        color = (
            PALETTE["surge"] if row.get("return", 0) >= 0
            else PALETTE["flare"]
        )
        size = max(8, min(30, abs(row.get("return", 0)) * 2))

        fig.add_trace(go.Scatter(
            x=[row["volatility"]],
            y=[row.get("return", 0)],
            mode="markers+text",
            marker=dict(size=size, color=color, opacity=0.8,
                        line=dict(color=PALETTE["frost"], width=1)),
            text=[row["symbol"]],
            textposition="top center",
            textfont=dict(color=PALETTE["frost"], size=10),
            name=row["symbol"],
            showlegend=False,
        ))

    fig.update_layout(_base_layout(title, height))
    fig.update_layout(
        xaxis_title="Volatility (%)",
        yaxis_title="Return (%)",
    )
    return fig


def index_trend_line(
    df: pd.DataFrame,
    title: str = "Index Trend",
    height: int = 300,
) -> go.Figure:
    """Build a simple line chart for index trends."""
    if df is None or df.empty:
        fig = go.Figure()
        fig.update_layout(_base_layout(title, height))
        return fig

    fig = go.Figure(go.Scatter(
        x=df["date"], y=df["close"],
        mode="lines",
        line=dict(color=PALETTE["laser"], width=2),
        fill="tozeroy",
        fillcolor=f"rgba({RGB['laser']}, 0.12)",
    ))

    fig.update_layout(_base_layout(title, height, show_legend=False))
    return fig


def oi_by_strike_chart(
    strikes: list[dict],
    spot: float | None = None,
    window: int = 12,
    title: str = "Open Interest by Strike",
    height: int = 420,
) -> go.Figure:
    """
    Grouped Call/Put OI bars per strike, windowed around ATM, with a spot marker.

    Call OI (resistance) in flare-red, Put OI (support) in surge-green — the
    trader convention; legend + strike axis carry identity beyond colour.
    `strikes`: the parsed option-chain rows (strike / call.oi / put.oi).
    """
    if not strikes:
        fig = go.Figure()
        fig.update_layout(_base_layout(title, height))
        fig.add_annotation(text="No option-chain data", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False,
                           font=dict(color=PALETTE["haze"], size=14))
        return fig

    rows = strikes
    if spot is not None:                       # keep the ATM ± window band, readable
        rows = sorted(rows, key=lambda s: abs(s["strike"] - spot))[: window * 2]
    rows = sorted(rows, key=lambda s: s["strike"])

    xs = [s["strike"] for s in rows]
    ce = [s["call"].get("oi") or 0 for s in rows]
    pe = [s["put"].get("oi") or 0 for s in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=xs, y=ce, name="Call OI (R)",
                         marker_color=PALETTE["flare"], opacity=0.85))
    fig.add_trace(go.Bar(x=xs, y=pe, name="Put OI (S)",
                         marker_color=PALETTE["surge"], opacity=0.85))

    fig.update_layout(_base_layout(title, height))
    fig.update_layout(
        barmode="group", bargap=0.25, bargroupgap=0.05,
        xaxis_title="Strike",
        xaxis=dict(showspikes=False),          # spikes look noisy on a bar histogram
    )
    if spot is not None:
        fig.add_vline(
            x=spot, line=dict(color=PALETTE["frost"], width=1, dash="dot"),
            annotation_text=f"Spot {spot:,.0f}", annotation_position="top",
            annotation_font_color=PALETTE["frost"],
        )
    return fig


# TradingView lightweight-charts (v4) UMD, vendored and inlined into the page so
# there's ZERO network fetch per render — no CDN latency, no reload flicker, works
# offline. That is the smoothness fix: the CDN <script src> reloaded on every rerun.
_LW_VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "lightweight-charts.js"
try:
    _LW_JS_SRC = _LW_VENDOR.read_text(encoding="utf-8")
except Exception:
    _LW_JS_SRC = ""  # fall back to CDN if the vendored file is missing
_LW_CDN = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"


def lightweight_candles_html(
    df: pd.DataFrame,
    levels: list[dict] | None,
    kind_color: dict,
    *,
    height: int = 470,
    title: str = "",
) -> str:
    """
    A fully interactive TradingView candlestick (crosshair, drag-pan, wheel-zoom,
    labelled price lines) as a self-contained HTML string for st.components.v1.html.

    df: chronological columns date/open/high/low/close (as _candles_df yields).
    levels: [{price, kind, label}] → horizontal price lines coloured by kind.

    Times are pushed as IST wall-clock (lightweight-charts renders timestamps as
    UTC, so we offset by +5:30 to make the axis/crosshair read IST).
    """
    import json

    bars = []
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            t = pd.to_datetime(r["date"])
            if t.tzinfo is None:
                t = t.tz_localize("Asia/Kolkata")
            bars.append({
                "time": int(t.timestamp()) + 19800,   # +5:30 → show IST wall-clock
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
            })
    lines = []
    for lv in levels or []:
        p = lv.get("price")
        if p is None:
            continue
        lines.append({
            "price": float(p),
            "color": kind_color.get(lv.get("kind"), PALETTE["haze"]),
            "title": str(lv.get("label", "")),
        })

    grid = f"rgba({RGB['haze']}, 0.08)"
    lw_script = f"<script>{_LW_JS_SRC}</script>" if _LW_JS_SRC else f'<script src="{_LW_CDN}"></script>'
    return f"""
<div style="position:relative;height:{height}px;background:{PALETTE['depth']};border-radius:8px;">
  <div id="lwtitle" style="position:absolute;top:8px;left:12px;z-index:3;
       font:600 13px Inter,sans-serif;color:{PALETTE['frost']};pointer-events:none;">{title}</div>
  <div id="lwchart" style="height:{height}px;"></div>
</div>
{lw_script}
<script>
(function() {{
  var el = document.getElementById('lwchart');
  if (!window.LightweightCharts || !el) return;
  var chart = LightweightCharts.createChart(el, {{
    autoSize: true,
    layout: {{ background: {{ color: 'transparent' }}, textColor: '{PALETTE['haze']}',
               fontFamily: 'JetBrains Mono, monospace' }},
    grid: {{ vertLines: {{ color: '{grid}' }}, horzLines: {{ color: '{grid}' }} }},
    crosshair: {{ mode: 0 }},
    rightPriceScale: {{ borderColor: '{PALETTE['grid']}' }},
    timeScale: {{ timeVisible: true, secondsVisible: false, borderColor: '{PALETTE['grid']}' }},
    handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true }},
    handleScale: {{ mouseWheel: true, pinch: true, axisPressedMouseMove: true }},
    kineticScroll: {{ mouse: true, touch: true }},
  }});
  var s = chart.addCandlestickSeries({{
    upColor: '{PALETTE['surge']}', downColor: '{PALETTE['flare']}',
    wickUpColor: '{PALETTE['surge']}', wickDownColor: '{PALETTE['flare']}',
    borderVisible: false,
  }});
  s.setData({json.dumps(bars)});
  var lines = {json.dumps(lines)};
  for (var i = 0; i < lines.length; i++) {{
    s.createPriceLine({{ price: lines[i].price, color: lines[i].color,
      lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: lines[i].title }});
  }}
  chart.timeScale().fitContent();
}})();
</script>
"""


__all__ = [
    "candlestick_chart",
    "lightweight_candles_html",
    "returns_bar_chart",
    "ownership_stacked_area",
    "peers_comparison_bar",
    "allocation_wheel",
    "volatility_radar",
    "index_trend_line",
    "oi_by_strike_chart",
]