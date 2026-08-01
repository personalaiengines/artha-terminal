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
  • Zone          = levels within 0.15% of each other, scored by how many
                    independent methods agree on that price
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, asdict
from statistics import median


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
    if not straddle:
        # Both ATM legs unquoted (a far, untraded expiry prints ltp 0.0). A
        # zero-width band centred on spot is not a measurement — every caller
        # already handles None as "expected move unavailable".
        return None
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
# Structure concept (educational, IV-regime driven)
# ----------------------------------------------------------------------

def _leg(right: str, pos: str, anchor: str, step: int) -> dict:
    """
    One leg of the named structure, described positionally.

    `anchor` names a key in the returned `anchors` dict; `step` counts listed
    strikes FURTHER out-of-the-money from that anchor (negative = one strike
    closer to spot). The UI resolves each leg against the loaded chain and
    prices it at that strike's own live LTP — a leg it cannot resolve means the
    payoff is not drawn at all, never an assumed premium (R17).
    """
    return {"right": right, "pos": pos, "anchor": anchor, "step": step}


def strategy_concept(bias_label: str, iv: float | None, em: dict | None,
                     walls: dict) -> dict:
    """
    Name the option STRUCTURE that matches the bias + IV regime and describe how
    it is built, using the OI walls / expected-move edges as strike anchors.

    Every string returned describes the structure itself. None of them is an
    instruction to the reader, and none carries buy/sell/exit vocabulary (R16) —
    this is educational context beside the chain, not a call.
    """
    high_iv = iv is not None and iv >= 15  # crude regime split; VIX-relative later
    if bias_label == "NEUTRAL":
        if high_iv:
            name = "Iron Condor"
            note = ("Range-bound with rich IV. Two out-of-the-money verticals, one "
                    "either side: the anchor legs sit at the OI walls and the wing "
                    "legs one strike further out. Net credit, risk capped on both "
                    "wings, and time decay favours the writer while price stays "
                    "between the walls.")
            legs = [_leg("put", "short", "put_wall", 0), _leg("put", "long", "put_wall", 1),
                    _leg("call", "short", "call_wall", 0), _leg("call", "long", "call_wall", 1)]
        else:
            name = "Calendar Spread"
            note = ("Range-bound but IV is low, so a same-expiry range structure "
                    "collects little premium. A calendar spans two expiries and "
                    "trades the term structure rather than the level of IV — it "
                    "cannot be drawn from a single expiry's chain.")
            legs = []   # two expiries; one chain cannot price it
    elif bias_label == "BULLISH":
        if high_iv:
            name = "Bull Put Spread (credit)"
            note = ("Upside bias with rich IV. A vertical below the put OI wall: the "
                    "anchor leg at the wall, the wing leg one strike lower. Net "
                    "credit, and the worst outcome is the strike width less that credit.")
            legs = [_leg("put", "short", "put_wall", 0), _leg("put", "long", "put_wall", 1)]
        else:
            name = "Bull Call Spread (debit)"
            note = ("Upside bias with cheap IV. A vertical capped at the call OI wall: "
                    "the anchor leg at the wall, the inner leg one strike closer to "
                    "spot. Net debit — cheap IV is what makes long premium affordable — "
                    "and the best outcome is the strike width less that debit.")
            legs = [_leg("call", "long", "call_wall", -1), _leg("call", "short", "call_wall", 0)]
    else:  # BEARISH
        if high_iv:
            name = "Bear Call Spread (credit)"
            note = ("Downside bias with rich IV. A vertical above the call OI wall: the "
                    "anchor leg at the wall, the wing leg one strike higher. Net "
                    "credit, and the worst outcome is the strike width less that credit.")
            legs = [_leg("call", "short", "call_wall", 0), _leg("call", "long", "call_wall", 1)]
        else:
            name = "Bear Put Spread (debit)"
            note = ("Downside bias with cheap IV. A vertical capped at the put OI wall: "
                    "the anchor leg at the wall, the inner leg one strike closer to "
                    "spot. Net debit — cheap IV is what makes long premium affordable — "
                    "and the best outcome is the strike width less that debit.")
            legs = [_leg("put", "long", "put_wall", -1), _leg("put", "short", "put_wall", 0)]

    anchors = {"call_wall": walls.get("call_wall"), "put_wall": walls.get("put_wall")}
    if em:
        anchors["em_upper"] = round(em["upper"], 1)
        anchors["em_lower"] = round(em["lower"], 1)
    return {"name": name, "note": note, "iv_regime": "high" if high_iv else "low",
            "anchors": anchors, "legs": legs}


