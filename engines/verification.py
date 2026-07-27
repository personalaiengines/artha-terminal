"""
ARTHA Terminal - Verification Membrane
Cross-source consensus for price-critical fields.

Fetches from two independent sources (Upstox + Yahoo) and computes
relative divergence:
- Both present, divergence <= 1.5%  -> VERIFIED (green, consensus mean)
- One source only                  -> SINGLE_SOURCE (amber)
- Divergence > 1.5%                -> CONFLICT (red, both values shown)

No field reaches the UI without a provenance status.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Tuple
import logging

logger = logging.getLogger("engines.verification")


class VerifiedStatus(Enum):
    """Provenance/verification status for a field."""
    VERIFIED = "VERIFIED"          # Two sources agree (green)
    SINGLE_SOURCE = "SINGLE_SOURCE"  # Only one source available (amber)
    CONFLICT = "CONFLICT"          # Sources diverge beyond threshold (red)
    PENDING = "PENDING"            # Not yet verified


@dataclass
class VerifiedField:
    """A price-critical field with provenance metadata."""
    field_name: str
    upstox_value: Optional[float]
    yahoo_value: Optional[float]
    consensus_value: Optional[float]  # The value to expose to UI
    status: VerifiedStatus
    divergence_pct: Optional[float]   # Only set when both sources present


class VerificationMembrane:
    """
    Cross-source consensus verification.

    The epistemic guarantee behind "data is real, not made up":
    no field reaches the UI without a provenance status.
    """

    DIVERGENCE_THRESHOLD = 1.5  # Percent - from build guide

    def __init__(self):
        pass

    def verify_price(
        self,
        upstox_price: Optional[float],
        yahoo_price: Optional[float],
        symbol: str = None,
    ) -> VerifiedField:
        """
        Verify a price field across two sources.

        Args:
            upstox_price: Price from Upstox (broker-grade primary)
            yahoo_price: Price from Yahoo Finance (independent secondary)
            symbol: For logging

        Returns:
            VerifiedField with consensus value and status
        """
        return self.verify_generic(
            field_name="price",
            primary=upstox_price,
            secondary=yahoo_price,
            symbol=symbol,
        )

    def verify_generic(
        self,
        field_name: str,
        primary: Optional[float],
        secondary: Optional[float],
        symbol: str = None,
    ) -> VerifiedField:
        """
        Verify any numeric field across two sources.

        Uses primary (Upstox) as the broker-grade authority but
        surfaces consensus mean when both sources agree.

        Args:
            field_name: Name of the field being verified
            primary: Primary source value (Upstox)
            secondary: Secondary source value (Yahoo)
            symbol: For logging

        Returns:
            VerifiedField with consensus and status
        """
        # Case 1: Both sources present
        if primary is not None and secondary is not None:
            divergence = self._compute_divergence(primary, secondary)

            if divergence is None:
                return VerifiedField(
                    field_name=field_name,
                    upstox_value=primary,
                    yahoo_value=secondary,
                    consensus_value=None,
                    status=VerifiedStatus.PENDING,
                    divergence_pct=None,
                )

            if divergence <= self.DIVERGENCE_THRESHOLD:
                # Consensus - use mean of both sources
                consensus = (primary + secondary) / 2
                status = VerifiedStatus.VERIFIED
                logger.debug(
                    f"{symbol or ''} {field_name}: VERIFIED "
                    f"(upstox={primary}, yahoo={secondary}, div={divergence:.2f}%)"
                )
            else:
                # Conflict - expose both, use primary as default
                consensus = primary  # Broker-grade authority
                status = VerifiedStatus.CONFLICT
                logger.warning(
                    f"{symbol or ''} {field_name}: CONFLICT "
                    f"(upstox={primary}, yahoo={secondary}, div={divergence:.2f}%)"
                )

            return VerifiedField(
                field_name=field_name,
                upstox_value=primary,
                yahoo_value=secondary,
                consensus_value=consensus,
                status=status,
                divergence_pct=divergence,
            )

        # Case 2: Only primary available
        elif primary is not None:
            return VerifiedField(
                field_name=field_name,
                upstox_value=primary,
                yahoo_value=None,
                consensus_value=primary,
                status=VerifiedStatus.SINGLE_SOURCE,
                divergence_pct=None,
            )

        # Case 3: Only secondary available
        elif secondary is not None:
            return VerifiedField(
                field_name=field_name,
                upstox_value=None,
                yahoo_value=secondary,
                consensus_value=secondary,
                status=VerifiedStatus.SINGLE_SOURCE,
                divergence_pct=None,
            )

        # Case 4: Neither available
        else:
            return VerifiedField(
                field_name=field_name,
                upstox_value=None,
                yahoo_value=None,
                consensus_value=None,
                status=VerifiedStatus.PENDING,
                divergence_pct=None,
            )

    def _compute_divergence(
        self,
        val_a: float,
        val_b: float,
    ) -> Optional[float]:
        """
        Compute relative divergence between two values.

        Uses the larger value as the denominator for symmetric handling
        of both near-zero and large values.

        Returns:
            Divergence as percentage, or None if computation impossible
        """
        if val_a is None or val_b is None:
            return None

        # Avoid division by zero
        if val_a == 0 and val_b == 0:
            return 0.0
        if val_a == 0 and val_b != 0:
            return 100.0
        if val_b == 0 and val_a != 0:
            return 100.0

        # Use the larger absolute value as denominator
        denom = max(abs(val_a), abs(val_b))
        return abs(val_a - val_b) / denom * 100

    def verify_quote(
        self,
        upstox_quote: Optional[dict],
        yahoo_quote: Optional[dict],
        symbol: str = None,
    ) -> Dict[str, VerifiedField]:
        """
        Verify multiple fields in a quote object.

        Fields verified: current_price, fifty_two_week_high,
        fifty_two_week_low, market_cap

        Args:
            upstox_quote: Quote dict from Upstox
            yahoo_quote: Quote dict from Yahoo Finance
            symbol: For logging

        Returns:
            Dictionary of field_name -> VerifiedField
        """
        fields_to_verify = [
            ("current_price", "current_price", "currentPrice"),
            ("fifty_two_week_high", "fifty_two_week_high", "fiftyTwoWeekHigh"),
            ("fifty_two_week_low", "fifty_two_week_low", "fiftyTwoWeekLow"),
            ("market_cap", "market_cap", "marketCap"),
        ]

        results = {}

        for field_name, upstox_key, yahoo_key in fields_to_verify:
            upstox_val = None
            yahoo_val = None

            if upstox_quote:
                upstox_val = self._extract_value(upstox_quote, upstox_key, field_name)
            if yahoo_quote:
                yahoo_val = self._extract_value(yahoo_quote, yahoo_key, field_name)

            results[field_name] = self.verify_generic(
                field_name=field_name,
                primary=upstox_val,
                secondary=yahoo_val,
                symbol=symbol,
            )

        return results

    def _extract_value(self, quote: dict, *keys) -> Optional[float]:
        """Extract a numeric value from a quote dict, trying multiple keys."""
        for key in keys:
            if key in quote and quote[key] is not None:
                try:
                    return float(quote[key])
                except (ValueError, TypeError):
                    continue
        return None

    def get_ui_metadata(self, field: VerifiedField) -> dict:
        """
        Get UI-ready metadata for a verified field.

        Returns color, status, and both source values for rendering.
        """
        color_map = {
            VerifiedStatus.VERIFIED: "surge",       # green
            VerifiedStatus.SINGLE_SOURCE: "volt",   # amber/yellow
            VerifiedStatus.CONFLICT: "flare",       # red
            VerifiedStatus.PENDING: "haze",         # muted
        }

        return {
            "field_name": field.field_name,
            "value": field.consensus_value,
            "status": field.status.value,
            "color": color_map.get(field.status, "haze"),
            "upstox_value": field.upstox_value,
            "yahoo_value": field.yahoo_value,
            "divergence_pct": field.divergence_pct,
            "label": self._get_status_label(field.status),
        }

    def _get_status_label(self, status: VerifiedStatus) -> str:
        """Human-readable status label for UI."""
        labels = {
            VerifiedStatus.VERIFIED: "Verified",
            VerifiedStatus.SINGLE_SOURCE: "Single Source",
            VerifiedStatus.CONFLICT: "Source Conflict",
            VerifiedStatus.PENDING: "Awaiting Data",
        }
        return labels.get(status, status.value)