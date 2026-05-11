"""Tests for parse_instrument_kind helper."""

import pytest

from deribit_trading.models import parse_instrument_kind


@pytest.mark.parametrize(
    "name, expected",
    [
        ("BTC-PERPETUAL", "perpetual"),
        ("ETH-PERPETUAL", "perpetual"),
        ("BTC-27JUN26", "future"),
        ("ETH-25DEC26", "future"),
        ("BTC-27JUN26-70000-C", "option"),
        ("BTC-27JUN26-70000-P", "option"),
        ("ETH-25DEC26-3000-C", "option"),
        ("BTC_USDC", "unknown"),
        ("nonsense", "unknown"),
        ("", "unknown"),
    ],
)
def test_parse_instrument_kind(name, expected):
    assert parse_instrument_kind(name) == expected
