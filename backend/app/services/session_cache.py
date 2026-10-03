"""Ephemeral session memory for working hypotheses. Never persisted to a database.
Redis (with TTL) when VC_REDIS_URL is set, otherwise an in-process TTL dict."""
from __future__ import annotations

import json
import threading
import time

from app.settings import get_settings

TTL_SECONDS = 2 * 60 * 60


class _Memory:
    def __init__(self) -> None:
        self._d: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, k: str) -> str | None:
        with self._lock:
            v = self._d.get(k)
            if not v or v[0] < time.time():
                self._d.pop(k, None)
                return None
            return v[1]

    def setex(self, k: str, ttl: int, v: str) -> None:
        with self._lock:
            self._d[k] = (time.time() + ttl, v)

    def delete(self, k: str) -> None:
        with self._lock:
            self._d.pop(k, None)

    def flushdb(self) -> None:
        with self._lock:
            self._d.clear()


_backend = None


def _store():
    global _backend
    if _backend is None:
        url = get_settings().redis_url
        if url:
            import redis  # optional dependency
            _backend = redis.Redis.from_url(url, decode_responses=True)
        else:
            _backend = _Memory()
    return _backend


def get_hypotheses(session_id: str) -> list[dict]:
    raw = _store().get(f"hyp:{session_id}")
    return json.loads(raw) if raw else []


def set_hypotheses(session_id: str, hyps: list[dict]) -> None:
    _store().setex(f"hyp:{session_id}", TTL_SECONDS, json.dumps(hyps))


def discard(session_id: str) -> None:
    _store().delete(f"hyp:{session_id}")


def clear_all() -> None:
    store = _store()
    if isinstance(store, _Memory):
        store.flushdb()
    else:
        for key in store.scan_iter("hyp:*"):
            store.delete(key)
