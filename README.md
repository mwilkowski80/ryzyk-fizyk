# Generator pytań liczbowych — CLI + Web

Ta aplikacja generuje „karty” do gry w stylu *najbliżej, ale nie przekraczaj*. Każda karta zawiera:

- pytanie (tekst)
- odpowiedź liczbową
- krótkie wyjaśnienie (*explanation*)

Aplikacja działa w dwóch trybach:

- **CLI**: interaktywnie w terminalu (`next` → pytanie, `answer` → odpowiedź+wyjaśnienie)
- **Web**: prosta strona z przyciskami „Następne pytanie” i „Pokaż odpowiedź”

Źródło pytań jest wybierane przez `QUESTION_SOURCE`:

- `llm` — generowanie przez LLM (OpenAI-compatible `POST /v1/chat/completions`)
- `csv` — serwowanie pytań z plików CSV z folderu

---

## Wymagania

- Python **>= 3.10**
- Lokalny virtualenv w katalogu projektu: `./venv` lub `./.venv`
- Działający serwer LLM (OpenAI-compatible) dostępny pod `LLM_BASE_URL`

---

## Konfiguracja (.env)

1. Skopiuj plik przykładowy:

```bash
cp .env.example .env
```

2. Uzupełnij wartości w `.env`:

- `QUESTION_SOURCE` — **WYMAGANE**, `llm` albo `csv`

### Tryb `llm`

Wymagane:

- `LLM_BASE_URL` — bazowy URL serwera LLM, np. `http://localhost:4001`
- `LLM_MODEL` — nazwa modelu dostępna na serwerze
- `LLM_API_KEY` — klucz Bearer (jeśli wymagany)
- opcjonalnie: `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_CHAT_COMPLETIONS_PATH`
  - `LLM_RESPONSE_FORMAT` — domyślnie `none` (kompatybilność). Ustaw `json_object`, jeśli Twój serwer wspiera `response_format` i chcesz wymusić poprawny JSON.

> Aplikacja ładuje `.env` przez `python-dotenv` **tylko w entrypoincie**.

### Tryb `csv`

Wymagane:

- `CSV_QUESTIONS_DIR` — folder z plikami `*.csv` (bez rekurencji)
- `CSV_DELIMITER` — separator (np. `;`)

CSV może mieć wiele kolumn, ale aplikacja używa tylko:

- `question`
- `answer`

Wiersze z nienumerycznym `answer` są pomijane.

### Wskazanie innego pliku niż `.env`

Jeśli chcesz użyć innego pliku, ustaw zmienną środowiskową `ENV_FILE` (bez parametrów CLI):

```bash
ENV_FILE=/sciezka/do/inny.env python -m number_questions
```

---

## Instalacja zależności

Załóż, że masz już aktywny lokalny virtualenv (`./venv` lub `./.venv`).

Zainstaluj projekt w trybie editable (zapewnia też komendy konsolowe):

```bash
pip install -e .
```

---

## Uruchomienie — tryb CLI

### Opcja A: jako moduł

```bash
python -m number_questions
```

### Opcja B: jako komenda (po `pip install -e .`)

```bash
number-questions
```

### Komendy w CLI

- `n` / `next` — generuje i pokazuje **nowe pytanie**
- `a` / `answer` — pokazuje **odpowiedź i wyjaśnienie** do aktualnego pytania
- `h` / `help` — pomoc
- `q` / `quit` — wyjście

---

## Uruchomienie — tryb Web

### Konfiguracja Web

W `.env` (lub w środowisku) możesz ustawić:

- `WEB_HOST` — domyślnie `127.0.0.1`
- `WEB_PORT` — domyślnie `8001`

### Opcja A: jako moduł

```bash
python -m number_questions.web
```

### Opcja B: jako komenda (po `pip install -e .`)

```bash
number-questions-web
```

Po uruchomieniu otwórz w przeglądarce:

- `http://WEB_HOST:WEB_PORT/` (np. `http://127.0.0.1:8001/`)

### Jak działa UI

- **„Następne pytanie”** — pobiera nową kartę i pokazuje tylko pytanie
- **„Pokaż odpowiedź”** — odsłania odpowiedź i wyjaśnienie dla bieżącej karty

---

## Szybkość: prefetch/cache (POOL_*)

Żeby ograniczyć czekanie na generację, aplikacja utrzymuje w tle **pulę** wygenerowanych kart.
Kliknięcie/komenda `next` zwykle tylko pobiera kartę z pamięci.

Możesz sterować tym przez zmienne środowiskowe:

- `POOL_TARGET_SIZE` — ile kart trzymać w pamięci (domyślnie 25)
- `POOL_REFILL_THRESHOLD` — poniżej ilu kart zaczyna się uzupełnianie (domyślnie 10)
- `POOL_BATCH_SIZE` — ile kart próbować pozyskać na jedno zapytanie do LLM (domyślnie 1)
- `POOL_CONCURRENCY` — ile równoległych zapytań do LLM robić (domyślnie 1)

Na słabszych modelach zwykle najlepiej działa **mniejszy batch** (np. 1–3), bo pojedyncze większe zapytanie może przekraczać timeout.

Dodatkowo warto ograniczyć długość odpowiedzi:

- `LLM_MAX_TOKENS` — maksymalna liczba tokenów odpowiedzi (domyślnie 256). Mniejsze wartości zwykle znacząco przyspieszają generację.

Jeśli czasem dostajesz niepoprawny JSON, możesz spróbować:

- `LLM_RESPONSE_FORMAT=json_object` — aplikacja wyśle `response_format` do serwera (jeśli wspiera). Jeśli po tym pojawią się puste/zepsute odpowiedzi, wróć do `none`.

---

## Testy

Jeśli masz zainstalowane `pytest` w virtualenv, uruchom:

```bash
pytest
```

---

## Rozwiązywanie problemów

### Connection refused

Jeśli widzisz `Connection refused`, to znaczy że pod `LLM_BASE_URL` nic nie nasłuchuje albo port/host jest niepoprawny.

- sprawdź `.env` (`LLM_BASE_URL`)
- upewnij się, że serwer LLM działa

### 400 Invalid model name

Jeśli serwer zwraca błąd o modelu, ustaw `LLM_MODEL` na nazwę modelu faktycznie dostępną na Twoim serwerze.

---

## Struktura „karty”

Aplikacja oczekuje, że LLM zwróci JSON o strukturze:

```json
{
  "question": "...",
  "answer": 123.45,
  "explanation": "..."
}
```

Odpowiedź (`answer`) może być liczbą całkowitą lub ułamkową.
