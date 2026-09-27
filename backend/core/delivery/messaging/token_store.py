from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Hashable


@dataclass
class _TokenEntry:
    token: str
    expires_at: float


class TokenStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[tuple[Hashable, ...], _TokenEntry] = {}

    def get(self, key: tuple[Hashable, ...]) -> str:
        with self._lock:
            entry = self._tokens.get(key)
            if entry is None:
                return ""
            if entry.expires_at <= time.time():
                self._tokens.pop(key, None)
                return ""
            return entry.token

    def set(self, key: tuple[Hashable, ...], token: str, expires_in: int) -> None:
        ttl = max(60, int(expires_in) - 300)
        with self._lock:
            self._tokens[key] = _TokenEntry(token=token, expires_at=time.time() + ttl)

    def get_or_fetch(self, key: tuple[Hashable, ...], fetcher: Callable[[], tuple[str, int]]) -> str:
        with self._lock:
            cached = self.get(key)
            if cached:
                return cached
            token, expires_in = fetcher()
            if token:
                self.set(key, token, expires_in)
            return token

    def clear(self) -> None:
        with self._lock:
            self._tokens.clear()


token_store = TokenStore()
