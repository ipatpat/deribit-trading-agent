"""LLM client factory: AsyncOpenAI pointed at any OpenAI-compatible endpoint.

Default provider is DeepSeek (`https://api.deepseek.com`). Reads config from
KeyStore (ai_agent namespace) first, then falls back to env vars
(`DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` / `DEEPSEEK_API_KEY`). If neither is
configured, returns None and the caller surfaces the cold-start guidance.

Backward-compat: also reads legacy `GLM_*` env vars if `DEEPSEEK_*` are unset.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI, APIError, AuthenticationError, RateLimitError

if TYPE_CHECKING:
    from ..config.key_store import KeyStore

logger = logging.getLogger(__name__)


DEFAULT_ENDPOINT = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass(frozen=True)
class AgentConfig:
    """Resolved AI agent configuration."""

    endpoint: str
    model: str
    api_key: str

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.model and self.api_key)


def _read_env(*names: str) -> str | None:
    """Return first non-empty env var from the given names."""
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return None


def get_agent_config(keystore: "KeyStore | None" = None) -> AgentConfig | None:
    """Resolve agent config: keystore first, then env vars.

    Returns None if neither source has all three of endpoint/model/api_key.
    """
    # 1. KeyStore (preferred)
    if keystore is not None:
        try:
            cfg = keystore.get_ai_agent_config()
            if cfg:
                return AgentConfig(
                    endpoint=cfg["endpoint"],
                    model=cfg["model"],
                    api_key=cfg["api_key"],
                )
        except Exception as exc:
            logger.warning("KeyStore read failed for ai_agent config: %s", exc)

    # 2. Env vars (DEEPSEEK_* preferred, GLM_* legacy fallback)
    endpoint = _read_env("DEEPSEEK_BASE_URL", "GLM_BASE_URL") or DEFAULT_ENDPOINT
    model = _read_env("DEEPSEEK_MODEL", "GLM_MODEL") or DEFAULT_MODEL
    api_key = _read_env("DEEPSEEK_API_KEY", "GLM_API_KEY")
    if api_key:
        return AgentConfig(endpoint=endpoint, model=model, api_key=api_key)

    return None


def has_env_api_key() -> bool:
    """Whether an API key is available via env (for UI banner)."""
    return bool(_read_env("DEEPSEEK_API_KEY", "GLM_API_KEY"))


def make_client(cfg: AgentConfig) -> AsyncOpenAI:
    """Build an AsyncOpenAI client pointed at the given endpoint."""
    return AsyncOpenAI(
        api_key=cfg.api_key,
        base_url=cfg.endpoint,
    )


# ── Provider-side queries ─────────────────────────────────────────────────────
async def list_models(
    endpoint: str, api_key: str, timeout: float = 10.0
) -> dict[str, Any]:
    """Call OpenAI-compatible `/v1/models` to fetch available model IDs.

    Returns:
        On success: {"ok": True, "models": ["deepseek-chat", "deepseek-reasoner", ...]}
        On failure: {"ok": False, "code": "...", "error": "..."}
    """
    client = AsyncOpenAI(api_key=api_key, base_url=endpoint, timeout=timeout)
    try:
        resp = await client.models.list()
        models = [m.id for m in resp.data] if hasattr(resp, "data") else []
        models.sort()
        return {"ok": True, "models": models}
    except AuthenticationError as exc:
        return {"ok": False, "code": "auth_failed", "error": str(exc)}
    except RateLimitError as exc:
        return {"ok": False, "code": "rate_limit", "error": str(exc)}
    except APIError as exc:
        return {"ok": False, "code": "api_error", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": "unknown", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        await client.close()
