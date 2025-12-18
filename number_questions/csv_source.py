from __future__ import annotations

import csv
import logging
import os
import random
import threading
from pathlib import Path

from .models import Card

logger = logging.getLogger(__name__)


def _parse_float(value: str) -> float:
    cleaned = value.strip().replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def load_cards_from_csv_dir(*, csv_dir: str, delimiter: str) -> list[Card]:
    if not delimiter or len(delimiter) != 1:
        raise ValueError("CSV_DELIMITER must be a single character")

    base = Path(csv_dir)
    if not base.is_absolute():
        base = Path(os.getcwd()) / base

    if not base.exists() or not base.is_dir():
        raise ValueError(f"CSV_QUESTIONS_DIR does not exist or is not a directory: {base}")

    paths = sorted(p for p in base.iterdir() if p.is_file() and p.suffix.lower() == ".csv")
    if not paths:
        raise ValueError(f"No CSV files found in directory: {base}")

    cards: list[Card] = []

    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            if reader.fieldnames is None:
                continue

            field_map = {name.strip().lower(): name for name in reader.fieldnames if name}
            q_field = field_map.get("question")
            a_field = field_map.get("answer")

            if q_field is None or a_field is None:
                raise ValueError(
                    f"CSV file {path} must contain columns 'question' and 'answer' (found: {reader.fieldnames})"
                )

            for row in reader:
                raw_q = (row.get(q_field) or "").strip()
                raw_a = (row.get(a_field) or "").strip()
                if not raw_q or not raw_a:
                    continue
                try:
                    answer = _parse_float(raw_a)
                except ValueError:
                    logger.warning("Skipping row with non-numeric answer in %s: %r", path.name, raw_a)
                    continue

                cards.append(
                    Card(
                        question=raw_q,
                        answer=answer,
                        explanation="Źródło: plik CSV.",
                    )
                )

    if not cards:
        raise ValueError(f"No valid cards loaded from CSV directory: {base}")

    return cards


class CsvDeck:
    __slots__ = ("_cards", "_rng", "_order", "_pos", "_lock")

    def __init__(self, cards: list[Card], *, rng: random.Random | None = None) -> None:
        if not cards:
            raise ValueError("CSV deck requires at least one card")
        self._cards = list(cards)
        self._rng = rng or random.Random()
        self._order: list[int] = []
        self._pos = 0
        self._lock = threading.Lock()
        self._reshuffle()

    def _reshuffle(self) -> None:
        self._order = list(range(len(self._cards)))
        self._rng.shuffle(self._order)
        self._pos = 0

    def next_card(self) -> Card:
        with self._lock:
            if self._pos >= len(self._order):
                self._reshuffle()
            idx = self._order[self._pos]
            self._pos += 1
            return self._cards[idx]