# ----------------------------------------------------------------------
# Level bundle (what Phase D draws on TradingView)
# ----------------------------------------------------------------------

def build_levels(spot: float, mp: float | None, walls: dict, em: dict | None,
                 pivots: dict | None = None, prev: dict | None = None,
                 structure: dict | None = None) -> list[dict]:
    """Combine option-derived + price-structure levels into one labeled draw list.

    `structure` is services.levels.prior_structure() — the CPR band, the Camarilla
    pair and last week's range, all arithmetic on settled OHLC. Absent keys draw
    nothing; a level is never approximated from another level (R17)."""
    levels: list[Level] = []
    if mp is not None:
        levels.append(Level("Max Pain", mp, KIND_MAXPAIN))
    if walls.get("call_wall") is not None:
        levels.append(Level("Call OI Wall", walls["call_wall"], KIND_RESISTANCE))
    if walls.get("put_wall") is not None:
        levels.append(Level("Put OI Wall", walls["put_wall"], KIND_SUPPORT))
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
        # The gap reference: where the last session actually settled.
        if prev.get("close") is not None:
            levels.append(Level("Prev Day Close", prev["close"], KIND_RESISTANCE))

    if structure:
        # CPR — the pivot band Indian intraday desks trade around. Its width is
        # the read (narrow = trend day, wide = range), so both edges are drawn.
        cpr = structure.get("cpr") or {}
        if cpr.get("top") is not None:
            levels.append(Level("CPR Top", cpr["top"], KIND_RESISTANCE))
        if cpr.get("bottom") is not None:
            levels.append(Level("CPR Bottom", cpr["bottom"], KIND_SUPPORT))
        # Camarilla H3/L3 — the intraday reversal band.
        cam = structure.get("camarilla") or {}
        if cam.get("H3") is not None:
            levels.append(Level("Camarilla H3", cam["H3"], KIND_RESISTANCE))
        if cam.get("L3") is not None:
            levels.append(Level("Camarilla L3", cam["L3"], KIND_SUPPORT))
        # Last completed week's range — the swing context a daily chart loses.
        week = structure.get("week") or {}
        if week.get("high") is not None:
            levels.append(Level("Prev Week High", week["high"], KIND_RESISTANCE))
        if week.get("low") is not None:
            levels.append(Level("Prev Week Low", week["low"], KIND_SUPPORT))

    # Support and resistance are POSITIONS RELATIVE TO PRICE, not fixed
    # properties of a level. Every kind above was assigned from the level's
    # name — "Prev Day High" was always resistance, Pivot S1 always support —
    # so once price crossed one, the chart kept asserting the old side. A
    # broken resistance IS the next support; that is the whole point of the
    # level. Re-derive from spot, and flag the ones that flipped so the UI can
    # say "broken" rather than silently relabel.
    #
    # Max Pain, the pivot point itself, and the expected-move band are magnets
    # and boundaries, not S/R — they keep their kind.
    out = []
    for l in levels:
        if l.price is None:
            continue
        kind, crossed = l.kind, False
        if kind in (KIND_RESISTANCE, KIND_SUPPORT):
            kind = KIND_RESISTANCE if l.price > spot else KIND_SUPPORT
            crossed = kind != l.kind
        out.append({"label": l.label, "price": round(l.price, 1),
                    "kind": kind, "crossed": crossed})
    return out


