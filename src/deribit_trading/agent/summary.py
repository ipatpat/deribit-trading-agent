"""Human-readable summaries for write-tool calls.

Used by the agent loop when yielding `confirmation_required` SSE events so
the frontend ConfirmationCard can show a clear, scannable description of
what the user is about to authorise.

The summaries are intentionally brief and parameter-dense (instrument /
direction / amount / price / estimated notional). They are NOT meant to
include disclaimers or trade analysis — that's the LLM's job before the
tool call.
"""

from __future__ import annotations

from typing import Any


def _safe(args: dict[str, Any], key: str, default: str = "?") -> str:
    """Pull a value from args, coerce to string. Used inside f-strings."""
    v = args.get(key)
    return str(v) if v is not None else default


def _format_amount(args: dict[str, Any]) -> str:
    """Format amount with order_type-aware unit hint."""
    amt = args.get("amount", "?")
    order_type = args.get("order_type", "limit")
    if order_type == "market":
        return f"{amt} (market)"
    price = args.get("price")
    if price is not None:
        return f"{amt} @ ${price:,}"
    return str(amt)


def _summarize_place_order(args: dict[str, Any]) -> str:
    instrument = _safe(args, "instrument_name")
    direction = _safe(args, "direction").upper()
    amount_part = _format_amount(args)
    label = args.get("label")
    parts = [f"{direction} {instrument}", amount_part]
    if label:
        parts.append(f"label='{label}'")
    return " · ".join(parts)


def _summarize_cancel_order(args: dict[str, Any]) -> str:
    return f"Cancel order_id={_safe(args, 'order_id')}"


def _summarize_smart_order(args: dict[str, Any]) -> str:
    instrument = _safe(args, "instrument_name")
    direction = _safe(args, "direction").upper()
    amount = _safe(args, "amount")
    algorithm = args.get("algorithm", "tick-chaser")
    intent = args.get("intent")
    parts = [f"Smart {direction} {instrument}", f"amount={amount}", f"algo={algorithm}"]
    if intent:
        parts.append(f"intent={intent}")
    if args.get("price_limit") is not None:
        parts.append(f"limit=${args['price_limit']:,}")
    return " · ".join(parts)


def _summarize_cancel_smart_order(args: dict[str, Any]) -> str:
    return f"Cancel smart order id={_safe(args, 'id')}"


_SUMMARIZERS = {
    "place_order": _summarize_place_order,
    "cancel_order": _summarize_cancel_order,
    "smart_order": _summarize_smart_order,
    "cancel_smart_order": _summarize_cancel_smart_order,
}


def summarize(tool_name: str, args: dict[str, Any]) -> str:
    """Return a one-line human-readable summary of a write-tool invocation.

    Falls back to "<tool_name>(args...)" if the tool isn't recognised.
    Never raises — defensive against malformed args.
    """
    summarizer = _SUMMARIZERS.get(tool_name)
    if summarizer is None:
        return f"{tool_name}({args})"
    try:
        return summarizer(args)
    except Exception:  # noqa: BLE001 — never raise from a summarizer
        return f"{tool_name}({args})"
