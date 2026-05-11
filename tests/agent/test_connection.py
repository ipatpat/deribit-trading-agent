"""End-to-end tests against the real LLM endpoint.

Skips automatically if neither DEEPSEEK_API_KEY nor GLM_API_KEY is set, so CI
runs are unaffected. Run locally with:
    DEEPSEEK_API_KEY=sk-... pytest tests/agent/test_connection.py -v
"""

import os

import pytest

from deribit_trading.agent.llm_client import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    list_models,
)
from deribit_trading.agent.loop import test_connection as glm_test_connection


def _has_key() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("GLM_API_KEY"))


def _api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY") or os.environ["GLM_API_KEY"]


def _endpoint() -> str:
    return (
        os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("GLM_BASE_URL")
        or DEFAULT_ENDPOINT
    )


def _model() -> str:
    return os.getenv("DEEPSEEK_MODEL") or os.getenv("GLM_MODEL") or DEFAULT_MODEL


@pytest.mark.skipif(not _has_key(), reason="No LLM API key set; skipping e2e test")
@pytest.mark.asyncio
async def test_real_minimal_request():
    """Issue a 1-token chat completion to a real provider endpoint."""
    result = await glm_test_connection(
        endpoint=_endpoint(), model=_model(), api_key=_api_key(), timeout=15.0
    )
    assert result["ok"] is True, f"Connection failed: {result}"
    assert isinstance(result.get("model"), str) and result["model"]
    usage = result.get("usage", {})
    assert usage.get("total_tokens", 0) >= 1


@pytest.mark.skipif(not _has_key(), reason="No LLM API key set")
@pytest.mark.asyncio
async def test_real_invalid_key_fails():
    """A wrong key should yield ok=false with auth_failed code."""
    result = await glm_test_connection(
        endpoint=_endpoint(), model=_model(), api_key="invalid-key-12345", timeout=10.0
    )
    assert result["ok"] is False
    assert result["code"] in ("auth_failed", "api_error", "unknown")


@pytest.mark.skipif(not _has_key(), reason="No LLM API key set")
@pytest.mark.asyncio
async def test_real_list_models():
    """Fetch available models from the live endpoint."""
    result = await list_models(endpoint=_endpoint(), api_key=_api_key(), timeout=15.0)
    assert result["ok"] is True, f"list-models failed: {result}"
    models = result["models"]
    assert isinstance(models, list)
    assert len(models) > 0
    assert all(isinstance(m, str) for m in models)
