from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LlmConfig:
    base_url: str
    api_key: str | None
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    max_retries: int
    chat_completions_path: str
    response_format: str | None
