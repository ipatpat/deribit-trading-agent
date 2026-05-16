"""Tests for the streaming agent loop with mocked GLM client."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deribit_trading.agent.llm_client import AgentConfig
from deribit_trading.agent.loop import SSEEvent, ToolDispatcher, agent_chat


# ── Helpers ───────────────────────────────────────────────────────────────────
def _delta(content: str | None = None, tool_calls: list[Any] | None = None, reasoning: str | None = None):
    """Build a chunk delta object."""
    obj = MagicMock()
    obj.content = content
    obj.tool_calls = tool_calls
    # reasoning_content is DeepSeek-reasoner specific; default to None on standard models
    obj.reasoning_content = reasoning
    return obj


def _tool_call_delta(idx: int, tc_id: str | None, name: str | None, args: str | None):
    obj = MagicMock()
    obj.index = idx
    obj.id = tc_id
    obj.function = MagicMock()
    obj.function.name = name
    obj.function.arguments = args
    return obj


def _chunk(delta_obj=None, finish_reason: str | None = None, usage=None):
    """Build a stream chunk."""
    chunk = MagicMock()
    if delta_obj is not None:
        choice = MagicMock()
        choice.delta = delta_obj
        choice.finish_reason = finish_reason
        chunk.choices = [choice]
    else:
        chunk.choices = []
    chunk.usage = usage
    return chunk


def _usage(prompt: int, completion: int, total: int):
    u = MagicMock()
    u.prompt_tokens = prompt
    u.completion_tokens = completion
    u.total_tokens = total
    return u


class _AsyncStream:
    """Wrap a list of chunks as an async iterator."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for c in self._chunks:
            yield c


def _make_client(stream_per_call):
    """Build a mock AsyncOpenAI client.

    stream_per_call: list of chunk lists (one per agent turn).
    """
    client = MagicMock()
    state = {"call_idx": 0}

    async def _create(**kwargs):
        chunks = stream_per_call[state["call_idx"]]
        state["call_idx"] += 1
        return _AsyncStream(chunks)

    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = _create
    return client


CFG = AgentConfig(endpoint="http://x", model="glm-4-plus", api_key="k")


# ── SSEEvent serialization ────────────────────────────────────────────────────
def test_sse_event_serialization():
    e = SSEEvent("text_delta", {"delta": "hi"})
    s = e.to_sse()
    assert s.startswith("event: text_delta\n")
    assert "data: " in s
    assert s.endswith("\n\n")


# ── Single-turn (no tool call) ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_single_turn_no_tool_call_done():
    chunks = [
        _chunk(_delta(content="Hello "), finish_reason=None),
        _chunk(_delta(content="world"), finish_reason="stop"),
        _chunk(usage=_usage(10, 5, 15)),
    ]
    client = _make_client([chunks])
    dispatcher = ToolDispatcher(AsyncMock())

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "hi"}],
        tools=[], dispatcher=dispatcher, max_turns=15,
    ):
        events.append(ev)

    # Two text_delta + done
    assert events[0].event == "text_delta"
    assert events[0].data["delta"] == "Hello "
    assert events[1].event == "text_delta"
    assert events[1].data["delta"] == "world"
    assert events[-1].event == "done"
    assert events[-1].data["finish_reason"] == "stop"
    assert events[-1].data["usage"]["total_tokens"] == 15


# ── Multi-turn with tool call ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_multi_turn_tool_call_then_final():
    # Turn 1: emit a tool_call
    turn1 = [
        _chunk(_delta(tool_calls=[_tool_call_delta(0, "tc_1", "get_balance", '{"currency": "BTC"}')])),
        _chunk(_delta(), finish_reason="tool_calls"),
    ]
    # Turn 2: emit final answer
    turn2 = [
        _chunk(_delta(content="Your equity is $428."), finish_reason="stop"),
        _chunk(usage=_usage(20, 10, 30)),
    ]
    client = _make_client([turn1, turn2])

    # Mock dispatcher returns success
    mcp_mock = AsyncMock(return_value=[MagicMock(text='{"equity": 428}', type="text")])
    dispatcher = ToolDispatcher(mcp_mock)

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "what's my equity"}],
        tools=[{"type": "function", "function": {"name": "get_balance", "description": "x", "parameters": {}}}],
        dispatcher=dispatcher, max_turns=15,
    ):
        events.append(ev)

    event_names = [e.event for e in events]
    # Expect: tool_use_start, tool_use_input, tool_use_end, tool_result, text_delta, done
    assert "tool_use_start" in event_names
    assert "tool_use_end" in event_names
    assert "tool_result" in event_names
    assert "text_delta" in event_names
    assert event_names[-1] == "done"
    # Verify mcp dispatch was called once
    mcp_mock.assert_called_once_with("get_balance", {"currency": "BTC"})
    # Verify tool_result is success
    tr = next(e for e in events if e.event == "tool_result")
    assert tr.data["is_error"] is False


