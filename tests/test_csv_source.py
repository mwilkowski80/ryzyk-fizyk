from __future__ import annotations

import random
from pathlib import Path

import pytest

from number_questions.csv_source import CsvDeck, load_cards_from_csv_dir
from number_questions.models import Card


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_load_cards_from_csv_dir_merges_and_ignores_extra_columns(tmp_path: Path) -> None:
    _write(
        tmp_path / "a.csv",
        "id;question;answer;unit\n"
        "1;Ile to jest?;10;g\n"
        "2;Drugie?;2.5;kg\n",
    )
    _write(
        tmp_path / "b.csv",
        "question;answer;category\n"
        "Trzecie?;100;cat\n",
    )

    cards = load_cards_from_csv_dir(csv_dir=str(tmp_path), delimiter=";")

    assert len(cards) == 3
    assert {c.question for c in cards} == {"Ile to jest?", "Drugie?", "Trzecie?"}
    assert {c.answer for c in cards} == {10.0, 2.5, 100.0}


def test_load_cards_from_csv_dir_skips_non_numeric_answers(tmp_path: Path) -> None:
    _write(
        tmp_path / "a.csv",
        "question;answer\n"
        "OK?;10\n"
        "BAD?;n/a\n",
    )

    cards = load_cards_from_csv_dir(csv_dir=str(tmp_path), delimiter=";")

    assert len(cards) == 1
    assert cards[0].question == "OK?"
    assert cards[0].answer == 10.0


def test_load_cards_from_csv_dir_requires_columns(tmp_path: Path) -> None:
    _write(tmp_path / "a.csv", "foo;bar\n1;2\n")

    with pytest.raises(ValueError, match="must contain columns 'question' and 'answer'"):
        load_cards_from_csv_dir(csv_dir=str(tmp_path), delimiter=";")


def test_csv_deck_cycles_without_repeats_within_cycle() -> None:
    subset = [
        Card(question="Q1?", answer=1.0, explanation="e"),
        Card(question="Q2?", answer=2.0, explanation="e"),
        Card(question="Q3?", answer=3.0, explanation="e"),
        Card(question="Q4?", answer=4.0, explanation="e"),
        Card(question="Q5?", answer=5.0, explanation="e"),
    ]

    deck = CsvDeck(subset, rng=random.Random(0))

    first_cycle = [deck.next_card().question for _ in range(len(subset))]
    assert len(set(first_cycle)) == len(subset)

    # After cycle exhaustion, deck reshuffles and continues.
    next_q = deck.next_card().question
    assert next_q in {c.question for c in subset}