# ----------------------------------------------------------------------
# Confluence zones, strength, and the structure read (pure, no I/O)
#
# A flat list of twelve prices says nothing about which of them matter. When
# the option writers (an OI wall) and the price structure (a pivot, a prior-day
# extreme) name the SAME price, that price is a materially stronger level than
# either method alone — so cluster them, score the cluster, and make the score
# state its own basis. Nothing here is generated by a model and no number in a
# basis string is invented: every clause is assembled from the inputs that
# produced the score. Missing inputs are named as missing, never defaulted.
# ----------------------------------------------------------------------

ZONE_TOL_PCT = 0.15      # levels this close (as % of spot) are one zone
_WALL_MULTIPLE = 1.5     # an OI wall counts as heavy at this × the median strike OI
_AT_PRICE_PCT = 0.10     # |distance| under this and price is sitting on the zone
_WATCH_PCT = 0.25        # spot this close to a strong zone → WATCH
_WATCH_STRENGTH = 60     # "strong" for the WATCH rule
_SIDE = {KIND_RESISTANCE: KIND_SUPPORT, KIND_SUPPORT: KIND_RESISTANCE}


def _px(v: float) -> str:
    """Price for a basis string — full points for an index, decimals below 1000."""
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"


def _oi(v: float) -> str:
    """Open interest in lakhs, the unit an Indian chain is read in."""
    return f"{v / 1e5:.1f}L"


def wall_oi_context(strikes: list[dict], walls: dict) -> dict | None:
    """
    Each OI wall's own OI against the MEDIAN strike OI on the same side — the
    check that separates a real wall from "the biggest of twelve small numbers".
    Returns {"call": {"oi","median"}, "put": {...}} or None without strikes.
    """
    if not strikes:
        return None
    out = {}
    for side, wall_key in (("call", "call_wall"), ("put", "put_wall")):
        k = walls.get(wall_key) if walls else None
        ois = [s[side]["oi"] for s in strikes if s.get(side) and s[side].get("oi")]
        row = next((s for s in strikes if s["strike"] == k), None) if k is not None else None
        out[side] = {"oi": (row[side]["oi"] if row else None),
                     "median": (median(ois) if ois else None)}
    return out


def zone_strength(zone: dict, spot: float, em: dict | None = None,
                  walls_oi: dict | None = None, *, nearest: bool = False) -> tuple[int, str]:
    """
    Deterministic 0-100 score for one zone PLUS the sentence that justifies it.

    Base 20. Confluence +25/extra member (cap +50) · heavy OI wall +20 ·
    inside the expected-move band +15 · nearest zone to spot +10 · crossed −15.
    A component whose input is missing is omitted from BOTH the score and the
    basis — never scored as a default that reads like a measurement (R17).
    """
    members = zone["members"]
    score, clauses = 20, []

    if len(members) > 1:
        score += min(50, 25 * (len(members) - 1))
        spread = (zone["hi"] - zone["lo"]) / spot * 100 if spot else 0.0
        clauses.append(" + ".join(f"{m['label']} {_px(m['price'])}" for m in members)
                       + f" agree within {spread:.2f}%")
    else:
        clauses.append(f"{members[0]['label']} {_px(members[0]['price'])} "
                       f"is the only method at this price")

    for m in members:
        side = {"Call OI Wall": "call", "Put OI Wall": "put"}.get(m["label"])
        w = (walls_oi or {}).get(side) if side else None
        if w and w.get("oi") and w.get("median") and w["oi"] >= _WALL_MULTIPLE * w["median"]:
            score += 20
            clauses.append(f"{side} OI {_oi(w['oi'])} vs {_oi(w['median'])} median across strikes")
            break

    band = em and em.get("upper") is not None and em.get("lower") is not None
    if band and em["lower"] <= zone["price"] <= em["upper"]:
        score += 15
        clauses.append(f"inside the ±{_px(em['straddle'])} expected-move band")

    if nearest:
        score += 10
        clauses.append("nearest level above spot" if zone["price"] > spot
                       else "nearest level below spot")

    if zone["crossed"]:
        score -= 15
        clauses.append("crossed since the prior session")

    if not band:
        clauses.append("expected move unavailable")

    return max(0, min(100, int(round(score)))), "; ".join(clauses) + "."


