"""Backend protocol. Redis is the real one; MemoryBackend is for dev and tests."""
from __future__ import annotations

from typing import Any, Optional, Protocol

from pydantic import BaseModel

from ..models import Event, Memory


class Filters(BaseModel):
    status: Optional[list[str]] = None
    scope: Optional[list[str]] = None
    type: Optional[list[str]] = None
    sensitivity: Optional[list[str]] = None
    subject: Optional[str] = None
    source_app: Optional[list[str]] = None
    exclude_ids: Optional[list[str]] = None

    def matches(self, m: Memory) -> bool:
        if self.status and m.status not in self.status:
            return False
        if self.scope and m.scope not in self.scope:
            return False
        if self.type and m.type not in self.type:
            return False
        if self.sensitivity and m.sensitivity not in self.sensitivity:
            return False
        if self.subject and (m.subject or "") != self.subject:
            return False
        if self.source_app and m.source.app not in self.source_app:
            return False
        if self.exclude_ids and m.id in self.exclude_ids:
            return False
        return True


class Backend(Protocol):
    name: str

    def ensure(self, dim: int) -> None: ...
    def put(self, m: Memory) -> None: ...
    def get(self, id: str) -> Optional[Memory]: ...
    def delete(self, id: str) -> None: ...
    def list(self, f: Filters, limit: int = 200, offset: int = 0) -> list[Memory]: ...
    def scan_all(self) -> list[Memory]: ...
    def count(self, f: Filters) -> int: ...
    def knn(self, vector: list[float], k: int, f: Filters) -> list[tuple[Memory, float]]: ...
    def append_event(self, e: Event) -> str: ...
    def events(self, limit: int = 100) -> list[Event]: ...
    def stats(self) -> dict[str, Any]: ...
    def get_meta(self) -> dict[str, Any]: ...
    def set_meta(self, meta: dict[str, Any]) -> None: ...
    def ping_ms(self) -> Optional[float]: ...
