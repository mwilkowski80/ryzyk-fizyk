from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .llm_client import OpenAICompatibleClient
from .models import Card

logger = logging.getLogger(__name__)


class InvalidCard(RuntimeError):
    pass


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _strip_code_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


_ANSWER_LINE_RE = re.compile(
    r"^(?:odpowiedź|answer)\s*[:\-]\s*(?P<value>[-+]?\d+(?:[\s.,]\d+)*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_QUESTION_LINE_RE = re.compile(
    r"^(?:pytanie|question)\s*[:\-]\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_EXPLANATION_LINE_RE = re.compile(
    r"^(?:wyjaśnienie|explanation)\s*[:\-]\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


_RELAXED_TRIPLE_RE = re.compile(
    r"\"question\"\s*:\s*\"(?P<question>.*?)\"\s*,\s*"
    r"\"answer\"\s*:\s*(?P<answer>[-+]?\d+(?:[\s.,]\d+)*)\s*,\s*"
    r"\"explanation\"\s*:\s*\"(?P<explanation>.*?)\"",
    re.IGNORECASE | re.DOTALL,
)


def _parse_cards_relaxed(text: str) -> list[Card]:
    cleaned = _strip_code_fences(text)
    cards: list[Card] = []

    for m in _RELAXED_TRIPLE_RE.finditer(cleaned):
        q = m.group("question").strip().replace("\n", " ")
        e = m.group("explanation").strip().replace("\n", " ")
        raw_answer = m.group("answer").strip().replace(" ", "").replace(",", ".")
        try:
            a = float(raw_answer)
        except ValueError:
            continue

        try:
            cards.append(_card_from_obj({"question": q, "answer": a, "explanation": e}))
        except InvalidCard:
            continue

    return cards


def _parse_card_fallback(text: str) -> Card | None:
    cleaned = _strip_code_fences(text)

    q_match = _QUESTION_LINE_RE.search(cleaned)
    a_match = _ANSWER_LINE_RE.search(cleaned)
    e_match = _EXPLANATION_LINE_RE.search(cleaned)

    if not a_match:
        return None

    question = q_match.group("value").strip() if q_match else None
    explanation = e_match.group("value").strip() if e_match else None

    if not question:
        # fallback: first line with '?' or first non-empty line
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        question = next((ln for ln in lines if "?" in ln), lines[0] if lines else None)

    if not explanation:
        explanation = "Szacunek na podstawie typowej/standardowej wartości."

    raw_answer = a_match.group("value").strip().replace(" ", "")
    raw_answer = raw_answer.replace(",", ".")

    try:
        answer = float(raw_answer)
    except ValueError:
        return None

    try:
        return _card_from_obj({"question": question, "answer": answer, "explanation": explanation})
    except InvalidCard:
        return None


def _extract_first_json_array(text: str) -> str | None:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _card_from_obj(obj: object) -> Card:
    if not isinstance(obj, dict):
        raise InvalidCard("Card must be an object")

    question = obj.get("question")
    answer = obj.get("answer")
    explanation = obj.get("explanation")

    if not isinstance(question, str) or not question.strip():
        raise InvalidCard("Field 'question' must be a non-empty string")
    if not isinstance(explanation, str) or not explanation.strip():
        raise InvalidCard("Field 'explanation' must be a non-empty string")

    if isinstance(answer, (int, float)):
        answer_f = float(answer)
    elif isinstance(answer, str):
        try:
            answer_f = float(answer.strip().replace(",", "."))
        except ValueError as e:
            raise InvalidCard("Field 'answer' must be a number") from e
    else:
        raise InvalidCard("Field 'answer' must be a number")

    if not (answer_f == answer_f):
        raise InvalidCard("Field 'answer' must not be NaN")

    return Card(question=question.strip(), answer=answer_f, explanation=explanation.strip())


def parse_card_json(text: str) -> Card:
    cleaned = _strip_code_fences(text)

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        extracted = _extract_first_json_object(cleaned)
        if extracted is not None:
            try:
                obj = json.loads(extracted)
                return _card_from_obj(obj)
            except json.JSONDecodeError as e2:
                fallback = _parse_card_fallback(extracted)
                if fallback is not None:
                    return fallback

                relaxed = _parse_cards_relaxed(extracted)
                if relaxed:
                    return relaxed[0]
                raise InvalidCard("LLM did not return valid JSON") from e2

        fallback = _parse_card_fallback(cleaned)
        if fallback is not None:
            return fallback

        relaxed = _parse_cards_relaxed(cleaned)
        if relaxed:
            return relaxed[0]
        raise InvalidCard("LLM did not return valid JSON") from e

    return _card_from_obj(obj)


def parse_cards_json(text: str) -> list[Card]:
    cleaned = _strip_code_fences(text)

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        extracted = _extract_first_json_array(cleaned) or _extract_first_json_object(cleaned)
        if extracted is not None:
            try:
                obj = json.loads(extracted)
            except json.JSONDecodeError as e2:
                fallback = _parse_card_fallback(extracted)
                if fallback is not None:
                    return [fallback]

                relaxed = _parse_cards_relaxed(extracted)
                if relaxed:
                    return relaxed
                raise InvalidCard("LLM did not return valid JSON") from e2
        else:
            fallback = _parse_card_fallback(cleaned)
            if fallback is not None:
                return [fallback]

            relaxed = _parse_cards_relaxed(cleaned)
            if relaxed:
                return relaxed
            raise InvalidCard("LLM did not return valid JSON") from e

    if isinstance(obj, dict):
        cards_value = obj.get("cards")
        if isinstance(cards_value, list):
            cards: list[Card] = []
            for item in cards_value:
                try:
                    cards.append(_card_from_obj(item))
                except InvalidCard as e:
                    logger.warning("%s: %s", type(e).__name__, e)
            return cards
        return [_card_from_obj(obj)]

    if isinstance(obj, list):
        cards: list[Card] = []
        for item in obj:
            try:
                cards.append(_card_from_obj(item))
            except InvalidCard as e:
                logger.warning("%s: %s", type(e).__name__, e)
        return cards

    raise InvalidCard("JSON root must be an object or an array")


_MATHY_KEYWORDS = (
    "kombin",
    "permut",
    "wariant",
    "prawdopodob",
    "równan",
    "pierwiast",
    "ciąg",
    "funkcj",
    "macierz",
    "logaryt",
    "silni",
    "nwd",
    "nww",
    "pin",
    "kod",
    "bez powtór",
    "ile jest kombin",
    "ile kombin",
    "ile możliwości",
)


_MATHY_PATTERNS = (
    re.compile(r"\b\d+\s*[+\-*/^]\s*\d+\b"),
    re.compile(r"\b[xyz]\b"),
    re.compile(r"=\s*\d"),
    re.compile(r"\bbez\s+powtórze"),
    re.compile(r"\b(?:sin|cos|tan)\b"),
)


_CALCULATION_EXPLANATION_PATTERNS = (
    re.compile(r"[+\-*/^=]"),
    re.compile(r"[×∙·]"),
    re.compile(r"\b\d+\s*[xX]\s*\d+\b"),
    re.compile(r"\b\d+\s*\+\s*\d+\b"),
)


_CALCULATION_KEYWORDS = (
    "policz",
    "oblicz",
    "suma",
    "razem",
    "łącznie",
    "ile punkt",
    "ile ma punkt",
    "wartość",
    "talia",
    "karty",
)


def _looks_like_math_puzzle(question: str) -> bool:
    q = question.strip().lower()
    if any(k in q for k in _MATHY_KEYWORDS):
        return True
    if any(p.search(q) for p in _MATHY_PATTERNS):
        return True
    return False


def _validate_trivia_style(card: Card) -> None:
    if _looks_like_math_puzzle(card.question):
        raise InvalidCard("Question looks like a math/logic puzzle; generate a trivia-style question instead")


_TOO_TECHNICAL_KEYWORDS = (
    "promień",
    "równik",
    "obwód",
    "gęsto",
    "ciśnien",
    "prędkość",
    "przyspieszen",
    "m/s",
    "km/s",
    "hz",
    "mhz",
    "ghz",
    "wolt",
    "amper",
    "wat",
    "joule",
    "kelvin",
    "atom",
    "cząsteczk",
    "reakcj",
    "wzór",
    "π",
)


def _looks_too_technical(question: str) -> bool:
    q = question.strip().lower()
    return any(k in q for k in _TOO_TECHNICAL_KEYWORDS)


def _validate_party_style(card: Card) -> None:
    _validate_trivia_style(card)
    if _looks_too_technical(card.question):
        raise InvalidCard("Question looks too technical; generate a party/trivia-style question instead")

    q_low = card.question.lower()
    if any(k in q_low for k in _CALCULATION_KEYWORDS):
        # Allow e.g. "ile kosztuje" etc. but reject scoring/summing/calculation style.
        if any(k in q_low for k in ("policz", "oblicz", "suma", "razem", "łącznie", "ile punkt", "talia", "karty")):
            raise InvalidCard("Question looks like a calculation/scoring task; generate trivia instead")

    if any(p.search(card.explanation) for p in _CALCULATION_EXPLANATION_PATTERNS):
        raise InvalidCard("Explanation contains arithmetic; generate trivia without calculations")

    if len(card.question) < 12 or len(card.question) > 180:
        raise InvalidCard("Question length is out of bounds")

    if not (0.001 <= card.answer <= 10_000_000):
        raise InvalidCard("Answer is out of reasonable bounds")


@dataclass(slots=True)
class QuestionGenerator:
    client: OpenAICompatibleClient

    def generate_card(self) -> Card:
        cards = self.generate_cards(target_count=1)
        if not cards:
            raise InvalidCard("No valid cards generated")
        return cards[0]

    def generate_cards(self, *, target_count: int) -> list[Card]:
        # If max_tokens is small, requesting too many cards can cause the JSON to be truncated,
        # resulting in invalid JSON. Scale the request size with max_tokens and let the pool
        # accumulate cards across multiple calls.
        max_tokens = self.client.config.max_tokens
        max_per_request = max(1, min(8, int(max_tokens / 220)))

        # Accumulate cards using multiple smaller calls (faster and less likely to truncate JSON).
        accepted: list[Card] = []
        unique: set[str] = set()
        max_calls = max(2, min(12, target_count * 3))

        system_prompt = (
            "Jesteś generatorem pytań do gry imprezowej w stylu 'Ryzyk Fizyk' (Wits & Wagers). "
            "To NIE jest quiz na wiedzę szkolną ani zadania z matematyki. "
            "Pytania mają być lekkie, zabawne, zaskakujące, z życia i popkultury, tak aby ludzie STRZELALI liczby. "
            "Unikaj tonu naukowego/encyklopedycznego. "
            "Nie podawaj żadnych obliczeń ani wzorów. "
            "Zwracaj WYŁĄCZNIE poprawny JSON."
        )

        common_rules = (
            "Kryteria stylu (bardzo ważne):\n"
            "- Ma to brzmieć jak pytanie z gry imprezowej, a nie z podręcznika.\n"
            "- Preferuj tematy: jedzenie i picie (pojemności/ilości), impreza/alkohol (z umiarem), sport (rekordy i wyniki, ale bez liczenia), "
            "kino/seriale/muzyka, zwierzęta, ciało człowieka (ciekawostki), codzienne przedmioty, pieniądze/ceny, zakupy, gry/Internet/memy (jeśli liczbowo).\n"
            "- UNIKAJ: naukowo-technicznych tematów wymagających wzorów (obwody, promienie, prędkości w m/s, jednostki fizyczne), "
            "łamigłówek matematycznych, kombinatoryki, prawdopodobieństwa, równań.\n"
            "- Odpowiedź ma być jedną liczbą (int/float) możliwą do oszacowania.\n"
            "- explanation: 1-2 zdania, skąd ta liczba (źródło/założenie), bez wyliczeń.\n"
            "- explanation ma być krótki, bez żargonu.\n"
            "\n"
            "Przykłady DOBREGO stylu (nie kopiuj dosłownie):\n"
            "- Ile minut trwa typowy film pełnometrażowy w kinie?\n"
            "- Ile litrów ma standardowa butelka wina?\n"
            "- Ile zębów ma dorosły człowiek?\n"
            "- Ile metrów ma basen olimpijski?\n"
            "- Ile kofeiny (mg) ma mniej więcej pojedyncze espresso?\n"
            "- Ile gramów waży mniej więcej tabliczka czekolady?\n"
            "\n"
            "Najpierw w myślach wybierz temat i oszacuj liczbę, ale NIE pokazuj rozumowania. Zwróć tylko JSON.\n"
        )

        for _ in range(max_calls):
            remaining = target_count - len(accepted)
            if remaining <= 0:
                break

            requested_count = min(remaining, max_per_request)

            if requested_count == 1:
                call_prompt = (
                    "Wygeneruj 1 kartę-pytanie liczbowe w języku polskim.\n"
                    "Zwróć JEDEN JSON OBJECT z kluczami: question (string), answer (number), explanation (string).\n"
                    "Nie zwracaj listy. Nie dodawaj żadnego tekstu poza JSON.\n"
                    "Pierwszy znak odpowiedzi ma być '{'. Nie używaj markdown.\n"
                    "Jeśli nie potrafisz zwrócić JSON, zwróć dokładnie 3 linie: 'Pytanie: ...', 'Odpowiedź: ...', 'Wyjaśnienie: ...'.\n"
                    "\n"
                    + common_rules
                )
            else:
                call_prompt = (
                    f"Wygeneruj {requested_count} różnych kart-pytań liczbowych w języku polskim.\n"
                    "Każda karta to obiekt JSON z kluczami: question (string), answer (number), explanation (string).\n"
                    "Zwróć JEDEN JSON OBJECT w formacie: {\"cards\": [ ... ]} i nic poza tym.\n"
                    "Pierwszy znak odpowiedzi ma być '{'. Nie używaj markdown.\n"
                    "\n"
                    + common_rules
                )

            raw = self.client.chat_completions(system_prompt=system_prompt, user_prompt=call_prompt)

            try:
                candidates = parse_cards_json(raw)
            except InvalidCard as e:
                logger.warning("%s: %s", type(e).__name__, e)
                cleaned = raw.strip().replace("\n", " ")
                logger.warning("LLM content length: %d", len(raw))
                logger.warning("LLM content snippet: %s", cleaned[:250])
                continue

            for card in candidates:
                try:
                    _validate_party_style(card)
                except InvalidCard as e:
                    logger.warning("%s: %s", type(e).__name__, e)
                    continue

                key = re.sub(r"\s+", " ", card.question.strip().lower())
                if key in unique:
                    continue
                unique.add(key)
                accepted.append(card)

                if len(accepted) >= target_count:
                    break

        return accepted
