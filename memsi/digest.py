"""Build the session-start digest: ranked, token-budgeted, grouped by type."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .config import Settings
from .models import Memory

TYPE_ORDER = ["identity", "preference", "decision", "project", "procedure", "fact", "relationship"]
TYPE_LABEL = {
    "identity": "Identity",
    "preference": "Preferences",
    "decision": "Decisions",
    "project": "Projects",
    "procedure": "Procedures",
    "fact": "Facts",
    "relationship": "Relationships",
}
STABLE_TYPES = {"identity", "preference"}  # decay 4x slower


def estimate_tokens(s: str) -> int:
    return max(1, len(s) // 4 + 2)


@dataclass
class DigestItem:
    memory: Memory
    score: float
    tokens: int
    included: bool = False


@dataclass
class Digest:
    text: str
    items: list[DigestItem] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    budget_tokens: int = 0
    used_tokens: int = 0

    @property
    def included(self) -> list[DigestItem]:
        return [i for i in self.items if i.included]

    @property
    def excluded(self) -> list[DigestItem]:
        return [i for i in self.items if not i.included]


def score_memory(m: Memory, settings: Settings, now: float) -> float:
    w = settings.recall.type_weights.get(m.type, 1.0)
    half_life = settings.recall.recency_half_life_days * (4 if m.type in STABLE_TYPES else 1)
    age_days = max(0.0, (now - (m.updated_at or m.created_at)) / 86400)
    decay = math.pow(0.5, age_days / half_life) if half_life > 0 else 1.0
    return w * decay * (0.5 + 0.5 * m.confidence)


def build_digest(memories: list[Memory], settings: Settings, scopes: list[str], budget_tokens: int, now: float | None = None) -> Digest:
    now = now or time.time()
    items = [DigestItem(m, score_memory(m, settings, now), estimate_tokens(f"- {m.content} [{m.short_id}]")) for m in memories]
    items.sort(key=lambda i: i.score, reverse=True)

    header = f"# Memory of {settings.owner} (scopes: {', '.join(scopes)})"
    footer = "\nCall memory_search for anything not here. Propose new facts, preferences or decisions with memory_propose and ask before confirming."
    used = estimate_tokens(header) + estimate_tokens(footer) + 6 * len(TYPE_ORDER)
    for it in items:
        if used + it.tokens <= budget_tokens:
            it.included = True
            used += it.tokens

    lines = [header]
    for t in TYPE_ORDER:
        group = [i for i in items if i.included and i.memory.type == t]
        if not group:
            continue
        lines.append(f"\n## {TYPE_LABEL[t]}")
        for i in group:
            scope_tag = "" if i.memory.scope in settings.recall.always_scopes else f" ({i.memory.scope})"
            lines.append(f"- {i.memory.content}{scope_tag} [{i.memory.short_id}]")
    lines.append(footer)
    return Digest(text="\n".join(lines), items=items, scopes=scopes, budget_tokens=budget_tokens, used_tokens=used)