# ── Tool exception → is_error → loop continues ────────────────────────────────
@pytest.mark.asyncio
async def test_tool_exception_returns_is_error_then_continues():
    turn1 = [
        _chunk(_delta(tool_calls=[_tool_call_delta(0, "tc_1", "get_quote", '{"instrument": "X"}')])),
        _chunk(_delta(), finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(_delta(content="Sorry, that instrument was invalid."), finish_reason="stop"),
        _chunk(usage=_usage(10, 5, 15)),
    ]
    client = _make_client([turn1, turn2])

    async def _failing_mcp(name, args):
        raise ValueError("instrument not found")

    dispatcher = ToolDispatcher(_failing_mcp)

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "x"}],
        tools=[{"type": "function", "function": {"name": "get_quote", "description": "x", "parameters": {}}}],
        dispatcher=dispatcher, max_turns=15,
    ):
        events.append(ev)

    tr = next(e for e in events if e.event == "tool_result")
    assert tr.data["is_error"] is True
    assert "instrument not found" in tr.data["output"] or "ValueError" in tr.data["output"]
    # Loop continued to final answer
    assert events[-1].event == "done"


# ── Unknown tool (hallucinated by LLM) → is_error ─────────────────────────────
@pytest.mark.asyncio
async def test_unknown_tool_returns_is_error():
    """If LLM hallucinates a tool name not on the whitelist (read or gated
    write), dispatcher rejects with is_error. Verifies the safety net beneath
    the OpenAI-tools-list gating."""
    turn1 = [
        _chunk(_delta(tool_calls=[_tool_call_delta(0, "tc_1", "definitely_not_a_tool", '{}')])),
        _chunk(_delta(), finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(_delta(content="That tool doesn't exist."), finish_reason="stop"),
        _chunk(usage=_usage(5, 5, 10)),
    ]
    client = _make_client([turn1, turn2])
    dispatcher = ToolDispatcher(AsyncMock())

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "x"}],
        tools=[],
        dispatcher=dispatcher, max_turns=15,
    ):
        events.append(ev)

    tr = next(e for e in events if e.event == "tool_result")
    assert tr.data["is_error"] is True
    assert "not available" in tr.data["output"]


# ── Max turns exceeded ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_max_turns_exceeded():
    """Each turn returns a tool_call → loop should hit max_turns and yield error."""
    def _looping_turn(turn_idx: int):
        return [
            _chunk(_delta(tool_calls=[_tool_call_delta(0, f"tc_{turn_idx}", "get_quote", '{"instrument":"BTC-PERPETUAL"}')])),
            _chunk(_delta(), finish_reason="tool_calls"),
        ]

    streams = [_looping_turn(i) for i in range(3)]
    client = _make_client(streams)

    mcp_mock = AsyncMock(return_value=[MagicMock(text='{"price": 80000}', type="text")])
    dispatcher = ToolDispatcher(mcp_mock)

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "x"}],
        tools=[{"type": "function", "function": {"name": "get_quote", "description": "x", "parameters": {}}}],
        dispatcher=dispatcher, max_turns=3,
    ):
        events.append(ev)

    assert events[-1].event == "error"
    assert events[-1].data["code"] == "max_turns_exceeded"


# ── Auth failure ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reasoning_content_echoed_back_to_next_turn():
    """DeepSeek-reasoner: assistant message in next turn must include reasoning_content."""
    # Turn 1: emit reasoning + tool_call
    turn1 = [
        _chunk(_delta(reasoning="Let me think...")),
        _chunk(_delta(reasoning=" need to call get_portfolio.")),
        _chunk(_delta(tool_calls=[_tool_call_delta(0, "tc_r1", "get_portfolio", '{"currency":"BTC"}')])),
        _chunk(_delta(), finish_reason="tool_calls"),
    ]
    # Turn 2: final answer
    turn2 = [
        _chunk(_delta(content="Equity is $428."), finish_reason="stop"),
        _chunk(usage=_usage(50, 10, 60)),
    ]
    client = _make_client([turn1, turn2])

    # Capture the messages sent in turn 2 to verify reasoning_content was preserved
    sent_messages: list[Any] = []
    original_create = client.chat.completions.create

    async def _capturing_create(**kwargs):
        sent_messages.append(kwargs.get("messages"))
        return await original_create(**kwargs)

    client.chat.completions.create = _capturing_create

    mcp_mock = AsyncMock(return_value=[MagicMock(text='{"equity":428}', type="text")])
    dispatcher = ToolDispatcher(mcp_mock)

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "x"}],
        tools=[{"type": "function", "function": {"name": "get_portfolio", "description": "x", "parameters": {}}}],
        dispatcher=dispatcher, max_turns=15,
    ):
        events.append(ev)

    # Should have emitted reasoning_delta events
    reasoning_evs = [e for e in events if e.event == "reasoning_delta"]
    assert len(reasoning_evs) == 2
    assert reasoning_evs[0].data["delta"] == "Let me think..."

    # Turn 2's messages should include the assistant message with reasoning_content
    assert len(sent_messages) == 2
    turn2_messages = sent_messages[1]
    # Find the assistant message with tool_calls
    assistant_msgs = [m for m in turn2_messages if m["role"] == "assistant" and "tool_calls" in m]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].get("reasoning_content") == "Let me think... need to call get_portfolio."


