"""Thread-safe, bounded, in-process failure limiter (single-process development)."""
from __future__ import annotations
from collections import defaultdict, deque
from threading import Lock
import time

class LoginGuard:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        if max_failures < 1 or window_seconds < 1:
            raise ValueError("Limits must be positive")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: str, now: float):
        history = self._failures[key]
        while history and now - history[0] >= self.window_seconds:
            history.popleft()
        return history

    def allowed(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            return len(self._prune(key, now)) < self.max_failures

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            history = self._prune(key, now)
            history.append(now)

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