def level_zones(spot: float, levels: list[dict], tol_pct: float = ZONE_TOL_PCT, *,
                em: dict | None = None, walls_oi: dict | None = None) -> list[dict]:
    """
    Cluster `build_levels()` output into confluence zones, priced low → high.

    Members join a zone while they stay within `tol_pct` of spot's value of the
    zone's LOW — complete linkage, so a chain of near-misses can never drift a
    zone wider than the tolerance it claims. A zone's price is its OI wall's
    strike when it has one (that is where the contracts actually sit), else the
    mean of its members.

    `kind` comes from the member kinds, which build_levels already re-derived
    from spot — so no zone is ever named from a label (R3) by construction.
    Max Pain keeps its magnet kind and the expected-move edges keep their band
    kind; they are not support or resistance.
    """
    if not spot or not levels:
        return []
    tol = abs(spot) * tol_pct / 100
    priced = sorted((l for l in levels if l.get("price") is not None),
                    key=lambda l: l["price"])

    groups: list[list[dict]] = []
    for l in priced:
        if groups and l["price"] - groups[-1][0]["price"] <= tol:
            groups[-1].append(l)
        else:
            groups.append([l])

    zones = []
    for g in groups:
        prices = [m["price"] for m in g]
        wall = next((m for m in g if m["label"].endswith("OI Wall")), None)
        price = wall["price"] if wall else sum(prices) / len(prices)
        kinds = {m["kind"] for m in g}
        if KIND_MAXPAIN in kinds:
            kind = KIND_MAXPAIN
        elif KIND_RANGE in kinds:
            kind = KIND_RANGE
        elif kinds & {KIND_RESISTANCE, KIND_SUPPORT}:
            kind = KIND_RESISTANCE if price > spot else KIND_SUPPORT
        else:
            kind = KIND_PIVOT
        flipped = next((m for m in g if m["crossed"]), None)
        dist = (price - spot) / spot * 100
        zones.append({
            "price": round(price, 1),
            "lo": round(min(prices), 1), "hi": round(max(prices), 1),
            "members": [dict(m) for m in g],
            "kind": kind,
            "crossed": flipped is not None,
            "state": ("BROKEN" if flipped else
                      "AT PRICE" if abs(dist) <= _AT_PRICE_PCT else "INTACT"),
            "dist_pct": round(dist, 2),
        })
        if flipped:
            zones[-1]["flip"] = (f"was {_SIDE.get(flipped['kind'], flipped['kind'])}, "
                                 f"now {flipped['kind']}")

    above = min((z for z in zones if z["price"] > spot), key=lambda z: z["price"], default=None)
    below = max((z for z in zones if z["price"] < spot), key=lambda z: z["price"], default=None)
    for z in zones:
        z["strength"], z["basis"] = zone_strength(
            z, spot, em, walls_oi, nearest=z is above or z is below)
    return zones