@pytest.mark.asyncio
async def test_auth_error_emits_error_event():
    from openai import AuthenticationError

    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()

    async def _fail(**kwargs):
        raise AuthenticationError(
            message="invalid key",
            response=MagicMock(),
            body={"error": {"message": "invalid"}},
        )

    client.chat.completions.create = _fail
    dispatcher = ToolDispatcher(AsyncMock())

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "x"}],
        tools=[], dispatcher=dispatcher, max_turns=15,
    ):
        events.append(ev)

    assert len(events) == 1
    assert events[0].event == "error"
    assert events[0].data["code"] == "auth_failed"


# ── Write-mode confirmation flow ──────────────────────────────────────────────


def _make_place_order_turn():
    return [
        _chunk(_delta(tool_calls=[_tool_call_delta(0, "tc_w1", "place_order",
                    '{"instrument_name":"BTC-PERPETUAL","direction":"buy","amount":1,"order_type":"market"}')])),
        _chunk(_delta(), finish_reason="tool_calls"),
    ]


@pytest.mark.asyncio
async def test_write_tool_yields_confirmation_required_then_dispatches_on_confirm():
    """Confirmed write tool: confirmation_required → resolve True → tool_result success."""
    import asyncio
    from deribit_trading.agent.loop import resolve_confirmation

    turn1 = _make_place_order_turn()
    turn2 = [
        _chunk(_delta(content="Order placed."), finish_reason="stop"),
        _chunk(usage=_usage(10, 5, 15)),
    ]
    client = _make_client([turn1, turn2])

    mcp_mock = AsyncMock(return_value=[MagicMock(text='{"order_id":"ord_xyz","status":"open"}', type="text")])
    dispatcher = ToolDispatcher(mcp_mock)

    events: list[SSEEvent] = []

    async def _drive():
        async for ev in agent_chat(
            client=client, config=CFG, system_prompt="sys",
            user_messages=[{"role": "user", "content": "place a buy order"}],
            tools=[{"type": "function", "function": {"name": "place_order", "description": "x", "parameters": {}}}],
            dispatcher=dispatcher, max_turns=15, write_enabled=True,
        ):
            events.append(ev)
            if ev.event == "confirmation_required":
                # Simulate the user clicking Confirm after a brief moment.
                await asyncio.sleep(0.01)
                ok = resolve_confirmation(ev.data["tool_call_id"], True)
                assert ok is True

    await _drive()

    event_names = [e.event for e in events]
    assert "confirmation_required" in event_names
    assert "tool_result" in event_names
    confirmation = next(e for e in events if e.event == "confirmation_required")
    assert confirmation.data["name"] == "place_order"
    assert confirmation.data["tool_call_id"] == "tc_w1"
    assert "summary" in confirmation.data
    # Real dispatch happened → tool_result not is_error
    tr = next(e for e in events if e.event == "tool_result")
    assert tr.data["is_error"] is False
    mcp_mock.assert_called_once()


@pytest.mark.asyncio
async def test_write_tool_declined_returns_is_error_no_dispatch():
    import asyncio
    from deribit_trading.agent.loop import resolve_confirmation

    turn1 = _make_place_order_turn()
    turn2 = [
        _chunk(_delta(content="Ok, declined."), finish_reason="stop"),
        _chunk(usage=_usage(8, 3, 11)),
    ]
    client = _make_client([turn1, turn2])
    mcp_mock = AsyncMock()  # should NOT be called
    dispatcher = ToolDispatcher(mcp_mock)

    events: list[SSEEvent] = []

    async def _drive():
        async for ev in agent_chat(
            client=client, config=CFG, system_prompt="sys",
            user_messages=[{"role": "user", "content": "place a buy order"}],
            tools=[], dispatcher=dispatcher, max_turns=15, write_enabled=True,
        ):
            events.append(ev)
            if ev.event == "confirmation_required":
                await asyncio.sleep(0.01)
                resolve_confirmation(ev.data["tool_call_id"], False)

    await _drive()

    tr = next(e for e in events if e.event == "tool_result")
    assert tr.data["is_error"] is True
    assert "declined" in tr.data["output"].lower()
    mcp_mock.assert_not_called()


