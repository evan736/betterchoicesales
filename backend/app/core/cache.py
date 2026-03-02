"""Simple in-memory TTL cache for expensive API responses."""
import time
from typing import Any, Optional
import threading

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def get(key: str) -> Optional[Any]:
    """Get a cached value if it hasn't expired."""
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del _cache[key]
            return None
        return value


def set(key: str, value: Any, ttl_seconds: int = 60) -> None:
    """Cache a value with a TTL."""
    with _lock:
        _cache[key] = (time.time() + ttl_seconds, value)


def invalidate(prefix: str = "") -> None:
    """Clear cache entries matching a prefix (or all if empty)."""
    with _lock:
        if not prefix:
            _cache.clear()
        else:
            keys_to_delete = [k for k in _cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del _cache[k]
