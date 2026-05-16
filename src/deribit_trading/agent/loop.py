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
from .summary import summarize as _summarize_write_call
from .tool_specs import READ_ONLY_TOOLS, WRITE_TOOLS_GATED

logger = logging.getLogger(__name__)


# ── Pending confirmations (module-level state) ────────────────────────────────
# Maps tool_call_id → Future. When the user resolves the ConfirmationCard
# in the UI, REST hits POST /api/v1/agent/confirm/<id> which calls
# `resolve_confirmation(...)` below, which sets the Future and unblocks the
# agent loop that's awaiting it.
_pending_confirmations: dict[str, asyncio.Future[bool]] = {}

# 30-second cap on user confirmation; matches the frontend countdown.
CONFIRMATION_TIMEOUT_SECONDS: float = 30.0


def resolve_confirmation(tool_call_id: str, confirmed: bool) -> bool:
    """Resolve a pending confirmation. Returns True if the future was found
    and unresolved (success); False if unknown or already-resolved."""
    future = _pending_confirmations.get(tool_call_id)
    if future is None or future.done():
        return False
    future.set_result(confirmed)
    return True


def has_pending_confirmation(tool_call_id: str) -> bool:
    """Exposed for tests / introspection."""
    future = _pending_confirmations.get(tool_call_id)
    return future is not None and not future.done()


def clear_pending_confirmations(reason: str = "account_switched") -> int:
    """Failure-resolve every pending Future. Called during account switch
    so the old chat's in-flight write decisions don't leak into the new
    account context. Returns the number of confirmations cleared."""
    n = 0
    for tcid, future in list(_pending_confirmations.items()):
        if not future.done():
            # Set False so the loop's await_for sees a "declined" result and
            # emits a clean tool_result is_error rather than dangling.
            try:
                future.set_result(False)
            except asyncio.InvalidStateError:
                pass
            n += 1
    _pending_confirmations.clear()
    if n:
        logger.info(
            "Cleared %d pending confirmation(s) (reason=%s)", n, reason
        )
    return n


# ── SSE event ─────────────────────────────────────────────────────────────────
@dataclass
class SSEEvent:
    """One SSE event to send to the frontend."""

    event: str  # text_delta | tool_use_start | tool_use_input | tool_use_end | tool_result | confirmation_required | reasoning_delta | done | error
    data: dict[str, Any]

    def to_sse(self) -> str:
        """Serialize to wire format: 'event: <name>\\ndata: <json>\\n\\n'."""
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


# ── Tool dispatcher protocol ──────────────────────────────────────────────────
class ToolDispatcher:
    """Wraps mcp_server.call_tool with whitelist enforcement.

    The whitelist covers ALL tools the agent may eventually invoke
    (read-only + gated write). The agent loop is responsible for
    intercepting write tools and routing them through the confirmation
    flow before they reach this dispatcher.
    """

    _ALLOWED: set[str] = set(READ_ONLY_TOOLS) | set(WRITE_TOOLS_GATED)

    def __init__(self, mcp_call_tool: Any) -> None:
        # mcp_call_tool: async callable (name, arguments) -> list[TextContent]
        self._call = mcp_call_tool

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        """Run a tool by name. Returns (result_json_or_text, is_error)."""
        if name not in self._ALLOWED:
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
            # mcp_server.call_tool wraps its branches in a top-level try/except
            # that returns exceptions as `Error: <Class>: <msg>` plain text.
            # Re-classify that here so the LLM sees is_error=True and stops
            # retrying blindly.
            is_error = text.lstrip().startswith("Error:") or text.lstrip().startswith(
                "Error "
            )
            try:
                return (json.loads(text), is_error)
            except (json.JSONDecodeError, TypeError):
                return (text, is_error)
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
    audit_repo: Any = None,
    account_id: str = "unknown",
    write_enabled: bool = False,
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
        audit_repo: optional WriteAuditRepo; if provided, each write tool
            decision (confirmed / declined / timeout) is recorded.
        account_id: the active account's uuid — written to each audit row so
            per-account audit history can be filtered.
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
                if name in WRITE_TOOLS_GATED:
                    if not write_enabled:
                        # Defense in depth: even if the LLM somehow synthesizes a
                        # write-tool call while write_enabled=false (some providers
                        # don't strictly validate against the tools list), reject
                        # without showing a confirmation card.
                        msg = (
                            f"Tool '{name}' is not available — write mode is off. "
                            "Ask the user to toggle the lock icon in the chat header "
                            "to enable order placement."
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": msg,
                        })
                        yield SSEEvent(
                            "tool_result",
                            {"tool_use_id": tc_id, "output": msg, "is_error": True},
                        )
                        continue
                    # Register the pending Future BEFORE yielding the SSE event,
                    # so the frontend's confirm POST (or test's resolve call)
                    # finds it immediately even if it races to respond.
                    summary = _summarize_write_call(name, args)
                    future: asyncio.Future[bool] = (
                        asyncio.get_event_loop().create_future()
                    )
                    _pending_confirmations[tc_id] = future
                    yield SSEEvent(
                        "confirmation_required",
                        {
                            "tool_call_id": tc_id,
                            "name": name,
                            "args": args,
                            "summary": summary,
                        },
                    )
                    decision: str
                    decision_reason: str | None = None
                    try:
                        confirmed = await asyncio.wait_for(
                            future, timeout=CONFIRMATION_TIMEOUT_SECONDS
                        )
                        decision = "confirmed" if confirmed else "declined"
                    except asyncio.TimeoutError:
                        confirmed = False
                        decision = "timeout"
                        decision_reason = "no_response_30s"
                    finally:
                        _pending_confirmations.pop(tc_id, None)

                    # Audit the decision (best-effort; never blocks main flow).
                    if audit_repo is not None:
                        try:
                            await audit_repo.record({
                                "tool_call_id": tc_id,
                                "tool_name": name,
                                "args_json": json.dumps(args, default=str),
                                "summary": summary,
                                "decision": decision,
                                "decision_reason": decision_reason,
                                "account_id": account_id,
                            })
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Audit log failed for %s: %s", tc_id, exc)

                    if not confirmed:
                        msg = (
                            "User declined the trade."
                            if decision == "declined"
                            else "Confirmation timed out (no response in 30s)."
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": msg,
                        })
                        yield SSEEvent(
                            "tool_result",
                            {
                                "tool_use_id": tc_id,
                                "output": msg,
                                "is_error": True,
                            },
                        )
                        continue
                    # Fall through: confirmed → real dispatch below

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
