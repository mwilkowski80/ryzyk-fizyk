from __future__ import annotations

import logging
import os
import queue
import sys
from typing import NoReturn

from .config import LlmConfig
from .csv_source import CsvDeck, load_cards_from_csv_dir
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


def _read_config() -> LlmConfig:
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


def _read_question_source() -> str:
    value = _get_required_env("QUESTION_SOURCE").lower()
    if value not in {"llm", "csv"}:
        raise ValueError("QUESTION_SOURCE must be either 'llm' or 'csv'")
    return value


def _read_csv_deck() -> CsvDeck:
    csv_dir = _get_required_env("CSV_QUESTIONS_DIR")
    delimiter = _get_required_env("CSV_DELIMITER")
    cards = load_cards_from_csv_dir(csv_dir=csv_dir, delimiter=delimiter)
    return CsvDeck(cards)


def _print_help() -> None:
    print("Komendy:")
    print("  n / next     - nowe pytanie")
    print("  a / answer   - pokaż odpowiedź do aktualnego pytania")
    print("  h / help     - pomoc")
    print("  q / quit     - wyjście")


def _die(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    _configure_logging()

    env_file = os.environ.get("ENV_FILE", ".env").strip() or ".env"
    try:
        _load_dotenv_if_available(env_file)
    except RuntimeError as e:
        _die(str(e))

    try:
        source = _read_question_source()
    except ValueError as e:
        _die(str(e))

    pool: CardPool | None = None
    deck: CsvDeck | None = None

    if source == "csv":
        try:
            deck = _read_csv_deck()
        except ValueError as e:
            _die(str(e))
    else:
        try:
            config = _read_config()
        except ValueError as e:
            _die(str(e))

        client = OpenAICompatibleClient(config)
        generator = QuestionGenerator(client=client)

        pool = CardPool(generator=generator, config=read_pool_config_from_env())
        pool.start_background()

    current = None
    answer_revealed = False

    _print_help()

    while True:
        try:
            cmd = input("> ").strip().lower()
        except EOFError:
            print()
            if pool is not None:
                pool.stop()
            return

        if cmd in {"q", "quit", "exit"}:
            if pool is not None:
                pool.stop()
            return

        if cmd in {"h", "help", "?", ""}:
            _print_help()
            continue

        if cmd in {"n", "next"}:
            try:
                if deck is not None:
                    current = deck.next_card()
                else:
                    assert pool is not None
                    try:
                        timeout = 3.0 if pool.size() == 0 else 0.2
                        current = pool.get_sync(timeout_seconds=timeout)
                    except queue.Empty:
                        print("Pula pytań się uzupełnia w tle — spróbuj ponownie za chwilę.")
                        continue
                answer_revealed = False
                print()
                print("Pytanie:")
                print(current.question)
                print()
            except (InvalidCard, LlmHttpError) as e:
                logging.getLogger(__name__).error("%s: %s", type(e).__name__, e)
                print("Nie udało się wygenerować poprawnej karty. Spróbuj ponownie.")
            continue

        if cmd in {"a", "answer"}:
            if current is None:
                print("Brak aktywnego pytania. Użyj 'next'.")
                continue
            if not answer_revealed:
                print("Odpowiedź:")
                print(current.answer)
                print("Wyjaśnienie:")
                print(current.explanation)
                print()
                answer_revealed = True
            else:
                print("Odpowiedź już była pokazana. Użyj 'next' po nowe pytanie.")
            continue

        print("Nieznana komenda. Użyj 'help'.")
