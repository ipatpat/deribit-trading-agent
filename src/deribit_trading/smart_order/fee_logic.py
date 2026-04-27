"""Fee-aware execution logic.

Determines post_only strategy per instrument type and estimates fees.
"""

from __future__ import annotations

from .types import FeeContext


# Standard tier fee rates (basis points → decimal)
FEE_TABLE: dict[str, tuple[float, float]] = {
    # (maker_fee, taker_fee) as fraction of underlying
    "future": (0.0, 0.0005),        # 0 bps / 5 bps
    "perpetual": (0.0, 0.0005),
    "weekly_future": (-0.0001, 0.0005),  # -1 bps / 5 bps (rebate!)
    "option": (0.0003, 0.0003),      # 3 bps / 3 bps (same)
}


def classify_instrument(instrument_name: str) -> str:
    """Classify instrument type from its name."""
    name = instrument_name.upper()
    if "PERPETUAL" in name:
        return "perpetual"
    # Options end with -C or -P (e.g. BTC-27JUN25-70000-C)
    if name.endswith("-C") or name.endswith("-P"):
        return "option"
    # Check if weekly: typically named like BTC-25APR25 (short expiry)
    # For now, treat all non-perpetual futures as regular futures
    return "future"


def build_fee_context(instrument_name: str) -> FeeContext:
    """Build FeeContext for an instrument."""
    inst_type = classify_instrument(instrument_name)
    maker_fee, taker_fee = FEE_TABLE.get(inst_type, (0.0, 0.0005))

    # post_only only makes sense when maker < taker
    should_post_only = maker_fee < taker_fee

    return FeeContext(
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        is_post_only=should_post_only,
        instrument_type=inst_type,
    )


def should_use_post_only(fee_context: FeeContext) -> bool:
    """Whether to enforce post_only for this instrument."""
    return fee_context.maker_fee < fee_context.taker_fee


def estimate_fee(
    amount_usd: float,
    fee_rate: float,
    option_price: float | None = None,
    instrument_type: str = "future",
) -> float:
    """Estimate fee in USD.

    For options, applies the 12.5% cap on option price.
    """
    if instrument_type == "option" and option_price is not None:
        capped_rate = min(fee_rate, 0.125 * option_price)
        return amount_usd * capped_rate

    return amount_usd * abs(fee_rate)


def fee_savings_estimate(
    amount_usd: float,
    fee_context: FeeContext,
    option_price: float | None = None,
) -> dict[str, float]:
    """Estimate maker vs taker fee and potential savings."""
    maker = estimate_fee(amount_usd, fee_context.maker_fee, option_price, fee_context.instrument_type)
    taker = estimate_fee(amount_usd, fee_context.taker_fee, option_price, fee_context.instrument_type)

    return {
        "maker_fee": maker,
        "taker_fee": taker,
        "savings": taker - maker,
    }
