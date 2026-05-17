"""Tests for write-tool confirmation summary generator."""

from deribit_trading.agent.summary import summarize


def test_place_order_summary_contains_key_fields():
    s = summarize(
        "place_order",
        {
            "instrument_name": "BTC-PERPETUAL",
            "direction": "buy",
            "amount": 1.0,
            "order_type": "limit",
            "price": 80000,
        },
    )
    assert "BUY" in s
    assert "BTC-PERPETUAL" in s
    assert "1" in s
    assert "80,000" in s or "80000" in s


def test_place_order_market_marks_market():
    s = summarize(
        "place_order",
        {
            "instrument_name": "ETH-PERPETUAL",
            "direction": "sell",
            "amount": 0.5,
            "order_type": "market",
        },
    )
    assert "SELL" in s and "ETH-PERPETUAL" in s and "market" in s.lower()


def test_cancel_order_summary():
    s = summarize("cancel_order", {"order_id": "ord_123"})
    assert "ord_123" in s
    assert "Cancel" in s


def test_smart_order_summary():
    s = summarize(
        "smart_order",
        {
            "instrument_name": "BTC-PERPETUAL",
            "direction": "buy",
            "amount": 100,
            "intent": "standard",
            "overrides": {"t_patience_ms": 45000, "max_cross_levels": 2},
        },
    )
    assert "BUY" in s and "BTC-PERPETUAL" in s
    assert "intent=standard" in s
    assert "patience=45000ms" in s
    assert "cross≤2" in s


def test_smart_order_summary_default_intent():
    s = summarize(
        "smart_order",
        {"instrument_name": "ETH-PERPETUAL", "direction": "sell", "amount": 1},
    )
    assert "intent=standard" in s  # defaults to standard when missing


def test_cancel_smart_order_summary():
    s = summarize("cancel_smart_order", {"id": "so_abc"})
    assert "so_abc" in s


def test_unknown_tool_does_not_raise():
    s = summarize("mystery_tool", {"foo": "bar"})
    assert "mystery_tool" in s


def test_malformed_args_does_not_raise():
    # Missing required keys — summarizer should fall back rather than raise.
    s = summarize("place_order", {})
    assert isinstance(s, str) and len(s) > 0
