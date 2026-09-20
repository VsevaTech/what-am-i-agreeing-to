"""Short-lived in-memory storage so the source viewer can show the analysed pages.

Nothing is written to disk or to a database. Entries expire after a TTL.
"""

from __future__ import annotations

import secrets
import threading
import time

from app.services.analysis import AnalysisResult


class ResultStore:
    def __init__(self, ttl_seconds: int = 1800, max_items: int = 200) -> None:
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._items: dict[str, tuple[float, AnalysisResult]] = {}
        self._lock = threading.Lock()

    def put(self, result: AnalysisResult) -> str:
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._purge()
            self._items[token] = (time.monotonic(), result)
        return token

    def get(self, token: str) -> AnalysisResult | None:
        with self._lock:
            self._purge()
            item = self._items.get(token)
        return item[1] if item else None

    def _purge(self) -> None:
        now = time.monotonic()
        expired = [k for k, (t, _) in self._items.items() if now - t > self.ttl]
        for k in expired:
            del self._items[k]
        while len(self._items) > self.max_items:
            oldest = min(self._items, key=lambda k: self._items[k][0])
            del self._items[oldest]
