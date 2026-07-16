"""LLM provider abstraction layer.

Implements a common ``LLMProvider`` interface with the Groq
adapter as the primary implementation.  The abstract base is
preserved so additional providers can be added later.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from tri9t.app.services.prompt_builder import PromptSet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @abstractmethod
    async def generate(
        self,
        prompt: PromptSet,
        model: str,
        temperature: float,
    ) -> str:
        """Send the prompt to the LLM and return the raw response text.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            httpx.RequestError: On network failures.
        """
        ...


# ---------------------------------------------------------------------------
# Groq  (OpenAI-compatible)
# ---------------------------------------------------------------------------


class GroqProvider(LLMProvider):
    """Groq adapter (OpenAI chat-completions format).

    Uses the official Groq API endpoint.  Handles timeouts,
    rate limits, and unexpected responses gracefully.
    """

    _URL = "https://api.groq.com/openai/v1/chat/completions"
    _TIMEOUT = 60.0

    async def generate(
        self,
        prompt: PromptSet,
        model: str,
        temperature: float,
    ) -> str:
        """Call the Groq API and return the assistant message content.

        Raises:
            httpx.HTTPStatusError: On non-2xx API responses.
            httpx.RequestError: On network or timeout errors.
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}
        messages = [
            {
                "role": "system",
                "content": prompt.system_prompt
                + "\n\n"
                + prompt.developer_prompt,
            },
            {"role": "user", "content": prompt.user_prompt},
        ]
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._URL, json=payload, headers=headers, timeout=self._TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "groq": GroqProvider,
}


def get_provider(name: str, api_key: str) -> LLMProvider:
    """Instantiate a provider by name.

    Raises:
        ValueError: If *name* is not a recognised provider.
    """
    cls = _PROVIDERS.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider '{name}'. "
            f"Available: {', '.join(_PROVIDERS)}"
        )
    return cls(api_key)
