"""MemoryService: the one write path. CLI, dashboard and MCP tools all go through here."""
from __future__ import annotations

import time
from typing import Any, Optional

from .backend import Filters, make_backend
from .backend.base import Backend
from .config import Settings, load_settings
from .digest import Digest, build_digest
from .embed import Embedder, make_embedder
from .models import (
    SENSITIVITIES,
    TYPES,
    Approval,
    Event,
    Memory,
    Neighbour,
    PendingItem,
    ProposeResult,
    Source,
    now_ts,
    sensitivities_up_to,
)

ACTIVE = ["approved", "pending"]


class MemoryError(ValueError):
    pass


class MemoryService:
    def __init__(self, settings: Settings, backend: Backend, embedder: Embedder):
        self.settings = settings
        self.backend = backend
        self.embedder = embedder
        self.backend.ensure(embedder.dim)
        self.backend.set_meta({"embedder": embedder.name})

    # ------------------------------------------------------------------ util
    def _event(self, kind: str, memory: Optional[Memory], actor: str, via: Optional[str], **details: Any) -> None:
        self.backend.append_event(Event(kind=kind, memory_id=memory.id if memory else None, actor=actor, via=via, details=details))

    def _embed(self, text: str) -> list[float]:
        return self.embedder.embed([text])[0]

    @staticmethod
    def _validate(type: str, sensitivity: str, confidence: float) -> None:
        if type not in TYPES:
            raise MemoryError(f"type must be one of {TYPES}")
        if sensitivity not in SENSITIVITIES:
            raise MemoryError(f"sensitivity must be one of {SENSITIVITIES}")
        if not 0 <= confidence <= 1:
            raise MemoryError("confidence must be between 0 and 1")

    def _must_get(self, id: str) -> Memory:
        m = self.backend.get(id)
        if not m:
            raise MemoryError(f"no memory with id {id}")
        return m

    # ------------------------------------------------------------ neighbours
    def neighbours_for(self, vector: list[float], subject: Optional[str], exclude_id: Optional[str] = None, k: int = 8) -> list[Neighbour]:
        th = self.settings.thresholds
        f = Filters(status=ACTIVE, exclude_ids=[exclude_id] if exclude_id else None)
        found: dict[str, Neighbour] = {}
        for m, sim in self.backend.knn(vector, k, f):
            if sim >= th.duplicate:
                rel = "duplicate"
            elif subject and m.subject == subject:
                rel = "possible_update"
            elif sim >= th.conflict_low:
                rel = "related"
            else:
                continue
            found[m.id] = Neighbour(memory=m, similarity=sim, relation=rel)
        if subject:
            for m in self.backend.list(Filters(status=ACTIVE, subject=subject, exclude_ids=[exclude_id] if exclude_id else None), limit=20):
                if m.id not in found:
                    sim = 0.0
                    if m.embedding:
                        from .embed import cosine

                        sim = cosine(vector, m.embedding)
                    found[m.id] = Neighbour(memory=m, similarity=sim, relation="possible_update")
        out = list(found.values())
        out.sort(key=lambda n: n.similarity, reverse=True)
        return out

    def _auto_approve(self, m: Memory, neighbours: list[Neighbour]) -> bool:
        if m.type in self.settings.never_auto_approve_types:
            return False
        for rule in self.settings.auto_approve:
            if rule.type != m.type:
                continue
            if rule.sources and m.source.app not in rule.sources:
                continue
            if m.confidence < rule.min_confidence:
                continue
            if rule.require_no_neighbours and neighbours:
                continue
            return True
        return False

    # --------------------------------------------------------------- propose
    def propose(
        self,
        content: str,
        type: str = "fact",
        scope: str = "personal",
        subject: Optional[str] = None,
        sensitivity: str = "internal",
        confidence: float = 0.8,
        source_app: str = "unknown",
        source_model: Optional[str] = None,
        session: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> ProposeResult:
        content = content.strip()
        if not content:
            raise MemoryError("content is empty")
        self._validate(type, sensitivity, confidence)
        vec = self._embed(content)
        neighbours = self.neighbours_for(vec, subject)
        dup = next((n for n in neighbours if n.relation == "duplicate"), None)
        if dup:
            self._event("duplicate", dup.memory, actor=source_app, via=source_app, content=content)
            return ProposeResult(status="duplicate", duplicate_of=dup.memory, neighbours=neighbours)

        m = Memory(
            content=content,
            type=type,
            scope=scope,
            subject=subject,
            sensitivity=sensitivity,
            confidence=confidence,
            source=Source(app=source_app, model=source_model, session=session),
            tags=tags or [],
            embedding=vec,
        )
        if self._auto_approve(m, neighbours):
            m.status = "approved"
            m.approval = Approval(by="auto", via=source_app, quote=None)
            self.backend.put(m)
            self._event("auto_approved", m, actor="auto", via=source_app, type=type, scope=scope)
            return ProposeResult(status="auto_approved", memory=m, neighbours=neighbours)

        self.backend.put(m)
        self._event("proposed", m, actor=source_app, via=source_app, type=type, scope=scope, neighbours=len(neighbours))
        return ProposeResult(status="pending", memory=m, neighbours=neighbours)

    # --------------------------------------------------------------- confirm
    def confirm(
        self,
        id: str,
        decision: str,
        user_quote: Optional[str] = None,
        actor: str = "user",
        via: str = "unknown",
        supersedes_id: Optional[str] = None,
        edited_content: Optional[str] = None,
    ) -> Memory:
        m = self._must_get(id)
        if m.status != "pending":
            raise MemoryError(f"memory {id} is {m.status}, not pending")
        if decision not in ("approve", "reject", "supersede"):
            raise MemoryError("decision must be approve, reject or supersede")
        now = now_ts()

        if decision == "reject":
            m.status, m.updated_at = "rejected", now
            m.approval = Approval(by=actor, quote=user_quote, via=via)
            self.backend.put(m)
            self._event("rejected", m, actor=actor, via=via, quote=user_quote)
            return m

        if edited_content and edited_content.strip() != m.content:
            old = m.content
            m.content = edited_content.strip()
            m.embedding = self._embed(m.content)
            self._event("edited", m, actor=actor, via=via, before=old, after=m.content)

        if decision == "supersede":
            if not supersedes_id:
                raise MemoryError("supersede requires supersedes_id")
            old = self._must_get(supersedes_id)
            if old.status not in ACTIVE:
                raise MemoryError(f"cannot supersede a memory that is {old.status}")
            old.status, old.valid_to, old.superseded_by, old.updated_at = "superseded", now, m.id, now
            self.backend.put(old)
            m.supersedes = old.id
            self._event("superseded", old, actor=actor, via=via, by=m.id)

        m.status, m.updated_at = "approved", now
        m.approval = Approval(by=actor, quote=user_quote, via=via)
        self.backend.put(m)
        self._event("approved", m, actor=actor, via=via, quote=user_quote, supersedes=m.supersedes)
        return m

    # --------------------------------------------------------- retract/edit
    def retract(self, id: str, reason: Optional[str] = None, actor: str = "user", via: str = "unknown") -> Memory:
        m = self._must_get(id)
        if m.status == "retracted":
            return m
        m.status, m.valid_to, m.updated_at = "retracted", now_ts(), now_ts()
        self.backend.put(m)
        self._event("retracted", m, actor=actor, via=via, reason=reason)
        return m

    def edit(self, id: str, actor: str = "user", via: str = "unknown", **fields: Any) -> Memory:
        m = self._must_get(id)
        before = m.public_dict()
        allowed = {"content", "type", "scope", "subject", "sensitivity", "confidence", "tags"}
        for k, v in fields.items():
            if k not in allowed or v is None:
                continue
            setattr(m, k, v)
        self._validate(m.type, m.sensitivity, m.confidence)
        if m.content != before["content"]:
            m.embedding = self._embed(m.content)
        m.updated_at = now_ts()
        self.backend.put(m)
        changed = {k: (before[k], getattr(m, k)) for k in allowed if before.get(k) != getattr(m, k)}
        self._event("edited", m, actor=actor, via=via, changed=changed)
        return m

    # ------------------------------------------------------------------ read
    def _read_filter(self, app: Optional[str]) -> list[str]:
        return sensitivities_up_to(self.settings.read_filter_for(app).sensitivity_max)

    def search(self, query: str, k: int = 8, scope: Optional[list[str]] = None, type: Optional[list[str]] = None, app: Optional[str] = None, include_pending: bool = False) -> list[tuple[Memory, float]]:
        f = Filters(status=["approved", "pending"] if include_pending else ["approved"], scope=scope, type=type, sensitivity=self._read_filter(app))
        return self.backend.knn(self._embed(query), k, f)

    def recall(self, scope: Optional[str] = None, budget_tokens: Optional[int] = None, app: Optional[str] = None) -> Digest:
        scopes = list(self.settings.recall.always_scopes)
        if scope and scope not in scopes:
            scopes.append(scope)
        f = Filters(status=["approved"], scope=scopes, sensitivity=self._read_filter(app))
        rows = self.backend.list(f, limit=2000)
        rows = [m for m in rows if m.valid_to is None]
        return build_digest(rows, self.settings, scopes, budget_tokens or self.settings.recall.budget_tokens)

    def pending(self) -> list[PendingItem]:
        self.expire_pending()
        out = []
        for m in self.backend.list(Filters(status=["pending"]), limit=500):
            nb = self.neighbours_for(m.embedding, m.subject, exclude_id=m.id) if m.embedding else []
            out.append(PendingItem(memory=m, neighbours=nb))
        return out

    def expire_pending(self) -> int:
        cutoff = now_ts() - self.settings.pending_expiry_days * 86400
        n = 0
        for m in self.backend.list(Filters(status=["pending"]), limit=500):
            if m.created_at < cutoff:
                m.status, m.updated_at = "expired", now_ts()
                self.backend.put(m)
                self._event("expired", m, actor="system", via="system")
                n += 1
        return n

    def audit(self, limit: int = 100) -> list[Event]:
        return self.backend.events(limit)

    def browse(self, f: Filters, limit: int = 200, offset: int = 0) -> list[Memory]:
        return self.backend.list(f, limit, offset)

    def get(self, id: str) -> Optional[Memory]:
        return self.backend.get(id)

    def stats(self) -> dict[str, Any]:
        s = self.backend.stats()
        s["ping_ms"] = self.backend.ping_ms()
        s["embedder"] = self.embedder.name
        s["dim"] = self.embedder.dim
        s["owner"] = self.settings.owner
        return s

    # ------------------------------------------------------- export/import
    def export_all(self) -> dict[str, Any]:
        return {
            "owner": self.settings.owner,
            "exported_at": time.time(),
            "embedder": self.embedder.name,
            "items": [m.model_dump() for m in self.backend.list(Filters(), limit=100_000)],
            "events": [e.model_dump() for e in self.backend.events(100_000)],
        }

    def import_all(self, data: dict[str, Any], reembed: bool = True) -> int:
        n = 0
        for raw in data.get("items", []):
            m = Memory(**raw)
            if reembed or not m.embedding or len(m.embedding) != self.embedder.dim:
                m.embedding = self._embed(m.content)
            self.backend.put(m)
            n += 1
        self._event("imported", None, actor="user", via="cli", count=n, source=data.get("owner"))
        return n

    def reindex(self) -> int:
        items = self.backend.scan_all()
        drop = getattr(self.backend, "drop_index", None)
        if drop:
            drop()
        self.backend.ensure(self.embedder.dim)
        n = 0
        for m in items:
            m.embedding = self._embed(m.content)
            self.backend.put(m)
            n += 1
        self.backend.set_meta({"index_dim": self.embedder.dim, "embedder": self.embedder.name})
        return n


def get_service(settings: Optional[Settings] = None) -> MemoryService:
    settings = settings or load_settings()
    return MemoryService(settings, make_backend(settings), make_embedder(settings.embedder))
