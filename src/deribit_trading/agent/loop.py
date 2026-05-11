"""Streaming agent loop with tool dispatch.

Multi-turn ReAct: call GLM with stream=True, accumulate text + tool_calls,
on tool_calls dispatch via mcp_server.call_tool, append tool_result message,
loop again. Cap at max_turns. Yield SSEEvent objects per the spec:

    text_delta, tool_use_start, tool_use_input, tool_use_end, tool_result, done, error
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from openai import AsyncOpenAI, APIError, AuthenticationError, RateLimitError

from .llm_client import AgentConfig
from .tool_specs import PHASE_1_READ_ONLY_TOOLS

logger = logging.getLogger(__name__)


# ── SSE event ─────────────────────────────────────────────────────────────────
@dataclass
class SSEEvent:
    """One SSE event to send to the frontend."""

    event: str  # text_delta | tool_use_start | tool_use_input | tool_use_end | tool_result | done | error
    data: dict[str, Any]

    def to_sse(self) -> str:
        """Serialize to wire format: 'event: <name>\\ndata: <json>\\n\\n'."""
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


# ── Tool dispatcher protocol ──────────────────────────────────────────────────
class ToolDispatcher:
    """Wraps mcp_server.call_tool with phase-1 whitelist enforcement."""

    def __init__(self, mcp_call_tool: Any) -> None:
        # mcp_call_tool: async callable (name, arguments) -> list[TextContent]
        self._call = mcp_call_tool

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        """Run a tool by name. Returns (result_json_or_text, is_error)."""
        if name not in PHASE_1_READ_ONLY_TOOLS:
            return (
                f"Tool '{name}' is not available in Phase 1 (read-only mode). "
                f"For order placement use the Place Order panel in the UI.",
                True,
            )
        try:
            content = await self._call(name, arguments)
            # MCP server returns list[TextContent]; concatenate text
            if isinstance(content, list):
                text = "".join(getattr(c, "text", str(c)) for c in content)
            else:
                text = str(content)
            # Try to parse as JSON; fall back to text
            try:
                return (json.loads(text), False)
            except (json.JSONDecodeError, TypeError):
                return (text, False)
        except Exception as exc:  # noqa: BLE001 — agent should see all tool errors
            logger.warning("Tool %s failed: %s", name, exc)
            return (f"Tool '{name}' raised: {type(exc).__name__}: {exc}", True)


# ── Agent loop ────────────────────────────────────────────────────────────────
async def agent_chat(
    *,
    client: AsyncOpenAI,
    config: AgentConfig,
    system_prompt: str,
    user_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    dispatcher: ToolDispatcher,
    max_turns: int = 15,
) -> AsyncIterator[SSEEvent]:
    """Run a multi-turn agent loop, yielding SSE events.

    Args:
        client: AsyncOpenAI client (GLM-pointed).
        config: AgentConfig (we only need .model from it here).
        system_prompt: prebuilt system prompt string.
        user_messages: list of OpenAI-format messages (user/assistant/tool roles).
        tools: OpenAI tool defs.
        dispatcher: ToolDispatcher wrapping mcp_server.call_tool.
        max_turns: hard cap on tool-call turns.
    """
    # Conversation state
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend(user_messages)

    for turn in range(max_turns):
        # Accumulator for this turn's response
        text_buf: list[str] = []
        reasoning_buf: list[str] = []  # DeepSeek-reasoner chain-of-thought
        tool_calls_partial: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: Any = None

        try:
            stream = await client.chat.completions.create(
                model=config.model,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                stream=True,
                stream_options={"include_usage": True},
            )
        except AuthenticationError as exc:
            yield SSEEvent("error", {"code": "auth_failed", "message": str(exc)})
            return
        except RateLimitError as exc:
            yield SSEEvent("error", {"code": "rate_limit", "message": str(exc)})
            return
        except APIError as exc:
            yield SSEEvent("error", {"code": "api_error", "message": str(exc)})
            return

        async for chunk in stream:
            # Handle usage (streaming GLM emits final chunk with usage)
            if chunk.usage is not None:
                usage = chunk.usage

            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # Reasoning streaming (DeepSeek-reasoner chain-of-thought).
            # MUST be captured and echoed back in subsequent turns or DeepSeek
            # rejects the request: "reasoning_content in thinking mode must be
            # passed back to the API."
            reasoning_chunk = getattr(delta, "reasoning_content", None) if delta else None
            if isinstance(reasoning_chunk, str) and reasoning_chunk:
                reasoning_buf.append(reasoning_chunk)
                yield SSEEvent("reasoning_delta", {"delta": reasoning_chunk})

            # Text streaming
            if delta and delta.content:
                text_buf.append(delta.content)
                yield SSEEvent("text_delta", {"delta": delta.content})

            # Tool call streaming (incremental JSON args)
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_partial:
                        tool_calls_partial[idx] = {
                            "id": tc.id or f"tc_{turn}_{idx}",
                            "name": "",
                            "args_buf": "",
                        }
                        if tc.function and tc.function.name:
                            tool_calls_partial[idx]["name"] = tc.function.name
                            yield SSEEvent(
                                "tool_use_start",
                                {
                                    "id": tool_calls_partial[idx]["id"],
                                    "name": tc.function.name,
                                },
                            )
                    # Append name fragment if it streams
                    if tc.function and tc.function.name and not tool_calls_partial[idx]["name"]:
                        tool_calls_partial[idx]["name"] = tc.function.name
                        yield SSEEvent(
                            "tool_use_start",
                            {
                                "id": tool_calls_partial[idx]["id"],
                                "name": tc.function.name,
                            },
                        )
                    # Stream args
                    if tc.function and tc.function.arguments:
                        tool_calls_partial[idx]["args_buf"] += tc.function.arguments
                        yield SSEEvent(
                            "tool_use_input",
                            {
                                "id": tool_calls_partial[idx]["id"],
                                "input_delta": tc.function.arguments,
                            },
                        )

            if choice.finish_reason:
                finish_reason = choice.finish_reason

        # End of stream for this turn — either tool_calls or final answer
        full_text = "".join(text_buf)
        full_reasoning = "".join(reasoning_buf)
        tool_calls_list = sorted(tool_calls_partial.items(), key=lambda kv: kv[0])

        if tool_calls_list:
            # Parse args, emit tool_use_end events, build assistant message
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if full_text:
                assistant_msg["content"] = full_text
            # DeepSeek-reasoner requires reasoning_content to be echoed back.
            if full_reasoning:
                assistant_msg["reasoning_content"] = full_reasoning
            assistant_msg["tool_calls"] = []
            parsed_calls: list[tuple[str, str, dict[str, Any]]] = []  # (id, name, args)
            for _idx, partial in tool_calls_list:
                tc_id = partial["id"]
                name = partial["name"]
                args_buf = partial["args_buf"] or "{}"
                try:
                    args = json.loads(args_buf)
                except json.JSONDecodeError:
                    args = {}
                yield SSEEvent("tool_use_end", {"id": tc_id, "input": args})
                assistant_msg["tool_calls"].append(
                    {
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    }
                )
                parsed_calls.append((tc_id, name, args))
            messages.append(assistant_msg)

            # Dispatch tools, append tool result messages
            for tc_id, name, args in parsed_calls:
                output, is_error = await dispatcher.dispatch(name, args)
                # Tool result must be a string for OpenAI API
                output_str = (
                    json.dumps(output, ensure_ascii=False, default=str)
                    if not isinstance(output, str)
                    else output
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": output_str,
                    }
                )
                yield SSEEvent(
                    "tool_result",
                    {
                        "tool_use_id": tc_id,
                        "output": output,
                        "is_error": is_error,
                    },
                )
            # Continue to next turn
            continue

        # No tool calls — terminal response
        if full_text or full_reasoning:
            terminal_msg: dict[str, Any] = {"role": "assistant"}
            if full_text:
                terminal_msg["content"] = full_text
            if full_reasoning:
                terminal_msg["reasoning_content"] = full_reasoning
            messages.append(terminal_msg)
        usage_dict = (
            {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
            if usage
            else {}
        )
        yield SSEEvent(
            "done",
            {
                "finish_reason": finish_reason or "stop",
                "usage": usage_dict,
            },
        )
        return

    # Hit max_turns
    yield SSEEvent(
        "error",
        {
            "code": "max_turns_exceeded",
            "message": f"Agent loop exceeded {max_turns} turns. Try a more focused question.",
        },
    )


# ── Connection test ───────────────────────────────────────────────────────────
async def test_connection(
    endpoint: str, model: str, api_key: str, timeout: float = 10.0
) -> dict[str, Any]:
    """Issue a minimal 1-token chat completion to verify endpoint+model+key."""
    client = AsyncOpenAI(api_key=api_key, base_url=endpoint, timeout=timeout)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return {
            "ok": True,
            "model": resp.model,
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else None,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else None,
                "total_tokens": resp.usage.total_tokens if resp.usage else None,
            },
        }
    except AuthenticationError as exc:
        return {"ok": False, "code": "auth_failed", "error": str(exc)}
    except RateLimitError as exc:
        return {"ok": False, "code": "rate_limit", "error": str(exc)}
    except APIError as exc:
        msg = str(exc)
        if "model" in msg.lower() and "not" in msg.lower():
            return {"ok": False, "code": "model_not_found", "error": msg}
        return {"ok": False, "code": "api_error", "error": msg}
    except (TimeoutError, asyncio.TimeoutError):
        return {"ok": False, "code": "timeout", "error": "Connection timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": "unknown", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        await client.close()
