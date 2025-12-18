from __future__ import annotations

import html
import logging
import os
import queue
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NoReturn

from .config import LlmConfig
from .generator import InvalidCard, QuestionGenerator
from .llm_client import LlmHttpError, OpenAICompatibleClient
from .pool import CardPool, read_pool_config_from_env


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s:%(levelname)s:%(name)s:%(message)s",
    )


def _load_dotenv_if_available(env_file: str) -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "python-dotenv is required to load configuration from .env. Install it in the local venv."
        ) from exc

    load_dotenv(dotenv_path=env_file, override=False)


def _get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()


def _read_llm_config() -> LlmConfig:
    base_url = _get_required_env("LLM_BASE_URL")
    model = _get_required_env("LLM_MODEL")

    api_key = os.environ.get("LLM_API_KEY")
    if api_key is not None:
        api_key = api_key.strip() or None

    temperature_raw = os.environ.get("LLM_TEMPERATURE", "0.7").strip()
    max_tokens_raw = os.environ.get("LLM_MAX_TOKENS", "256").strip()
    timeout_raw = os.environ.get("LLM_TIMEOUT_SECONDS", "30").strip()
    retries_raw = os.environ.get("LLM_MAX_RETRIES", "5").strip()
    path = os.environ.get("LLM_CHAT_COMPLETIONS_PATH", "/v1/chat/completions").strip()
    response_format_raw = os.environ.get("LLM_RESPONSE_FORMAT", "none").strip().lower()
    response_format = response_format_raw or None
    if response_format in {"none", "null"}:
        response_format = None

    return LlmConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=float(temperature_raw),
        max_tokens=int(max_tokens_raw),
        timeout_seconds=float(timeout_raw),
        max_retries=int(retries_raw),
        chat_completions_path=path,
        response_format=response_format,
    )


def _die(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _read_web_bind() -> tuple[str, int]:
    host = os.environ.get("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.environ.get("WEB_PORT", "8001").strip() or "8001"
    return host, int(port_raw)


class _AppState:
    def __init__(self, *, generator: QuestionGenerator, pool: CardPool) -> None:
        self.generator = generator
        self.pool = pool
        self.current = None
        self.answer_revealed = False
        self.last_error: str | None = None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        state: _AppState = self.server.state  # type: ignore[attr-defined]
        body = _render_page(state)
        body_bytes = body.encode("utf-8")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_POST(self) -> None:  # noqa: N802
        state: _AppState = self.server.state  # type: ignore[attr-defined]

        if self.path == "/next":
            try:
                try:
                    timeout = 1.0 if state.pool.size() == 0 else 0.2
                    state.current = state.pool.get_sync(timeout_seconds=timeout)
                except queue.Empty:
                    state.last_error = "Pula pytań się uzupełnia w tle — spróbuj ponownie za chwilę."
                    self._redirect_home()
                    return
                state.answer_revealed = False
                state.last_error = None
            except (InvalidCard, LlmHttpError) as e:
                logging.getLogger(__name__).error("%s: %s", type(e).__name__, e)
                state.last_error = f"{type(e).__name__}: {e}"
            self._redirect_home()
            return

        if self.path == "/answer":
            if state.current is not None:
                state.answer_revealed = True
            self._redirect_home()
            return

        if self.path == "/shutdown":
            allow = os.environ.get("WEB_ALLOW_SHUTDOWN", "0").strip() == "1"
            if not allow:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            state.pool.stop()
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            self.wfile.write(b"shutting down")
            self.server.shutdown()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _redirect_home(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        logging.getLogger(__name__).info(fmt, *args)


def _render_page(state: _AppState) -> str:
    question_html = "<em>Brak aktywnego pytania. Kliknij 'Następne pytanie'.</em>"
    answer_html = ""

    if state.current is not None:
        question_html = f"<div class='card'><h2>Pytanie</h2><div class='content'>{html.escape(state.current.question)}</div></div>"

        if state.answer_revealed:
            answer_html = (
                "<div class='card'>"
                "<h2>Odpowiedź</h2>"
                f"<div class='content'>{html.escape(str(state.current.answer))}</div>"
                "<h3>Wyjaśnienie</h3>"
                f"<div class='content'>{html.escape(state.current.explanation)}</div>"
                "</div>"
            )
        else:
            answer_html = "<div class='card muted'><h2>Odpowiedź</h2><div class='content'>(ukryta)</div></div>"

    error_html = ""
    if state.last_error:
        error_html = f"<div class='error'>Błąd: {html.escape(state.last_error)}</div>"

    return f"""<!doctype html>
<html lang='pl'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>Generator pytań liczbowych</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; max-width: 900px; }}
    .row {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }}
    button {{ padding: 10px 14px; font-size: 16px; cursor: pointer; }}
    .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 14px; margin: 12px 0; }}
    .muted {{ color: #666; background: #fafafa; }}
    .content {{ font-size: 18px; line-height: 1.4; white-space: pre-wrap; }}
    .error {{ background: #ffecec; border: 1px solid #ffb3b3; padding: 10px; border-radius: 10px; }}
  </style>
</head>
<body>
  <h1>Generator pytań liczbowych</h1>
  {error_html}

  <div class='row'>
    <form method='post' action='/next'>
      <button type='submit'>Następne pytanie</button>
    </form>

    <form method='post' action='/answer'>
      <button type='submit'>Pokaż odpowiedź</button>
    </form>
  </div>

  {question_html}
  {answer_html}
</body>
</html>"""


def main() -> None:
    _configure_logging()

    env_file = os.environ.get("ENV_FILE", ".env").strip() or ".env"
    try:
        _load_dotenv_if_available(env_file)
    except RuntimeError as e:
        _die(str(e))

    try:
        llm_config = _read_llm_config()
    except ValueError as e:
        _die(str(e))

    host, port = _read_web_bind()

    client = OpenAICompatibleClient(llm_config)
    generator = QuestionGenerator(client=client)

    pool = CardPool(generator=generator, config=read_pool_config_from_env())
    pool.start_background()

    server = ThreadingHTTPServer((host, port), _Handler)
    server.state = _AppState(generator=generator, pool=pool)  # type: ignore[attr-defined]

    logging.getLogger(__name__).info("Starting server on http://%s:%d", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
