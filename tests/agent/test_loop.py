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


# ── Banned tool → is_error ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_banned_tool_returns_is_error():
    turn1 = [
        _chunk(_delta(tool_calls=[_tool_call_delta(0, "tc_1", "place_order", '{"instrument_name":"X","direction":"buy","amount":1}')])),
        _chunk(_delta(), finish_reason="tool_calls"),
    ]
    turn2 = [
        _chunk(_delta(content="I cannot place orders."), finish_reason="stop"),
        _chunk(usage=_usage(5, 5, 10)),
    ]
    client = _make_client([turn1, turn2])
    dispatcher = ToolDispatcher(AsyncMock())

    events: list[SSEEvent] = []
    async for ev in agent_chat(
        client=client, config=CFG, system_prompt="sys",
        user_messages=[{"role": "user", "content": "buy 1 btc"}],
        tools=[],
        dispatcher=dispatcher, max_turns=15,
    ):
        events.append(ev)

    tr = next(e for e in events if e.event == "tool_result")
    assert tr.data["is_error"] is True
    assert "Phase 1" in tr.data["output"] or "not available" in tr.data["output"]


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
