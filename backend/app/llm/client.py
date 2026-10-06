"""Real LLM call: LiteLLM -> OpenRouter -> Cerebras, with structured output (see .claude/skills/cerebras)."""

from __future__ import annotations

import asyncio
import logging
import os

from pydantic import ValidationError

from .schema import LLMResponse

# litellm fetches its model cost map from GitHub at import time unless told otherwise.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

log = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
TIMEOUT_SECONDS = 60.0


class LLMError(Exception):
    """`code` goes into ChatResponse.actions.error (TEAM_CONTRACT §3)."""

    code = "llm_unavailable"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class LLMNotConfigured(LLMError):
    code = "llm_not_configured"


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMBadResponse(LLMError):
    code = "llm_bad_response"


def _completion(**kwargs):
    from litellm import completion  # deferred: importing litellm is slow

    return completion(**kwargs)


def _call_sync(messages: list[dict]) -> str:
    response = _completion(
        model=MODEL,
        messages=messages,
        response_format=LLMResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
        timeout=TIMEOUT_SECONDS,
    )
    return response.choices[0].message.content


def parse_response(content: str | None) -> LLMResponse:
    if not content:
        raise LLMBadResponse("empty LLM response")
    try:
        return LLMResponse.model_validate_json(content)
    except ValidationError as exc:
        raise LLMBadResponse(f"malformed LLM response: {exc.error_count()} validation error(s)") from exc


async def call_llm(messages: list[dict]) -> LLMResponse:
    """Raises LLMNotConfigured, LLMUnavailable or LLMBadResponse; never anything else."""
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        raise LLMNotConfigured("OPENROUTER_API_KEY is not set")
    try:
        content = await asyncio.to_thread(_call_sync, messages)
    except Exception as exc:  # network, auth, rate limit, provider errors...
        log.warning("LLM call failed: %s: %s", type(exc).__name__, exc)
        raise LLMUnavailable(str(exc)) from exc
    return parse_response(content)
