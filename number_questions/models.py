from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Card:
    question: str
    answer: float
    explanation: str
