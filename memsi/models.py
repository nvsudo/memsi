"""Domain models."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

TYPES = ["identity", "preference", "fact", "decision", "project", "procedure", "relationship"]
SENSITIVITIES = ["public", "internal", "private"]
SENSITIVITY_RANK = {s: i for i, s in enumerate(SENSITIVITIES)}
STATUSES = ["pending", "approved", "rejected", "superseded", "retracted", "expired"]


def new_id() -> str:
    """Time-ordered id: 10 hex chars of ms epoch + 8 random hex."""
    return f"{int(time.time() * 1000):011x}{secrets.token_hex(4)}"


def now_ts() -> float:
    return time.time()


def iso(ts: Optional[float]) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def sensitivities_up_to(max_level: str) -> list[str]:
    rank = SENSITIVITY_RANK.get(max_level, len(SENSITIVITIES) - 1)
    return [s for s in SENSITIVITIES if SENSITIVITY_RANK[s] <= rank]


class Source(BaseModel):
    app: str = "unknown"
    model: Optional[str] = None
    session: Optional[str] = None


class Approval(BaseModel):
    by: str  # user | auto | <actor>
    quote: Optional[str] = None
    at: float = Field(default_factory=now_ts)
    via: Optional[str] = None  # claude-code | dashboard | cli | ...


class Memory(BaseModel):
    id: str = Field(default_factory=new_id)
    content: str
    type: str = "fact"
    scope: str = "personal"
    subject: Optional[str] = None
    sensitivity: str = "internal"
    status: str = "pending"
    confidence: float = 0.8
    source: Source = Field(default_factory=Source)
    approval: Optional[Approval] = None
    valid_from: Optional[float] = Field(default_factory=now_ts)
    valid_to: Optional[float] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    embedding: Optional[list[float]] = None
    created_at: float = Field(default_factory=now_ts)
    updated_at: float = Field(default_factory=now_ts)

    @property
    def short_id(self) -> str:
        return self.id[-8:]

    @property
    def created_iso(self) -> str:
        return iso(self.created_at)

    def public_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d.pop("embedding", None)
        return d


class Neighbour(BaseModel):
    memory: Memory
    similarity: float
    relation: str  # duplicate | possible_update | related


class ProposeResult(BaseModel):
    status: str  # pending | auto_approved | duplicate
    memory: Optional[Memory] = None
    duplicate_of: Optional[Memory] = None
    neighbours: list[Neighbour] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.memory:
            out["id"] = self.memory.id
        if self.duplicate_of:
            out["duplicate_of"] = {"id": self.duplicate_of.id, "content": self.duplicate_of.content}
        out["neighbours"] = [
            {
                "id": n.memory.id,
                "content": n.memory.content,
                "type": n.memory.type,
                "scope": n.memory.scope,
                "subject": n.memory.subject,
                "status": n.memory.status,
                "similarity": round(n.similarity, 3),
                "relation": n.relation,
            }
            for n in self.neighbours
        ]
        return out


class Event(BaseModel):
    id: Optional[str] = None
    kind: str  # proposed | auto_approved | approved | rejected | superseded | retracted | edited | duplicate | expired
    memory_id: Optional[str] = None
    at: float = Field(default_factory=now_ts)
    actor: str = "system"
    via: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def at_iso(self) -> str:
        return iso(self.at)


class PendingItem(BaseModel):
    memory: Memory
    neighbours: list[Neighbour] = Field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.neighbours