@pytest.mark.asyncio
async def test_write_tool_timeout_returns_is_error_no_dispatch(monkeypatch):
    """If user doesn't resolve within timeout, tool_result is_error with timeout reason."""
    import deribit_trading.agent.loop as loop_mod

    # Shrink timeout so the test is fast
    monkeypatch.setattr(loop_mod, "CONFIRMATION_TIMEOUT_SECONDS", 0.1)

    turn1 = _make_place_order_turn()
    turn2 = [
        _chunk(_delta(content="Timed out."), finish_reason="stop"),
        _chunk(usage=_usage(6, 2, 8)),
    ]
    client = _make_client([turn1, turn2])
    mcp_mock = AsyncMock()
    dispatcher = ToolDispatcher(mcp_mock)

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "place a buy order"}],
        tools=[], dispatcher=dispatcher, max_turns=15, write_enabled=True,
    ):
        events.append(ev)
        # never resolve

    tr = next(e for e in events if e.event == "tool_result")
    assert tr.data["is_error"] is True
    assert "timed out" in tr.data["output"].lower()
    mcp_mock.assert_not_called()


@pytest.mark.asyncio
async def test_write_tool_with_write_disabled_returns_is_error_without_card():
    """Defense-in-depth: if LLM synthesizes a write call while write_enabled=false,
    reject immediately without confirmation_required."""
    turn1 = _make_place_order_turn()
    turn2 = [
        _chunk(_delta(content="Sorry, locked."), finish_reason="stop"),
        _chunk(usage=_usage(2, 2, 4)),
    ]
    client = _make_client([turn1, turn2])
    mcp_mock = AsyncMock()
    dispatcher = ToolDispatcher(mcp_mock)

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "x"}],
        tools=[], dispatcher=dispatcher, max_turns=15,
        write_enabled=False,
    ):
        events.append(ev)

    assert not any(e.event == "confirmation_required" for e in events)
    tr = next(e for e in events if e.event == "tool_result")
    assert tr.data["is_error"] is True
    assert "write mode is off" in tr.data["output"].lower()
    mcp_mock.assert_not_called()


@pytest.mark.asyncio
async def test_audit_repo_records_decision():
    import asyncio
    from deribit_trading.agent.loop import resolve_confirmation

    turn1 = _make_place_order_turn()
    turn2 = [
        _chunk(_delta(content="ok"), finish_reason="stop"),
        _chunk(usage=_usage(1, 1, 2)),
    ]
    client = _make_client([turn1, turn2])
    dispatcher = ToolDispatcher(AsyncMock(return_value=[MagicMock(text='{}', type="text")]))

    captured: list[dict] = []
    audit_repo = MagicMock()
    audit_repo.record = AsyncMock(side_effect=lambda d: captured.append(d))

    async def _drive():
        async for ev in agent_chat(
            client=client, config=CFG, system_prompt="sys",
            user_messages=[{"role": "user", "content": "x"}],
            tools=[], dispatcher=dispatcher, max_turns=15,
            audit_repo=audit_repo, account_id="testnet", write_enabled=True,
        ):
            if ev.event == "confirmation_required":
                await asyncio.sleep(0.01)
                resolve_confirmation(ev.data["tool_call_id"], True)

    await _drive()

    assert len(captured) == 1
    audit_row = captured[0]
    assert audit_row["decision"] == "confirmed"
    assert audit_row["tool_name"] == "place_order"
    assert audit_row["account_id"] == "testnet"
    assert audit_row["tool_call_id"] == "tc_w1"


# ── Dispatcher: error-text reclassification ───────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_recognizes_error_text_prefix_as_is_error():
    """mcp_server.call_tool wraps exceptions as 'Error: ClassName: msg' text;
    dispatcher must surface this as is_error=True so the agent doesn't keep
    retrying a doomed call (e.g. Deribit -32602 Invalid params)."""
    err_content = MagicMock()
    err_content.text = "Error: DeribitAPIError: Deribit API error -32602: Invalid params"
    mcp_mock = AsyncMock(return_value=[err_content])
    dispatcher = ToolDispatcher(mcp_mock)

    output, is_error = await dispatcher.dispatch(
        "place_order", {"instrument_name": "BTC-PERPETUAL", "amount": 1}
    )
    assert is_error is True
    assert "Invalid params" in output


@pytest.mark.asyncio
async def test_dispatcher_normal_text_not_marked_as_error():
    ok_content = MagicMock()
    ok_content.text = '{"order_id":"ord_123","status":"filled"}'
    mcp_mock = AsyncMock(return_value=[ok_content])
    dispatcher = ToolDispatcher(mcp_mock)

    output, is_error = await dispatcher.dispatch("place_order", {"amount": 10})
    assert is_error is False
    assert output["order_id"] == "ord_123"
