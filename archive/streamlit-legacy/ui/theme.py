"""
ARTHA Terminal - Theme Module

Colors, fonts, radius and every native widget are themed in
`.streamlit/config.toml`. This module only holds:
  - PALETTE, so Python code (Plotly, inline spans) can use the same colors
  - the small amount of CSS for components Streamlit has no native version of
"""

# ============================================
# Color Palette
# ============================================
# Keys are historical; values track .streamlit/config.toml — keep in sync.

PALETTE = {
    "abyss": "#0F172A",      # Background
    "depth": "#1E293B",      # Panels
    "grid": "#334155",       # Borders
    "laser": "#60A5FA",      # Primary accent (blue)
    "surge": "#34D399",      # Up/Bull (green)
    "flare": "#F87171",      # Down/Bear (red)
    "volt": "#FBBF24",       # Warn/Volatility (amber)
    "frost": "#F1F5F9",      # Text
    "haze": "#94A3B8",       # Muted
}

# RGB triples for the few places that need alpha over a palette color.
RGB = {
    "laser": "96, 165, 250",
    "surge": "52, 211, 153",
    "flare": "248, 113, 113",
    "volt": "251, 191, 36",
    "grid": "51, 65, 85",
    "haze": "148, 163, 184",
    "frost": "241, 245, 249",
}

# ============================================
# Verified Status Colors (from verification membrane)
# ============================================

STATUS_COLORS = {
    "VERIFIED": PALETTE["surge"],
    "SINGLE_SOURCE": PALETTE["volt"],
    "CONFLICT": PALETTE["flare"],
    "PENDING": PALETTE["haze"],
}

# ============================================
# Global CSS — custom components only.
# Anything a config.toml option can do is NOT here.
# ============================================

GLOBAL_CSS = f"""
<style>
    /* Suppress Streamlit chrome */
    #MainMenu {{visibility: hidden;}}
    header {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    .builtWithPill {{display: none;}}
    .stDeployButton {{display: none;}}

    :root {{
        --abyss: {PALETTE['abyss']};
        --depth: {PALETTE['depth']};
        --grid: {PALETTE['grid']};
        --laser: {PALETTE['laser']};
        --surge: {PALETTE['surge']};
        --flare: {PALETTE['flare']};
        --volt: {PALETTE['volt']};
        --frost: {PALETTE['frost']};
        --haze: {PALETTE['haze']};

        /* Surfaces sit ABOVE the page, not level with it — this is what
           stops cards reading as empty space. */
        --surface: #18233A;
        --surface-hi: #1F2C47;
        --border: rgba({RGB['haze']}, 0.18);
        --border-hi: rgba({RGB['laser']}, 0.55);
        --shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 6px 20px rgba(0, 0, 0, 0.35);
        --shadow-hi: 0 2px 4px rgba(0, 0, 0, 0.4), 0 14px 34px rgba(0, 0, 0, 0.5);
    }}

    /* Ambient depth — two cool washes, no neon */
    .stApp {{
        background-image:
            radial-gradient(ellipse 90% 55% at 12% -5%, rgba({RGB['laser']}, 0.10) 0%, transparent 60%),
            radial-gradient(ellipse 75% 55% at 88% 5%, rgba(167, 139, 250, 0.07) 0%, transparent 60%);
        background-attachment: fixed;
    }}

    /* ============ Density ============
       Streamlit ships ~6rem of dead space above the first element and lets
       content sprawl edge-to-edge on wide monitors. Both read as "empty". */
    .stMain .block-container {{
        padding-top: 0.75rem;
        padding-bottom: 3rem;
        max-width: 1480px;
    }}

    /* st.container(border=True) renders a transparent bordered stVerticalBlock —
       give it the same surface as .card so native and custom tiles match. */
    .stMain [data-testid="stVerticalBlock"][style*="border"],
    .stMain [data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {{
        background: linear-gradient(180deg, var(--surface-hi) 0%, var(--surface) 100%);
        border-color: var(--border) !important;
        border-radius: 14px;
        box-shadow: var(--shadow), inset 0 1px 0 rgba({RGB['frost']}, 0.05);
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }}
    .stMain [data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]:hover {{
        border-color: var(--border-hi) !important;
        box-shadow: var(--shadow-hi);
    }}
    .stMain h1, .stMain h2, .stMain h3 {{
        margin-bottom: 0.35rem;
    }}

    /* ============ Card / Panel ============
       One surface treatment, used by every tile in the app. */
    .card, .panel {{
        background: linear-gradient(180deg, var(--surface-hi) 0%, var(--surface) 100%);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 1rem 1.15rem;
        box-shadow: var(--shadow), inset 0 1px 0 rgba({RGB['frost']}, 0.05);
        transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
    }}
    .card:hover, .panel:hover {{
        border-color: var(--border-hi);
        box-shadow: var(--shadow-hi);
        transform: translateY(-2px);
    }}
    /* Directional accent rail — up/down/flat state at a glance */
    .card-up   {{ border-left: 3px solid var(--surge); }}
    .card-down {{ border-left: 3px solid var(--flare); }}
    .card-flat {{ border-left: 3px solid var(--haze); }}

    /* Section heading: small caps eyebrow with a hairline, no emoji */
    .section-head {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin: 0.25rem 0 0.75rem;
    }}
    .section-head .title {{
        font-size: 1.05rem;
        font-weight: 700;
        color: var(--frost);
        letter-spacing: 0.2px;
        white-space: nowrap;
    }}
    .section-head .rule {{
        flex: 1;
        height: 1px;
        background: linear-gradient(90deg, var(--border), transparent);
    }}

    /* ============ Semantic text ============ */
    .neon-success {{ color: var(--surge); }}
    .neon-danger  {{ color: var(--flare); }}
    .neon-warning {{ color: var(--volt); }}
    .neon-primary {{ color: var(--laser); }}
    .neon-muted   {{ color: var(--haze); }}

    /* ============ Metric card ============ */
    .metric-card {{
        position: relative;
        overflow: hidden;
        background: linear-gradient(180deg, var(--surface-hi) 0%, var(--surface) 100%);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 1.15rem 1.25rem;
        box-shadow: var(--shadow), inset 0 1px 0 rgba({RGB['frost']}, 0.05);
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    }}
    .metric-card::before {{
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 2px;
        background: linear-gradient(90deg, transparent, rgba({RGB['laser']}, 0.8), transparent);
    }}
    .metric-card:hover {{
        transform: translateY(-3px);
        border-color: var(--border-hi);
        box-shadow: var(--shadow-hi);
    }}
    .metric-value {{
        font-size: 1.9rem;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.5px;
        margin: 0.35rem 0 0;
    }}
    .metric-label {{
        font-size: 0.7rem;
        color: var(--haze);
        text-transform: uppercase;
        letter-spacing: 1.2px;
        font-weight: 600;
    }}
    .metric-delta {{
        font-size: 0.85rem;
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
        margin-top: 0.15rem;
    }}

    /* ============ Verification status badges ============ */
    .status-badge {{
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
    }}
    .status-VERIFIED {{
        background: rgba({RGB['surge']}, 0.14); color: var(--surge);
        border: 1px solid rgba({RGB['surge']}, 0.45);
    }}
    .status-SINGLE_SOURCE {{
        background: rgba({RGB['volt']}, 0.14); color: var(--volt);
        border: 1px solid rgba({RGB['volt']}, 0.45);
    }}
    .status-CONFLICT {{
        background: rgba({RGB['flare']}, 0.14); color: var(--flare);
        border: 1px solid rgba({RGB['flare']}, 0.45);
    }}
    .status-PENDING {{
        background: rgba({RGB['haze']}, 0.14); color: var(--haze);
        border: 1px solid rgba({RGB['haze']}, 0.45);
    }}

    /* ============ Charts & tables framed as panels ============ */
    [data-testid="stPlotlyChart"] {{
        border: 1px solid var(--grid);
        border-radius: 14px;
        overflow: hidden;
        background: var(--depth);
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }}
    [data-testid="stPlotlyChart"]:hover {{
        border-color: rgba({RGB['laser']}, 0.4);
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    }}
    [data-testid="stPlotlyChart"] > div {{ border-radius: 14px; }}

    /* Tabular figures everywhere numbers live */
    [data-testid="stMetricValue"], [data-testid="stDataFrame"] {{
        font-variant-numeric: tabular-nums;
    }}

    /* Softer, tighter rules — the default divider eats a whole screen of air */
    hr {{
        border: none !important;
        height: 1px !important;
        background: var(--border) !important;
        margin: 1.1rem 0 !important;
    }}

    /* Slim themed scrollbars */
    ::-webkit-scrollbar {{ width: 9px; height: 9px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: var(--grid); border-radius: 999px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--haze); }}

    /* Accessibility */
    @media (prefers-reduced-motion: reduce) {{
        * {{
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
        }}
    }}

    .sebi-disclaimer {{
        text-align: center;
        color: var(--haze);
        font-size: 0.7rem;
        margin-top: 2rem;
        padding: 1rem;
        border-top: 1px solid var(--grid);
        line-height: 1.6;
    }}
</style>
"""

