"""In-process backend persisted to a JSON file. Same semantics as Redis, brute-force KNN."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..models import Event, Memory
from .base import Filters


class MemoryBackend:
    name = "memory"

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        self._items: dict[str, Memory] = {}
        self._events: list[Event] = []
        self._meta: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._load()

    # persistence -----------------------------------------------------------
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        raw = json.loads(self.path.read_text())
        self._items = {m["id"]: Memory(**m) for m in raw.get("items", [])}
        self._events = [Event(**e) for e in raw.get("events", [])]
        self._meta = raw.get("meta", {})

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "items": [m.model_dump() for m in self._items.values()],
                    "events": [e.model_dump() for e in self._events],
                    "meta": self._meta,
                }
            )
        )
        tmp.replace(self.path)

    # protocol --------------------------------------------------------------
    def ensure(self, dim: int) -> None:
        self._meta.setdefault("index_dim", dim)

    def put(self, m: Memory) -> None:
        with self._lock:
            self._items[m.id] = m
            self._save()

    def get(self, id: str) -> Optional[Memory]:
        return self._items.get(id)

    def delete(self, id: str) -> None:
        with self._lock:
            self._items.pop(id, None)
            self._save()

    def list(self, f: Filters, limit: int = 200, offset: int = 0) -> list[Memory]:
        rows = [m for m in self._items.values() if f.matches(m)]
        rows.sort(key=lambda m: m.created_at, reverse=True)
        return rows[offset : offset + limit]

    def scan_all(self) -> list[Memory]:
        return list(self._items.values())

    def count(self, f: Filters) -> int:
        return sum(1 for m in self._items.values() if f.matches(m))

    def knn(self, vector: list[float], k: int, f: Filters) -> list[tuple[Memory, float]]:
        q = np.asarray(vector, dtype=np.float32)
        qn = float(np.linalg.norm(q)) or 1.0
        scored: list[tuple[Memory, float]] = []
        for m in self._items.values():
            if not m.embedding or not f.matches(m):
                continue
            v = np.asarray(m.embedding, dtype=np.float32)
            vn = float(np.linalg.norm(v)) or 1.0
            scored.append((m, float(np.dot(q, v) / (qn * vn))))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    def append_event(self, e: Event) -> str:
        with self._lock:
            e.id = e.id or f"{int(e.at * 1000)}-{len(self._events)}"
            self._events.append(e)
            self._save()
        return e.id

    def events(self, limit: int = 100) -> list[Event]:
        return list(reversed(self._events))[:limit]

    def stats(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for m in self._items.values():
            by_status[m.status] = by_status.get(m.status, 0) + 1
        size = self.path.stat().st_size if self.path and self.path.exists() else 0
        return {"backend": "memory", "items": len(self._items), "by_status": by_status, "events": len(self._events), "bytes_used": size}

    def get_meta(self) -> dict[str, Any]:
        return dict(self._meta)

    def set_meta(self, meta: dict[str, Any]) -> None:
        self._meta.update(meta)
        self._save()

    def ping_ms(self) -> Optional[float]:
        t = time.perf_counter()
        _ = len(self._items)
        return (time.perf_counter() - t) * 1000
