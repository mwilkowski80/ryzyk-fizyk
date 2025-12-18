import unittest

from number_questions.config import LlmConfig
from number_questions.generator import InvalidCard, QuestionGenerator


class _StubClient:
    def __init__(self, responses: list[str], *, max_retries: int) -> None:
        self._responses = list(responses)
        self._i = 0
        self._config = LlmConfig(
            base_url="http://example.invalid",
            api_key=None,
            model="test-model",
            temperature=0.0,
            max_tokens=200,
            timeout_seconds=1.0,
            max_retries=max_retries,
            chat_completions_path="/v1/chat/completions",
            response_format=None,
        )

    @property
    def config(self) -> LlmConfig:
        return self._config

    def chat_completions(self, *, system_prompt: str, user_prompt: str) -> str:  # noqa: ARG002
        if self._i >= len(self._responses):
            return self._responses[-1]
        r = self._responses[self._i]
        self._i += 1
        return r


class TestQuestionGeneratorRetry(unittest.TestCase):
    def test_filters_batch_then_succeeds(self) -> None:
        client = _StubClient(
            [
                "["
                '{"question":"Ile różnych 4-cyfrowych kodów PIN można utworzyć z cyfr 0-9 bez powtórzeń?","answer":5040,"explanation":"10*9*8*7"},'
                '{"question":"Ile mililitrów ma standardowa puszka coli?","answer":330,"explanation":"Najczęściej spotykana puszka w Polsce ma 330 ml."}'
                "]",
            ],
            max_retries=3,
        )
        gen = QuestionGenerator(client=client)  # type: ignore[arg-type]
        card = gen.generate_card()
        self.assertIn("puszka", card.question.lower())
        self.assertAlmostEqual(card.answer, 330.0)
        self.assertTrue(card.explanation)

    def test_raises_when_no_acceptable_cards(self) -> None:
        client = _StubClient(
            [
                "["
                '{"question":"Ile różnych 4-cyfrowych kodów PIN można utworzyć z cyfr 0-9 bez powtórzeń?","answer":5040,"explanation":"10*9*8*7"},'
                '{"question":"Ile jest kombinacji 6 liczb z 49?","answer":13983816,"explanation":"kombinatoryka"}'
                "]",
            ],
            max_retries=2,
        )
        gen = QuestionGenerator(client=client)  # type: ignore[arg-type]
        with self.assertRaises(InvalidCard):
            gen.generate_card()


if __name__ == "__main__":
    unittest.main()
