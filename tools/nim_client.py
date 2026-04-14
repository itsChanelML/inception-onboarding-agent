"""
tools/nim_client.py

Reusable NVIDIA NIM API client. Every agent and route in this project
imports from here instead of instantiating OpenAI clients directly.

Features:
  - Single client instantiation with environment validation
  - Model constants for the two tiers used in this project
  - Retry logic with exponential backoff for transient errors
  - Streaming and non-streaming call methods
  - Token usage tracking per call
  - Structured output helper (returns parsed JSON from NIM)

Usage:
    from tools.nim_client import NIMClient, SUPER, NANO

    client = NIMClient()

    # Simple completion
    response = client.complete("Explain NIM in one sentence.")

    # With system prompt
    response = client.complete(
        prompt="Analyze this founder profile...",
        system="You are an NVIDIA Inception advisor.",
        model=SUPER
    )

    # Structured JSON output
    data = client.complete_json(
        prompt="Return risk signals as JSON...",
        system="Return only valid JSON."
    )

    # Streaming
    for chunk in client.stream("Generate a 12-month roadmap..."):
        print(chunk, end="", flush=True)
"""

import os
import json
import time
import re
from typing import Generator, Optional, Union
from openai import OpenAI, APIError, APITimeoutError, RateLimitError

# ── Model constants ───────────────────────────────────────────────────────────

SUPER = "nvidia/nemotron-super-49b-v1"   # Smart — briefs, roadmaps, risk analysis
NANO  = "nvidia/nemotron-nano-8b-v1"     # Fast — chip prediction, triage, short tasks

DEFAULT_MODEL     = SUPER
NIM_BASE_URL      = "https://integrate.api.nvidia.com/v1"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMP       = 0.7
DEFAULT_TOP_P      = 0.95
MAX_RETRIES        = 3
RETRY_BASE_DELAY   = 2.0   # seconds — doubles each retry


# ── Client ────────────────────────────────────────────────────────────────────

class NIMClient:
    """
    Wrapper around the NVIDIA NIM API (OpenAI-compatible endpoint).

    Instantiate once and reuse across the application.
    Validates the API key on init so misconfiguration fails fast.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        if not self.api_key:
            raise EnvironmentError(
                "NVIDIA_API_KEY not set. "
                "Add it to your .env file or Vercel environment variables."
            )
        self._client = OpenAI(
            base_url=NIM_BASE_URL,
            api_key=self.api_key
        )
        self.total_tokens_used = 0

    # ── Core completion ───────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMP,
        top_p: float = DEFAULT_TOP_P,
    ) -> str:
        """
        Single non-streaming completion. Returns the response string.
        Retries up to MAX_RETRIES times on transient errors.
        """
        messages = self._build_messages(prompt, system)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    stream=False
                )
                # Track token usage
                if response.usage:
                    self.total_tokens_used += response.usage.total_tokens

                return response.choices[0].message.content

            except RateLimitError as e:
                if attempt == MAX_RETRIES:
                    raise
                wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"[NIMClient] Rate limited. Retrying in {wait}s... (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)

            except APITimeoutError as e:
                if attempt == MAX_RETRIES:
                    raise
                wait = RETRY_BASE_DELAY * attempt
                print(f"[NIMClient] Timeout. Retrying in {wait}s... (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)

            except APIError as e:
                # Non-retryable API error
                raise RuntimeError(f"NIM API error: {e}") from e

    # ── Structured JSON output ────────────────────────────────────────────────

    def complete_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
    ) -> "Union[dict, list]":
        """
        Completion that expects and returns parsed JSON.
        Strips markdown fences if the model wraps output in them.
        Raises ValueError if the response cannot be parsed as JSON.
        """
        json_system = (
            (system + "\n\n" if system else "") +
            "Return ONLY valid JSON. No markdown, no preamble, no explanation."
        )

        raw = self.complete(
            prompt=prompt,
            system=json_system,
            model=model,
            max_tokens=max_tokens,
            temperature=0.3,   # Lower temp for structured output
        )

        # Strip markdown fences if present
        cleaned = re.sub(r"```json\s*", "", raw)
        cleaned = re.sub(r"```\s*", "", cleaned).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"NIM response was not valid JSON.\n"
                f"Error: {e}\n"
                f"Raw response:\n{raw[:500]}"
            ) from e

    # ── Streaming ─────────────────────────────────────────────────────────────

    def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMP,
    ) -> Generator[str, None, None]:
        """
        Streaming completion. Yields text chunks as they arrive.
        Use with Flask's Response + stream_with_context for SSE.

        Example:
            for chunk in client.stream("Generate a roadmap..."):
                yield f"data: {chunk}\\n\\n"
        """
        messages = self._build_messages(prompt, system)

        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True
        )

        for chunk in response:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                yield content

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def complete_fast(self, prompt: str, system: Optional[str] = None, max_tokens: int = 512) -> str:
        """Use NANO model for quick, low-stakes tasks like chip prediction and triage."""
        return self.complete(
            prompt=prompt,
            system=system,
            model=NANO,
            max_tokens=max_tokens,
            temperature=0.8
        )

    def complete_smart(self, prompt: str, system: Optional[str] = None, max_tokens: int = 4096) -> str:
        """Use SUPER model for high-quality generation like briefs and roadmaps."""
        return self.complete(
            prompt=prompt,
            system=system,
            model=SUPER,
            max_tokens=max_tokens,
            temperature=0.7
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _build_messages(prompt: str, system: Optional[str]) -> list:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def token_report(self) -> str:
        """Returns a summary of tokens used across all calls this session."""
        return f"Total tokens used this session: {self.total_tokens_used:,}"


# ── Module-level singleton ────────────────────────────────────────────────────
# Import this in agents and routes for a shared client instance.
# Falls back gracefully if the key isn't set yet (e.g. during import at build time).

try:
    nim = NIMClient()
except EnvironmentError:
    nim = None  # Routes should check for None and return a 503 if nim is unavailable