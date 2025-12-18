from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request

from .config import LlmConfig

logger = logging.getLogger(__name__)


class LlmHttpError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, config: LlmConfig) -> None:
        self._config = config

    @property
    def config(self) -> LlmConfig:
        return self._config

    def _chat_completions_url(self) -> str:
        base = self._config.base_url
        if not base.endswith("/"):
            base = base + "/"
        return urllib.parse.urljoin(base, self._config.chat_completions_path.lstrip("/"))

    def chat_completions(self, *, system_prompt: str, user_prompt: str) -> str:
        url = self._chat_completions_url()

        payload: dict[str, object] = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        if self._config.max_tokens > 0:
            payload["max_tokens"] = self._config.max_tokens

        if self._config.response_format:
            payload["response_format"] = {"type": self._config.response_format}

        try:
            content = self._do_request(url=url, payload=payload)
            if not content.strip() or ("{" not in content and "[" not in content):
                # Fallback for servers that return empty/non-JSON content with some params.
                payload.pop("response_format", None)
                payload.pop("max_tokens", None)
                content = self._do_request(url=url, payload=payload)
            return content
        except LlmHttpError as e:
            # Fallback for servers that don't support response_format
            if self._config.response_format and "HTTP error calling LLM: 400" in str(e):
                payload.pop("response_format", None)
                return self._do_request(url=url, payload=payload)
            raise

    def _do_request(self, *, url: str, payload: dict[str, object]) -> str:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        if self._config.api_key:
            req.add_header("Authorization", f"Bearer {self._config.api_key}")

        try:
            with urllib.request.urlopen(req, timeout=self._config.timeout_seconds) as resp:
                resp_body = resp.read().decode("utf-8")
        except (TimeoutError, socket.timeout) as e:
            logger.error("%s: %s", type(e).__name__, e)
            raise LlmHttpError(f"Timeout calling LLM after {self._config.timeout_seconds} seconds") from e
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                body = ""
            logger.error("%s: %s", type(e).__name__, e)
            raise LlmHttpError(f"HTTP error calling LLM: {e.code} {e.reason}. Body: {body}") from e
        except urllib.error.URLError as e:
            logger.error("%s: %s", type(e).__name__, e)
            raise LlmHttpError(f"URL error calling LLM: {e.reason}") from e

        try:
            parsed = json.loads(resp_body)
            content = parsed["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("LLM response content is not a string")
            return content
        except (KeyError, IndexError, TypeError, ValueError) as e:
            logger.error("%s: %s", type(e).__name__, e)
            raise LlmHttpError("Unexpected LLM response format") from e
