from __future__ import annotations

import concurrent.futures
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass

from .generator import QuestionGenerator
from .models import Card

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PoolConfig:
    target_size: int
    refill_threshold: int
    batch_size: int
    concurrency: int


def read_pool_config_from_env() -> PoolConfig:
    target_size = int(os.environ.get("POOL_TARGET_SIZE", "25").strip() or "25")
    refill_threshold = int(os.environ.get("POOL_REFILL_THRESHOLD", "10").strip() or "10")
    batch_size = int(os.environ.get("POOL_BATCH_SIZE", "1").strip() or "1")
    concurrency = int(os.environ.get("POOL_CONCURRENCY", "1").strip() or "1")

    if target_size < 1:
        raise ValueError("POOL_TARGET_SIZE must be >= 1")
    if refill_threshold < 0:
        raise ValueError("POOL_REFILL_THRESHOLD must be >= 0")
    if batch_size < 1:
        raise ValueError("POOL_BATCH_SIZE must be >= 1")
    if concurrency < 1:
        raise ValueError("POOL_CONCURRENCY must be >= 1")

    return PoolConfig(
        target_size=target_size,
        refill_threshold=refill_threshold,
        batch_size=batch_size,
        concurrency=concurrency,
    )


class CardPool:
    def __init__(self, *, generator: QuestionGenerator, config: PoolConfig) -> None:
        self._generator = generator
        self._config = config

        self._queue: queue.Queue[Card] = queue.Queue()
        self._seen: set[str] = set()

        self._stop_event = threading.Event()
        self._fill_lock = threading.Lock()
        self._background_thread: threading.Thread | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def size(self) -> int:
        try:
            return self._queue.qsize()
        except NotImplementedError:
            return 0

    def get_sync(self, *, timeout_seconds: float | None = None) -> Card:
        return self._queue.get(timeout=timeout_seconds)

    def warmup_sync(self, *, min_ready: int = 5) -> None:
        deadline = time.monotonic() + 120.0
        while self.size() < min_ready:
            self._fill_once_sync()
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out while warming up the card pool")

    def start_background(self) -> None:
        if self._background_thread is not None:
            return

        self._background_thread = threading.Thread(
            target=self._background_main,
            name="card-pool",
            daemon=True,
        )
        self._background_thread.start()

    def _background_main(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    if self.size() < self._config.refill_threshold:
                        while self.size() < self._config.target_size and not self._stop_event.is_set():
                            self._fill_once_sync()
                except Exception as e:
                    logger.error("%s: %s", type(e).__name__, e)
                time.sleep(0.5)
        except Exception as e:
            logger.error("%s: %s", type(e).__name__, e)
            raise

    def _fill_once_sync(self) -> None:
        missing = max(0, self._config.target_size - self.size())
        if missing <= 0:
            return

        logger.info("Filling pool: size=%d target=%d", self.size(), self._config.target_size)

        with self._fill_lock:
            if self.size() >= self._config.target_size:
                return

            results: list[list[Card]] = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=self._config.concurrency) as ex:
                futs = [
                    ex.submit(self._generator.generate_cards, target_count=self._config.batch_size)
                    for _ in range(self._config.concurrency)
                ]

                for fut in concurrent.futures.as_completed(futs):
                    try:
                        results.append(fut.result())
                    except Exception as e:
                        logger.error("%s: %s", type(e).__name__, e)

            added = 0
            for r in results:
                for card in r:
                    key = " ".join(card.question.lower().split())
                    if key in self._seen:
                        continue
                    self._seen.add(key)

                    if len(self._seen) > 2000:
                        self._seen.clear()

                    self._queue.put(card)
                    added += 1
                    if self.size() >= self._config.target_size:
                        break

                if self.size() >= self._config.target_size:
                    break

            if added == 0:
                logger.warning("Pool fill produced 0 cards")
                time.sleep(2.0)
