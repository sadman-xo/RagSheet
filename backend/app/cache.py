"""Per-process LRU caches (no TTL: the data does not change while the process runs).

Caches never affect correctness: every key contains the data version and the scope key (or the
exact rendered prompt), so two scopes never share an entry.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Hashable


class LRUCache:
    def __init__(self, size: int):
        self.size = size
        self._items: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                self.hits += 1
                return self._items[key]
            self.misses += 1
            return None

    def put(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def stats(self) -> dict:
        with self._lock:
            return {"size": len(self._items), "max": self.size, "hits": self.hits, "misses": self.misses}