def structure_state(spot: float, zones: list[dict], pivots: dict | None = None) -> dict:
    """
    One soft signal for the whole level map, first rule that matches:

      REVIEW  — at least one zone flipped side since the prior session.
      WATCH   — spot is within 0.25% of a zone scoring 60 or more.
      HOLD    — neither.

    HOLD/WATCH/REVIEW describe THE STATE OF THE LEVEL MAP, never a position:
    nothing here is addressed to the reader and no verb is directed at them.
    With no levels there is nothing to describe, and it says so rather than
    reporting a state it cannot support (R17).
    """
    if not spot or not zones:
        return {"signal": None,
                "headline": "Level map unavailable — no levels were computed for this session.",
                "basis": "no levels available to compare against spot."}

    def labels(z: dict) -> str:
        return " + ".join(m["label"] for m in z["members"])

    broken = [z for z in zones if z["crossed"]]
    if broken:
        return {
            "signal": "REVIEW",
            "headline": (f"{len(broken)} level{'s' if len(broken) > 1 else ''} flipped side "
                         f"since the prior session; the level map has changed."),
            "basis": "; ".join(f"{labels(z)} {_px(z['price'])} {z['flip']}" for z in broken) + ".",
        }

    near = [z for z in zones
            if z["strength"] >= _WATCH_STRENGTH and abs(z["dist_pct"]) <= _WATCH_PCT]
    if near:
        z = min(near, key=lambda z: abs(z["dist_pct"]))
        return {
            "signal": "WATCH",
            "headline": (f"Spot {_px(spot)} is {abs(z['dist_pct']):.2f}% from {labels(z)} "
                         f"at {_px(z['price'])}, strength {z['strength']}/100."),
            "basis": z["basis"],
        }

    above = min((z for z in zones if z["price"] > spot), key=lambda z: z["price"], default=None)
    below = max((z for z in zones if z["price"] < spot), key=lambda z: z["price"], default=None)
    head, banded = f"Spot {_px(spot)}", False
    if pivots and pivots.get("S1") is not None and pivots.get("R1") is not None:
        head += (" is inside the S1-R1 pivot band" if pivots["S1"] <= spot <= pivots["R1"]
                 else (" is above the R1 pivot" if spot > pivots["R1"] else " is below the S1 pivot"))
        banded = True
    gaps = []
    if above:
        gaps.append(f"{abs(above['dist_pct']):.2f}% below {labels(above)} {_px(above['price'])}")
    if below:
        gaps.append(f"{abs(below['dist_pct']):.2f}% above {labels(below)} {_px(below['price'])}")
    if gaps:
        head += (", " if banded else " sits ") + " and ".join(gaps)
    return {
        "signal": "HOLD",
        "headline": head + "; no level crossed today.",
        "basis": (f"no zone within {_WATCH_PCT}% of spot scores {_WATCH_STRENGTH} or more, "
                  f"and none of the {len(zones)} zones has been crossed."),
    }


# ----------------------------------------------------------------------
# OI build-up quadrants, delta aggregates, percentile context (pure, no I/O)
# ----------------------------------------------------------------------

# Where the per-leg price change that classifies a quadrant came from. Upstox
# returns `close_price` (the prior settled close) on every leg alongside
# `prev_oi`, so the real per-leg change is available and nothing is proxied.
BUILDUP_BASIS_LEG = "leg price"

QUADRANTS = ("long_buildup", "short_buildup", "short_covering", "long_unwinding")

_PCTILE_MIN = 60         # fewer stored sessions than this → no percentile at all


def buildup(price_chg: float | None, oi_chg: float | None) -> str | None:
    """
    The four standard OI build-up quadrants, from price change × OI change:

        price ↑  OI ↑   long build-up     — new longs opening
        price ↓  OI ↑   short build-up    — new shorts opening
        price ↑  OI ↓   short covering    — shorts closing
        price ↓  OI ↓   long unwinding    — longs closing

    None when either input is missing OR exactly zero: a flat print is not a
    quadrant, and picking one anyway would be an invented read (R17).
    """
    if not price_chg or not oi_chg:
        return None
    if price_chg > 0:
        return "long_buildup" if oi_chg > 0 else "short_covering"
    return "short_buildup" if oi_chg > 0 else "long_unwinding"


