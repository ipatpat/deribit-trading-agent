"""Tests for slim system prompt construction (atomic redesign)."""

from deribit_trading.agent.system_prompt import (
    SYSTEM_PROMPT_TEMPLATE,
    TIER_1_KNOWLEDGE,
    build_system_prompt,
)


def test_role_first_section():
    prompt = build_system_prompt({"route": "/", "instrument": None})
    first_line = prompt.splitlines()[0]
    assert first_line == "ROLE"
    assert "Not financial advice" not in prompt


def test_required_sections_present():
    prompt = build_system_prompt()
    for section in (
        "ROLE", "GOAL", "ANCHOR", "INTERNAL CHECKLIST",
        "KNOWLEDGE", "CONTEXT", "CONSTRAINTS",
    ):
        assert section in prompt, f"Missing section: {section}"


def test_phase_1_readonly_declared():
    prompt = build_system_prompt()
    assert "Phase 1" in prompt and "read-only" in prompt
    assert "CANNOT place" in prompt or "cannot place" in prompt.lower()


def test_anchor_three_principles():
    prompt = build_system_prompt()
    assert "tool data" in prompt.lower()
    assert "predict price direction" in prompt.lower() or "refuse to predict" in prompt.lower()
    assert "trade-offs" in prompt.lower() or "buy/sell" in prompt.lower()


def test_internal_checklist_uses_atomic_tool_names():
    """Checklist must reference atomic tool names, not legacy ones."""
    prompt = build_system_prompt()
    lower = prompt.lower()
    # Atomic names referenced
    assert "get_market_snapshot" in lower or "get_quote" in lower
    assert "get_positions" in lower or "get_balance" in lower
    # Legacy names absent
    assert "get_ticker" not in lower
    assert "get_portfolio" not in lower
    assert "get_option_chain" not in lower


# ── Tier 1 retained facts ─────────────────────────────────────────────────────


def test_tier_1_reverse_contract_face_values_retained():
    assert "$10/contract" in TIER_1_KNOWLEDGE
    assert "$1/contract" in TIER_1_KNOWLEDGE


def test_tier_1_greeks_retained():
    for g in ("Delta", "Gamma", "Vega", "Theta"):
        assert g in TIER_1_KNOWLEDGE


def test_tier_1_instrument_naming_retained():
    assert "PERPETUAL" in TIER_1_KNOWLEDGE
    assert "27JUN26" in TIER_1_KNOWLEDGE


# ── Tier 1 facts intentionally removed ────────────────────────────────────────


def test_tier_1_smart_order_intents_removed():
    """Smart Order intent details belong in get_system_status / docs, not Tier 1."""
    lower = TIER_1_KNOWLEDGE.lower()
    # The standalone descriptors should be gone (we may still mention "PERPETUAL"
    # which contains "u","r","g","e","n","t" letters individually so use exact word boundary)
    import re
    assert not re.search(r"\bsmart order\b", lower)
    assert "post-only at best bid" not in lower
    assert "ioc sweep" not in lower


def test_tier_1_strategy_roster_removed():
    """Full strategy roster (straddle / condor / covered call / vertical / calendar)
    is no longer in Tier 1; the agent learns from analyze_option_combo + reasoning."""
    lower = TIER_1_KNOWLEDGE.lower()
    for s in ("straddle", "iron condor", "covered call", "calendar spread", "vertical spread"):
        assert s not in lower, f"strategy '{s}' should be removed from Tier 1"


def test_tier_1_fee_numbers_removed():
    """Maker/taker fee numbers belong in get_system_status, not Tier 1."""
    lower = TIER_1_KNOWLEDGE.lower()
    assert "maker -0.01" not in lower
    assert "taker +0.05" not in lower
    assert "0.0003 btc/contract" not in lower


def test_tier_1_funding_8h_detail_removed():
    """Funding-rate 8h detail is removable (agent can ask via get_quote/funding_8h)."""
    assert "every 8h" not in TIER_1_KNOWLEDGE.lower()
    assert "settled every" not in TIER_1_KNOWLEDGE.lower()


def test_tier_1_data_hygiene_section_removed():
    lower = TIER_1_KNOWLEDGE.lower()
    assert "data hygiene" not in lower
    assert "treat as illiquid" not in lower


# ── Volume budgets ────────────────────────────────────────────────────────────


def test_tier_1_size_budget():
    assert len(TIER_1_KNOWLEDGE) <= 3000, (
        f"Tier 1 too large: {len(TIER_1_KNOWLEDGE)} chars (limit 3000)"
    )


def test_total_prompt_size_budget():
    prompt = build_system_prompt({"route": "/", "instrument": None})
    assert len(prompt) <= 4000, f"Prompt too large: {len(prompt)} chars (limit 4000)"


# ── Context injection ────────────────────────────────────────────────────────


def test_context_injection_with_instrument():
    prompt = build_system_prompt({"route": "/futures", "instrument": "BTC-PERPETUAL"})
    assert "Current page: /futures" in prompt
    assert "Selected instrument: BTC-PERPETUAL" in prompt


def test_context_injection_no_instrument():
    prompt = build_system_prompt({"route": "/", "instrument": None})
    assert "Current page: /" in prompt
    assert "Selected instrument: none" in prompt


def test_context_injection_empty_dict():
    prompt = build_system_prompt({})
    assert "Current page: /" in prompt
    assert "Selected instrument: none" in prompt


def test_context_injection_none():
    prompt = build_system_prompt(None)
    assert "Current page: /" in prompt
    assert "Selected instrument: none" in prompt


def test_template_has_placeholders():
    assert "{tier_1}" in SYSTEM_PROMPT_TEMPLATE
    assert "{route}" in SYSTEM_PROMPT_TEMPLATE
    assert "{instrument}" in SYSTEM_PROMPT_TEMPLATE
