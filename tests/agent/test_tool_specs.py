"""Tests for MCP -> OpenAI tool def conversion (atomic redesign)."""

from dataclasses import dataclass

from deribit_trading.agent.tool_specs import (
    PHASE_1_READ_ONLY_TOOLS,
    READ_ONLY_TOOLS,
    TOOL_DESCRIPTIONS_OVERRIDE,
    WRITE_TOOLS,
    WRITE_TOOLS_GATED,
    convert_mcp_to_openai,
    _annotate_optionals,
)


@dataclass
class _MockMcpTool:
    """Stand-in for mcp.types.Tool to keep tests independent of MCP package."""

    name: str
    description: str
    inputSchema: dict


_NEW_TOOLS = [
    "list_instruments", "list_expiries",
    "get_quote", "get_orderbook", "get_candles",
    "get_market_snapshot",
    "get_positions", "get_balance", "get_pnl_breakdown", "get_risk_status",
    "get_system_status",
    "analyze_option_combo",
]

_OLD_TOOLS_REMOVED = [
    "get_ticker", "get_option_chain", "get_vol_surface",
    "get_portfolio", "get_pnl_attribution", "get_equity_curve",
]


def _build_mock_chain() -> list[_MockMcpTool]:
    """Mock the new 12 read-only tools + 5 write tools + a few legacy names."""
    schemas = {
        "list_instruments": {"type": "object", "properties": {"currency": {"type": "string"}, "kind": {"type": "string"}}, "required": ["currency"]},
        "list_expiries": {"type": "object", "properties": {"currency": {"type": "string"}}, "required": ["currency"]},
        "get_quote": {"type": "object", "properties": {"instrument": {"type": "string"}}, "required": ["instrument"]},
        "get_orderbook": {"type": "object", "properties": {"instrument": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["instrument"]},
        "get_candles": {"type": "object", "properties": {"instrument": {"type": "string"}, "resolution": {"type": "string"}, "period": {"type": "string"}}},
        "get_market_snapshot": {"type": "object", "properties": {"currency": {"type": "string"}, "kind": {"type": "string"}}, "required": ["currency"]},
        "get_positions": {"type": "object", "properties": {"currency": {"type": "string"}}},
        "get_balance": {"type": "object", "properties": {"currency": {"type": "string"}}},
        "get_pnl_breakdown": {"type": "object", "properties": {"currency": {"type": "string"}}},
        "get_risk_status": {"type": "object", "properties": {}},
        "get_system_status": {"type": "object", "properties": {}},
        "analyze_option_combo": {"type": "object", "properties": {"legs": {"type": "array"}}, "required": ["legs"]},
    }
    chain = [_MockMcpTool(n, "short server desc", schemas[n]) for n in _NEW_TOOLS]
    # Write tools — must NOT pass through
    for n in WRITE_TOOLS:
        chain.append(_MockMcpTool(n, "write tool", {"type": "object", "properties": {}}))
    # Legacy names — must NOT pass through
    for n in _OLD_TOOLS_REMOVED:
        chain.append(_MockMcpTool(n, "legacy", {"type": "object", "properties": {}}))
    return chain


def test_whitelist_size_and_membership():
    assert len(PHASE_1_READ_ONLY_TOOLS) == 12
    assert set(PHASE_1_READ_ONLY_TOOLS) == set(_NEW_TOOLS)


def test_old_tool_names_removed_from_whitelist():
    for legacy in _OLD_TOOLS_REMOVED:
        assert legacy not in PHASE_1_READ_ONLY_TOOLS


def test_write_tools_excluded():
    expected = {"place_order", "cancel_order", "smart_order", "cancel_smart_order", "switch_env"}
    assert set(WRITE_TOOLS) == expected
    assert not (set(PHASE_1_READ_ONLY_TOOLS) & set(WRITE_TOOLS))


def test_read_only_tools_alias_matches_phase1():
    assert READ_ONLY_TOOLS == PHASE_1_READ_ONLY_TOOLS


def test_write_tools_gated_does_not_include_switch_env():
    expected = {"place_order", "cancel_order", "smart_order", "cancel_smart_order"}
    assert set(WRITE_TOOLS_GATED) == expected
    assert "switch_env" not in WRITE_TOOLS_GATED


def test_convert_default_write_disabled_returns_only_read_tools():
    """write_enabled defaults to False → only read tools."""
    tools = convert_mcp_to_openai(_build_mock_chain())
    names = {t["function"]["name"] for t in tools}
    assert names == set(READ_ONLY_TOOLS)
    for n in WRITE_TOOLS_GATED:
        assert n not in names


def test_convert_write_enabled_includes_write_tools():
    """write_enabled=True → reads + 4 gated writes (still no switch_env)."""
    # Build a chain that also includes write tools as mock entries
    from dataclasses import dataclass

    @dataclass
    class _T:
        name: str
        description: str = "x"
        inputSchema: dict = None

        def __post_init__(self):
            if self.inputSchema is None:
                self.inputSchema = {"type": "object", "properties": {}}

    chain = _build_mock_chain()
    # Already includes write tools and switch_env via WRITE_TOOLS injection
    tools = convert_mcp_to_openai(chain, write_enabled=True)
    names = {t["function"]["name"] for t in tools}
    assert set(READ_ONLY_TOOLS) <= names
    assert set(WRITE_TOOLS_GATED) <= names
    # switch_env still excluded
    assert "switch_env" not in names


def test_write_tools_have_descriptions_with_confirmation_notice():
    """The 4 gated write tools must mention 'CONFIRMATION CARD' in description."""
    for name in WRITE_TOOLS_GATED:
        desc = TOOL_DESCRIPTIONS_OVERRIDE.get(name, "")
        assert "CONFIRMATION CARD" in desc, f"{name} description missing confirmation notice"


def test_convert_only_returns_whitelist():
    tools = convert_mcp_to_openai(_build_mock_chain())
    names = [t["function"]["name"] for t in tools]
    assert len(names) == 12
    assert set(names) == set(PHASE_1_READ_ONLY_TOOLS)
    for n in WRITE_TOOLS:
        assert n not in names
    for n in _OLD_TOOLS_REMOVED:
        assert n not in names


def test_each_tool_has_openai_schema():
    tools = convert_mcp_to_openai(_build_mock_chain())
    for t in tools:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "description" in t["function"]
        assert "parameters" in t["function"]
        assert t["function"]["parameters"]["type"] == "object"


def test_descriptions_overridden_and_long():
    tools = convert_mcp_to_openai(_build_mock_chain())
    for t in tools:
        desc = t["function"]["description"]
        assert desc != "short server desc"
        assert len(desc) >= 250, (
            f"{t['function']['name']} description too short: {len(desc)} chars"
        )


def test_all_whitelisted_tools_have_override():
    for name in PHASE_1_READ_ONLY_TOOLS:
        assert name in TOOL_DESCRIPTIONS_OVERRIDE, f"Missing override for {name}"


def test_naming_convention_verb_prefixes():
    for n in PHASE_1_READ_ONLY_TOOLS:
        assert n.startswith(("list_", "get_", "analyze_")), f"{n} violates verb prefix"


def test_optional_params_annotated():
    schema = {
        "type": "object",
        "properties": {
            "currency": {"type": "string", "description": "BTC or ETH"},
            "kind": {"type": "string", "description": "Filter"},
        },
        "required": ["currency"],
    }
    annotated = _annotate_optionals(schema)
    assert annotated["properties"]["currency"]["description"] == "BTC or ETH"
    assert annotated["properties"]["kind"]["description"].startswith("Optional. Omit if unknown.")
    assert schema["properties"]["kind"]["description"] == "Filter"


def test_optional_no_description_gets_default():
    schema = {
        "type": "object",
        "properties": {"foo": {"type": "string"}},
        "required": [],
    }
    annotated = _annotate_optionals(schema)
    assert annotated["properties"]["foo"]["description"] == "Optional. Omit if unknown."


def test_annotation_idempotent():
    schema = {
        "type": "object",
        "properties": {
            "foo": {"type": "string", "description": "Optional. Omit if unknown. Already done."},
        },
        "required": [],
    }
    annotated = _annotate_optionals(schema)
    assert annotated["properties"]["foo"]["description"] == "Optional. Omit if unknown. Already done."