def classify_buildup(strikes: list[dict], basis: str = BUILDUP_BASIS_LEG) -> dict:
    """
    Tag every leg with its quadrant IN PLACE and return the aggregate.

    Per-strike quadrants are what the chain renders; the aggregate is what the
    page reads. Both come out of one pass, so the two can never disagree.

    `basis` names where the price change came from and travels with the
    numbers, so the UI can state the provenance rather than imply a precision
    the classification does not have (R17). It is None when nothing could be
    classified at all — no basis, because there was no measurement.

    Returns {"call"/"put": {quadrant: {"legs", "oi_change"}},
             "unclassified": {"call","put"}, "basis": str | None}
    """
    out = {side: {q: {"legs": 0, "oi_change": 0.0} for q in QUADRANTS}
           for side in ("call", "put")}
    unclassified = {"call": 0, "put": 0}

    for s in strikes or []:
        for side in ("call", "put"):
            leg = s.get(side)
            if not leg:
                continue
            q = buildup(leg.get("price_chg"), leg.get("oi_change"))
            leg["buildup"] = q
            if q is None:
                unclassified[side] += 1
                continue
            out[side][q]["legs"] += 1
            out[side][q]["oi_change"] += leg["oi_change"]

    classified = sum(out[s][q]["legs"] for s in out for q in QUADRANTS)
    for side in out.values():
        for cell in side.values():
            cell["oi_change"] = round(cell["oi_change"], 1)
    out["unclassified"] = unclassified
    out["basis"] = basis if classified else None
    return out


def delta_weighted_oi(strikes: list[dict]) -> dict:
    """
    Σ |delta| × OI per side — open interest weighted by how much each contract
    actually tracks the underlying, which a raw OI sum does not say.

    A leg without a live delta is SKIPPED and counted in `legs_without_greeks`,
    never folded in as delta 0 (R17). `services.upstox._greek` already nulls
    Upstox's literal 0.0 thin-quote print, so that artifact lands here too.
    Returns None for a side where no leg had a delta at all.
    """
    out = {"call": 0.0, "put": 0.0, "legs_without_greeks": 0}
    counted = {"call": 0, "put": 0}
    for s in strikes or []:
        for side in ("call", "put"):
            leg = s.get(side) or {}
            d = leg.get("delta")
            if not d:
                out["legs_without_greeks"] += 1
                continue
            if leg.get("oi") is None:
                continue
            out[side] += abs(d) * leg["oi"]
            counted[side] += 1
    for side in ("call", "put"):
        out[side] = round(out[side], 1) if counted[side] else None
    return out


def percentile_rank(series: list[float], value: float | None) -> float | None:
    """
    Where `value` sits inside its own history, 0-100 (the share of the series
    at or below it). A bare "India VIX 11.8" says nothing; "18th percentile of
    252 sessions" says the whole thing.

    None when fewer than 60 points are stored — a percentile of five samples is
    a number, not a measurement, and the caller must say "unavailable" (R17).
    """
    if value is None:
        return None
    vals = sorted(v for v in (series or []) if v is not None)
    if len(vals) < _PCTILE_MIN:
        return None
    return round(bisect_right(vals, value) / len(vals) * 100, 1)


# ----------------------------------------------------------------------
# Top-level composition
# ----------------------------------------------------------------------

def analyze(chain: dict, *, prev_ohlc: dict | None = None,
            vix: float | None = None, pivots: dict | None = None,
            structure: dict | None = None) -> dict:
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
    levels = build_levels(spot, mp, walls, em, pivots=pivots, prev=prev_ohlc,
                          structure=structure)
    zones = level_zones(spot, levels, em=em, walls_oi=wall_oi_context(strikes, walls))
    bu = classify_buildup(strikes)   # also tags each leg with its quadrant

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
        "zones": zones,
        "structure": structure_state(spot, zones, pivots),
        "buildup_summary": bu,
        "buildup_basis": bu["basis"],
        "delta_oi": delta_weighted_oi(strikes),
    }


__all__ = [
    "atm_strike", "pcr_oi", "max_pain", "oi_walls", "expected_move", "atm_iv",
    "options_flow_bias", "strategy_concept", "build_levels", "analyze", "Level",
    "wall_oi_context", "level_zones", "zone_strength", "structure_state",
    "ZONE_TOL_PCT",
    "buildup", "classify_buildup", "delta_weighted_oi", "percentile_rank",
    "BUILDUP_BASIS_LEG", "QUADRANTS",
]
