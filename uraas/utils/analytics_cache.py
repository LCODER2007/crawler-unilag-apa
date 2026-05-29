"""
URAAS Analytics Cache
Thread-safe in-memory cache with TTL for expensive analytics computations.
Invalidated on crawl completion.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_DEFAULT_TTL = 1800  # 30 minutes


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: int):
        self.value = value
        self.expires_at = time.monotonic() + ttl


class AnalyticsCache:
    """Thread-safe in-memory key-value cache with TTL expiry."""

    def __init__(self, default_ttl: int = _DEFAULT_TTL):
        self._store: Dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                log.debug("Cache MISS (expired): %s", key)
                return None
            log.debug("Cache HIT: %s", key)
            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            self._store[key] = _CacheEntry(value, ttl or self._default_ttl)
            log.debug("Cache SET: %s (ttl=%ss)", key, ttl or self._default_ttl)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def invalidate_all(self) -> None:
        """Call this when new papers are crawled to flush stale analytics."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
        log.info("Analytics cache flushed (%d entries cleared)", count)

    def invalidate_prefix(self, prefix: str) -> None:
        """Invalidate all keys starting with a given prefix."""
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            log.debug(
                "Invalidated %d cache entries with prefix '%s'", len(keys), prefix
            )

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)


# Singleton instance shared across the app
analytics_cache = AnalyticsCache(default_ttl=_DEFAULT_TTL)