# ============================================
# SEBI Disclaimer (persistent footer)
# ============================================

SEBI_DISCLAIMER = """
<div class="sebi-disclaimer">
    <strong style="color: var(--volt);">SEBI disclaimer:</strong> ARTHA Terminal is for research and educational purposes only.
    The Analysis Score (0–10) is <strong>NOT</strong> a buy/sell recommendation.
    All data is sourced from public APIs and disclosures.
    Consult a SEBI-registered investment advisor before making investment decisions.
</div>
"""

# ============================================
# Helper to build metric card HTML
# ============================================

def metric_card(
    label: str,
    value: str,
    delta: str = "",
    delta_type: str = "neutral",  # 'up', 'down', 'neutral', 'warn'
) -> str:
    """Build an HTML metric card."""
    delta_color_class = {
        "up": "neon-success",
        "down": "neon-danger",
        "neutral": "neon-muted",
        "warn": "neon-warning",
    }.get(delta_type, "neon-muted")

    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        {f'<div class="metric-delta {delta_color_class}">{delta}</div>' if delta else ''}
    </div>
    """


def section_head(title: str, note: str = "") -> str:
    """Build a section heading: title, hairline rule, optional right-aligned note."""
    right = (
        f'<span style="font-size:0.68rem; color:{PALETTE["haze"]}; white-space:nowrap;">{note}</span>'
        if note else ""
    )
    return (
        f'<div class="section-head"><span class="title">{title}</span>'
        f'<span class="rule"></span>{right}</div>'
    )


def status_badge(status: str) -> str:
    """Build a verified-status badge."""
    return f'<span class="status-badge status-{status}">{status.replace("_", " ")}</span>'


def clean_html(html: str) -> str:
    """
    Collapse a multi-line HTML string to a single line with no leading
    indentation. Streamlit's markdown parser treats any line indented 4+ spaces
    as a code block and renders the raw HTML as text — this prevents that.
    """
    return " ".join(line.strip() for line in html.splitlines() if line.strip())


__all__ = [
    "PALETTE",
    "RGB",
    "STATUS_COLORS",
    "GLOBAL_CSS",
    "SEBI_DISCLAIMER",
    "metric_card",
    "section_head",
    "status_badge",
    "clean_html",
]
