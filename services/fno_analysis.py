"""
ARTHA Terminal - F&O Analysis Engine
Deterministic options-structure analytics for NIFTY / BANK NIFTY / SENSEX.

Pure math on the option chain (from services.upstox.get_option_chain) plus the
prior session's OHLC and India VIX. Everything here is auditable and never a
buy/sell call — the same SEBI-safe framing as the rest of ARTHA. An LLM may
narrate these numbers downstream, but never generates them.

Definitions used:
  • PCR (OI)      = Σ put OI / Σ call OI  (>1 = put-writing/supportive)
  • Max pain      = expiry price minimizing total ITM value to option buyers
  • OI walls      = strike with max call OI (resistance) / max put OI (support)
  • Expected move = ATM straddle price ≈ market-implied move by expiry
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


# ----------------------------------------------------------------------
# Level kinds → how the TradingView draw bridge (Phase D) colours them.
# ----------------------------------------------------------------------
KIND_SUPPORT = "support"
KIND_RESISTANCE = "resistance"
KIND_MAXPAIN = "maxpain"
KIND_RANGE = "range"
KIND_PIVOT = "pivot"


@dataclass
class Level:
    label: str
    price: float
    kind: str


# ----------------------------------------------------------------------
# Core option-chain analytics (pure functions)
# ----------------------------------------------------------------------

def atm_strike(spot: float, strikes: list[dict]) -> float | None:
    """The strike nearest to spot."""
    if spot is None or not strikes:
        return None
    return min((s["strike"] for s in strikes), key=lambda k: abs(k - spot))


def pcr_oi(strikes: list[dict]) -> float | None:
    """Put/Call ratio by open interest. None if no call OI."""
    call = sum((s["call"]["oi"] or 0) for s in strikes)
    put = sum((s["put"]["oi"] or 0) for s in strikes)
    return (put / call) if call else None


def max_pain(strikes: list[dict]) -> float | None:
    """
    Strike minimizing total ITM value to buyers (writers' 'max pain').

    For candidate expiry price E: value = Σ_K [CE_OI(K)·max(0,E−K)]
                                        + Σ_K [PE_OI(K)·max(0,K−E)].
    Evaluated across the listed strikes (the standard discrete method).
    """
    if not strikes:
        return None
    best_k, best_pain = None, None
    for cand in strikes:
        e = cand["strike"]
        pain = 0.0
        for s in strikes:
            k = s["strike"]
            ce = s["call"]["oi"] or 0
            pe = s["put"]["oi"] or 0
            if e > k:
                pain += ce * (e - k)
            elif k > e:
                pain += pe * (k - e)
        if best_pain is None or pain < best_pain:
            best_pain, best_k = pain, e
    return best_k


def oi_walls(strikes: list[dict]) -> dict:
    """Highest-OI call strike (resistance) and put strike (support)."""
    call_wall = max(strikes, key=lambda s: s["call"]["oi"] or 0, default=None)
    put_wall = max(strikes, key=lambda s: s["put"]["oi"] or 0, default=None)
    return {
        "call_wall": call_wall["strike"] if call_wall else None,
        "put_wall": put_wall["strike"] if put_wall else None,
    }


def expected_move(spot: float, strikes: list[dict]) -> dict | None:
    """
    Market-implied move by expiry from the ATM straddle (CE+PE LTP).
    Returns {"straddle","upper","lower","pct"} or None if unavailable.
    """
    atm = atm_strike(spot, strikes)
    if atm is None:
        return None
    row = next((s for s in strikes if s["strike"] == atm), None)
    if not row:
        return None
    ce, pe = row["call"]["ltp"], row["put"]["ltp"]
    if ce is None or pe is None:
        return None
    straddle = ce + pe
    return {
        "straddle": straddle,
        "upper": spot + straddle,
        "lower": spot - straddle,
        "pct": (straddle / spot * 100) if spot else None,
    }


def atm_iv(spot: float, strikes: list[dict]) -> float | None:
    """Average of ATM call & put IV — a quick IV read for strategy selection."""
    atm = atm_strike(spot, strikes)
    row = next((s for s in strikes if s["strike"] == atm), None) if atm else None
    if not row:
        return None
    ivs = [v for v in (row["call"]["iv"], row["put"]["iv"]) if v]
    return (sum(ivs) / len(ivs)) if ivs else None


# ----------------------------------------------------------------------
# Options-flow bias (deterministic, explainable)
# ----------------------------------------------------------------------

def options_flow_bias(strikes: list[dict], spot: float, mp: float | None) -> dict:
    """
    A scoped bias from OPTION-CHAIN flow only (0=very bearish, 100=very bullish,
    50=neutral). Blends PCR, net OI-change (writing pressure) and spot-vs-max-pain
    pull. Returns {"score","label","drivers":[{name,detail,delta}]}.

    ponytail: options-flow only — a full directional bias also wants futures OI
    buildup + price-vs-VWAP/pivots + news; those fold in at the orchestration layer.
    """
    score = 50.0
    drivers = []

    pcr = pcr_oi(strikes)
    if pcr is not None:
        # >1.3 supportive (put writing), <0.7 heavy (call writing).
        if pcr >= 1.3:
            d = min(18, (pcr - 1.3) * 40 + 8); drivers.append(("PCR", f"{pcr:.2f} (put-writing/supportive)", +d)); score += d
        elif pcr <= 0.7:
            d = min(18, (0.7 - pcr) * 40 + 8); drivers.append(("PCR", f"{pcr:.2f} (call-writing/heavy)", -d)); score -= d
        else:
            drivers.append(("PCR", f"{pcr:.2f} (balanced)", 0))

    # Net OI change: puts adding faster than calls = bullish (put writing).
    ce_chg = sum((s["call"]["oi_change"] or 0) for s in strikes)
    pe_chg = sum((s["put"]["oi_change"] or 0) for s in strikes)
    net = pe_chg - ce_chg
    tot = abs(ce_chg) + abs(pe_chg)
    if tot:
        d = max(-15, min(15, net / tot * 15))
        drivers.append(("OI change", f"put−call ΔOI {net:+,.0f}", round(d, 1)))
        score += d

    # Spot vs max pain: price stretched above max pain has a downward pull.
    if mp and spot:
        gap = (spot - mp) / spot * 100
        if abs(gap) >= 0.5:
            d = max(-10, min(10, -gap * 2))  # above max pain → mild bearish pull
            drivers.append(("Max-pain pull", f"spot {gap:+.1f}% vs max pain", round(d, 1)))
            score += d

    score = max(0, min(100, round(score)))
    label = "BULLISH" if score >= 62 else "BEARISH" if score <= 38 else "NEUTRAL"
    return {"score": score, "label": label,
            "drivers": [{"name": n, "detail": t, "delta": dl} for n, t, dl in drivers]}


# ----------------------------------------------------------------------
# Strategy concept (educational, IV-regime driven)
# ----------------------------------------------------------------------

def strategy_concept(bias_label: str, iv: float | None, em: dict | None,
                     walls: dict) -> dict:
    """
    Map bias + IV regime to an educational strategy concept (NOT a call).
    Uses OI walls / expected-move edges as strike anchors.
    """
    high_iv = iv is not None and iv >= 15  # crude regime split; VIX-relative later
    if bias_label == "NEUTRAL":
        if high_iv:
            name = "Iron Condor (premium-selling)"
            note = ("Range-bound + rich IV. Sell OTM call & put spreads with short "
                    "strikes near the OI walls / expected-move edges; defined risk.")
        else:
            name = "Calendar / wait"
            note = "Range-bound but IV is low — little premium to sell; often a no-trade day."
    elif bias_label == "BULLISH":
        name = "Bull Put Spread" if high_iv else "Bull Call (debit) Spread"
        note = ("Sell a put spread below the put OI wall (collect rich premium)."
                if high_iv else "Buy a call debit spread; cheap IV favours long premium.")
    else:  # BEARISH
        name = "Bear Call Spread" if high_iv else "Bear Put (debit) Spread"
        note = ("Sell a call spread above the call OI wall."
                if high_iv else "Buy a put debit spread; cheap IV favours long premium.")

    anchors = {"call_wall": walls.get("call_wall"), "put_wall": walls.get("put_wall")}
    if em:
        anchors["em_upper"] = round(em["upper"], 1)
        anchors["em_lower"] = round(em["lower"], 1)
    return {"name": name, "note": note, "iv_regime": "high" if high_iv else "low",
            "anchors": anchors}


# ----------------------------------------------------------------------
# Level bundle (what Phase D draws on TradingView)
# ----------------------------------------------------------------------

def build_levels(spot: float, mp: float | None, walls: dict, em: dict | None,
                 pivots: dict | None = None, prev: dict | None = None) -> list[dict]:
    """Combine option-derived + price-structure levels into one labeled draw list."""
    levels: list[Level] = []
    if mp is not None:
        levels.append(Level("Max Pain", mp, KIND_MAXPAIN))
    if walls.get("call_wall") is not None:
        levels.append(Level("Call OI Wall (R)", walls["call_wall"], KIND_RESISTANCE))
    if walls.get("put_wall") is not None:
        levels.append(Level("Put OI Wall (S)", walls["put_wall"], KIND_SUPPORT))
    if em:
        levels.append(Level("Exp-Move Upper", em["upper"], KIND_RANGE))
        levels.append(Level("Exp-Move Lower", em["lower"], KIND_RANGE))
    if pivots:
        for name in ("R2", "R1", "P", "S1", "S2"):
            if pivots.get(name) is not None:
                kind = KIND_PIVOT if name == "P" else (
                    KIND_RESISTANCE if name.startswith("R") else KIND_SUPPORT)
                levels.append(Level(f"Pivot {name}", pivots[name], kind))
    if prev:
        if prev.get("high") is not None:
            levels.append(Level("Prev Day High", prev["high"], KIND_RESISTANCE))
        if prev.get("low") is not None:
            levels.append(Level("Prev Day Low", prev["low"], KIND_SUPPORT))
    # round prices to 1 decimal; drop any without a price
    return [{"label": l.label, "price": round(l.price, 1), "kind": l.kind}
            for l in levels if l.price is not None]


# ----------------------------------------------------------------------
# Top-level composition
# ----------------------------------------------------------------------

def analyze(chain: dict, *, prev_ohlc: dict | None = None,
            vix: float | None = None, pivots: dict | None = None) -> dict:
    """
    Full deterministic F&O game plan for one index from a parsed option chain.

    `chain` is the dict from UpstoxClient.get_option_chain (has spot, strikes,
    expiry). prev_ohlc/pivots/vix are optional enrichments from other sources.
    """
    spot = chain.get("spot")
    strikes = chain.get("strikes", [])
    if not spot or not strikes:
        return {"ok": False, "error": "empty or invalid option chain"}

    mp = max_pain(strikes)
    walls = oi_walls(strikes)
    em = expected_move(spot, strikes)
    iv = atm_iv(spot, strikes)
    pcr = pcr_oi(strikes)
    bias = options_flow_bias(strikes, spot, mp)
    strat = strategy_concept(bias["label"], iv, em, walls)
    levels = build_levels(spot, mp, walls, em, pivots=pivots, prev=prev_ohlc)

    return {
        "ok": True,
        "spot": spot,
        "expiry": chain.get("expiry"),
        "atm": atm_strike(spot, strikes),
        "pcr_oi": round(pcr, 2) if pcr is not None else None,
        "max_pain": mp,
        "oi_walls": walls,
        "expected_move": em,
        "atm_iv": round(iv, 2) if iv is not None else None,
        "india_vix": vix,
        "bias": bias,
        "strategy": strat,
        "levels": levels,
    }


__all__ = [
    "atm_strike", "pcr_oi", "max_pain", "oi_walls", "expected_move", "atm_iv",
    "options_flow_bias", "strategy_concept", "build_levels", "analyze", "Level",
]
