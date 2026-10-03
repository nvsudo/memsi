"""Redis 8 backend: JSON documents, a Search index with a vector field, a Stream for events.

Keys (all under one owner prefix so copying to another person is a prefix change):
  mem:{owner}:item:{id}   JSON   the memory record incl. embedding
  mem:{owner}:idx         FT     index over the item prefix
  mem:{owner}:events      STREAM append-only audit log
  mem:{owner}:meta        HASH   index_dim, embedder, schema version
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import numpy as np
import redis
from redis.commands.search.field import NumericField, TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from ..models import Event, Memory
from .base import Filters

_TAG_ESCAPE = set(",.<>{}[]\"':;!@#$%^&*()-+=~| /\\")


def _esc(v: str) -> str:
    return "".join(("\\" + c) if c in _TAG_ESCAPE else c for c in v)


def _tag_clause(field: str, values: list[str]) -> str:
    return f"@{field}:{{{'|'.join(_esc(v) for v in values)}}}"


def _filter_expr(f: Filters) -> str:
    parts: list[str] = []
    if f.status:
        parts.append(_tag_clause("status", f.status))
    if f.scope:
        parts.append(_tag_clause("scope", f.scope))
    if f.type:
        parts.append(_tag_clause("type", f.type))
    if f.sensitivity:
        parts.append(_tag_clause("sensitivity", f.sensitivity))
    if f.subject:
        parts.append(_tag_clause("subject", [f.subject]))
    if f.source_app:
        parts.append(_tag_clause("source_app", f.source_app))
    if f.exclude_ids:
        parts.append("-" + _tag_clause("id", f.exclude_ids))
    return " ".join(parts) if parts else "*"


class RedisBackend:
    name = "redis"

    def __init__(self, url: str, owner: str):
        self.owner = owner
        self.r = redis.Redis.from_url(url, decode_responses=False)
        self.prefix = f"mem:{owner}:item:"
        self.idx_name = f"mem:{owner}:idx"
        self.events_key = f"mem:{owner}:events"
        self.meta_key = f"mem:{owner}:meta"
        self._idx = self.r.ft(self.idx_name)

    # keys ------------------------------------------------------------------
    def _key(self, id: str) -> str:
        return f"{self.prefix}{id}"

    # schema ----------------------------------------------------------------
    def ensure(self, dim: int) -> None:
        meta = self.get_meta()
        existing_dim = int(meta["index_dim"]) if meta.get("index_dim") else None
        try:
            self._idx.info()
            exists = True
        except redis.ResponseError:
            exists = False
        if exists and existing_dim and existing_dim != dim:
            raise RuntimeError(
                f"index {self.idx_name} was built for dim={existing_dim}, embedder now produces dim={dim}. Run `memctl reindex`."
            )
        if not exists:
            self._create_index(dim)
            self.set_meta({"index_dim": dim, "schema": 1})

    def _create_index(self, dim: int) -> None:
        schema = (
            TagField("$.id", as_name="id"),
            TextField("$.content", as_name="content"),
            TagField("$.type", as_name="type"),
            TagField("$.scope", as_name="scope"),
            TagField("$.subject", as_name="subject"),
            TagField("$.sensitivity", as_name="sensitivity"),
            TagField("$.status", as_name="status"),
            TagField("$.source.app", as_name="source_app"),
            NumericField("$.created_at", as_name="created_at", sortable=True),
            NumericField("$.confidence", as_name="confidence"),
            VectorField(
                "$.embedding",
                "HNSW",
                {"TYPE": "FLOAT32", "DIM": dim, "DISTANCE_METRIC": "COSINE", "M": 16, "EF_CONSTRUCTION": 200},
                as_name="embedding",
            ),
        )
        self._idx.create_index(schema, definition=IndexDefinition(prefix=[self.prefix], index_type=IndexType.JSON))

    def drop_index(self) -> None:
        try:
            self._idx.dropindex(delete_documents=False)
        except redis.ResponseError:
            pass
        self.r.hdel(self.meta_key, "index_dim")

    # documents -------------------------------------------------------------
    def put(self, m: Memory) -> None:
        self.r.json().set(self._key(m.id), "$", m.model_dump())

    def get(self, id: str) -> Optional[Memory]:
        raw = self.r.json().get(self._key(id))
        return Memory(**raw) if raw else None

    def delete(self, id: str) -> None:
        self.r.delete(self._key(id))

    def _docs(self, res) -> list[Memory]:
        out = []
        for d in res.docs:
            raw = getattr(d, "json", None)
            if raw is None:
                continue
            out.append(Memory(**json.loads(raw)))
        return out

    def list(self, f: Filters, limit: int = 200, offset: int = 0) -> list[Memory]:
        q = Query(_filter_expr(f)).sort_by("created_at", asc=False).paging(offset, limit).return_field("$", as_field="json").dialect(2)
        return self._docs(self._idx.search(q))

    def scan_all(self) -> list[Memory]:
        out: list[Memory] = []
        for key in self.r.scan_iter(match=f"{self.prefix}*", count=500):
            raw = self.r.json().get(key)
            if raw:
                out.append(Memory(**raw))
        return out

    def count(self, f: Filters) -> int:
        q = Query(_filter_expr(f)).paging(0, 0).dialect(2)
        return int(self._idx.search(q).total)

    def knn(self, vector: list[float], k: int, f: Filters) -> list[tuple[Memory, float]]:
        expr = _filter_expr(f)
        q = (
            Query(f"({expr})=>[KNN {k} @embedding $vec AS score]")
            .sort_by("score")
            .paging(0, k)
            .return_field("$", as_field="json")
            .return_field("score")
            .dialect(2)
        )
        blob = np.asarray(vector, dtype=np.float32).tobytes()
        res = self._idx.search(q, query_params={"vec": blob})
        out: list[tuple[Memory, float]] = []
        for d in res.docs:
            raw = getattr(d, "json", None)
            if raw is None:
                continue
            dist = float(getattr(d, "score"))
            out.append((Memory(**json.loads(raw)), 1.0 - dist))
        return out

    # events ----------------------------------------------------------------
    def append_event(self, e: Event) -> str:
        fields = {
            "kind": e.kind,
            "memory_id": e.memory_id or "",
            "at": repr(e.at),
            "actor": e.actor,
            "via": e.via or "",
            "details": json.dumps(e.details),
        }
        eid = self.r.xadd(self.events_key, fields, maxlen=50_000, approximate=True)
        e.id = eid.decode() if isinstance(eid, bytes) else eid
        return e.id

    def events(self, limit: int = 100) -> list[Event]:
        rows = self.r.xrevrange(self.events_key, count=limit)
        out = []
        for eid, fields in rows:
            f = {k.decode(): v.decode() for k, v in fields.items()}
            out.append(
                Event(
                    id=eid.decode(),
                    kind=f["kind"],
                    memory_id=f.get("memory_id") or None,
                    at=float(f.get("at") or 0),
                    actor=f.get("actor", "system"),
                    via=f.get("via") or None,
                    details=json.loads(f.get("details") or "{}"),
                )
            )
        return out

    # meta / stats ----------------------------------------------------------
    def get_meta(self) -> dict[str, Any]:
        raw = self.r.hgetall(self.meta_key)
        return {k.decode(): v.decode() for k, v in raw.items()}

    def set_meta(self, meta: dict[str, Any]) -> None:
        if meta:
            self.r.hset(self.meta_key, mapping={k: str(v) for k, v in meta.items()})

    def stats(self) -> dict[str, Any]:
        info = self.r.info("memory")
        by_status: dict[str, int] = {}
        for s in ["pending", "approved", "rejected", "superseded", "retracted", "expired"]:
            try:
                by_status[s] = self.count(Filters(status=[s]))
            except redis.ResponseError:
                by_status[s] = 0
        try:
            n = int(self._idx.info().get("num_docs", 0))
        except redis.ResponseError:
            n = 0
        return {
            "backend": "redis",
            "items": n,
            "by_status": by_status,
            "events": int(self.r.xlen(self.events_key)),
            "bytes_used": int(info.get("used_memory", 0)),
            "maxmemory": int(info.get("maxmemory", 0)),
        }

    def ping_ms(self) -> Optional[float]:
        t = time.perf_counter()
        self.r.ping()
        return (time.perf_counter() - t) * 1000
