"""AI Agent runtime: GLM-driven derivatives trading copilot.

Phase 1+2 (read-only):
- Backend agent loop with streaming SSE responses
- 11 read-only MCP tools exposed to LLM
- System prompt with Tier 1 derivatives knowledge

Modules:
- system_prompt: prompt template + Tier 1 knowledge + context injection
- tool_specs: MCP -> OpenAI tool def conversion + read-only whitelist
- llm_client: AgentConfig + AsyncOpenAI factory (DeepSeek default; OpenAI-compatible)
- loop: ReAct multi-turn loop with SSE event stream
"""

from .llm_client import AgentConfig, get_agent_config, has_env_api_key, list_models, make_client
from .loop import agent_chat, SSEEvent
from .system_prompt import build_system_prompt
from .tool_specs import (
    PHASE_1_READ_ONLY_TOOLS,
    TOOL_DESCRIPTIONS_OVERRIDE,
    convert_mcp_to_openai,
)

__all__ = [
    "AgentConfig",
    "get_agent_config",
    "has_env_api_key",
    "list_models",
    "make_client",
    "agent_chat",
    "SSEEvent",
    "build_system_prompt",
    "PHASE_1_READ_ONLY_TOOLS",
    "TOOL_DESCRIPTIONS_OVERRIDE",
    "convert_mcp_to_openai",
]
