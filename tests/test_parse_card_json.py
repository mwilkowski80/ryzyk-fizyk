import unittest

from number_questions.generator import InvalidCard, parse_card_json


class TestParseCardJson(unittest.TestCase):
    def test_parses_valid_json(self) -> None:
        text = '{"question":"Ile to jest?","answer":12.5,"explanation":"bo tak"}'
        card = parse_card_json(text)
        self.assertEqual(card.question, "Ile to jest?")
        self.assertAlmostEqual(card.answer, 12.5)
        self.assertEqual(card.explanation, "bo tak")

    def test_strips_code_fences(self) -> None:
        text = "```json\n{\"question\":\"Q\",\"answer\":1,\"explanation\":\"E\"}\n```"
        card = parse_card_json(text)
        self.assertEqual(card.question, "Q")

    def test_rejects_missing_fields(self) -> None:
        with self.assertRaises(InvalidCard):
            parse_card_json('{"question":"Q","answer":1}')

    def test_accepts_numeric_string_answer(self) -> None:
        card = parse_card_json('{"question":"Q","answer":"1.25","explanation":"E"}')
        self.assertAlmostEqual(card.answer, 1.25)

    def test_rejects_non_numeric_answer(self) -> None:
        with self.assertRaises(InvalidCard):
            parse_card_json('{"question":"Q","answer":"abc","explanation":"E"}')


if __name__ == "__main__":
    unittest.main()
