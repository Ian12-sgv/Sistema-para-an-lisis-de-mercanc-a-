from time import monotonic
from threading import Lock
from typing import TypeVar

T = TypeVar("T")


class TtlCache:
    def __init__(self, ttl_seconds: int = 300, max_items: int = 128):
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._items: dict[str, tuple[float, object]] = {}
        self._lock = Lock()

    def get(self, key: str) -> object | None:
        with self._lock:
            item = self._items.get(key)

            if item is None:
                return None

            expires_at, value = item
            if expires_at <= monotonic():
                self._items.pop(key, None)
                return None

            return value

    def set(self, key: str, value: object) -> None:
        with self._lock:
            if len(self._items) >= self.max_items:
                oldest_key = min(self._items, key=lambda item_key: self._items[item_key][0])
                self._items.pop(oldest_key, None)

            self._items[key] = (monotonic() + self.ttl_seconds, value)


query_cache = TtlCache(ttl_seconds=300, max_items=256)
