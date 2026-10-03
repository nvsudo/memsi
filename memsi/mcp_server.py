"""MCP server (stdio). Tool descriptions ARE the behavioural contract across clients.

Set MEMSI_APP in the client's MCP config so proposals carry their source (claude-code, claude-desktop, ...).
"""
from __future__ import annotations

import os
from typing import Any, Optional

try:  # mcp SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .core import MemoryError, MemoryService, get_service

APP = os.environ.get("MEMSI_APP", "mcp")
MODEL = os.environ.get("MEMSI_MODEL")

INSTRUCTIONS = """memsi is the user's governed memory of record. Protocol:
1. At the start of every conversation call memory_recall once. Treat its content as what you know about the user.
2. Before answering anything that depends on the user's history, preferences or past decisions, call memory_search if the digest does not cover it.
3. When the user states a durable preference, fact, decision or project detail, call memory_propose. Never store secrets, credentials or health/financial identifiers.
4. memory_propose returns pending plus any neighbours. Ask the user in one short sentence whether to keep it (and, if a neighbour looks like an older version of the same fact, whether it replaces that one). Only after the user answers call memory_confirm with their words in user_quote. If it returns duplicate, say nothing was added.
5. Never present a pending memory as fact. Never call memory_confirm without an explicit yes or no from the user in this conversation.
6. If the user says a memory is wrong, call memory_retract."""

mcp = _Server("memsi", instructions=INSTRUCTIONS)
_svc: Optional[MemoryService] = None


def svc() -> MemoryService:
    global _svc
    if _svc is None:
        _svc = get_service()
    return _svc


def _m(m) -> dict[str, Any]:
    return {
        "id": m.id,
        "content": m.content,
        "type": m.type,
        "scope": m.scope,
        "subject": m.subject,
        "sensitivity": m.sensitivity,
        "status": m.status,
        "confidence": m.confidence,
        "source": m.source.app,
        "created": m.created_iso,
    }


@mcp.tool()
def memory_recall(scope: Optional[str] = None, budget_tokens: int = 1500) -> str:
    """Call this FIRST in every conversation, before anything else. Returns a ranked digest of what is known about the user: identity, preferences, decisions, projects. Pass scope="project:<slug>" when working inside a specific project so its memories are included alongside the always-on personal and work scopes."""
    return svc().recall(scope=scope, budget_tokens=budget_tokens, app=APP).text


@mcp.tool()
def memory_search(query: str, k: int = 8, scope: Optional[list[str]] = None, type: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Semantic search over the user's approved memories. Use when the digest from memory_recall does not answer a question about the user's history, preferences, decisions or projects. Returns matches with similarity scores."""
    return [dict(_m(m), similarity=round(sim, 3)) for m, sim in svc().search(query, k=k, scope=scope, type=type, app=APP)]


@mcp.tool()
def memory_propose(
    content: str,
    type: str = "fact",
    scope: str = "personal",
    subject: Optional[str] = None,
    sensitivity: str = "internal",
    confidence: float = 0.8,
) -> dict[str, Any]:
    """Propose a durable memory about the user. Does NOT store it as fact: it lands pending until the user confirms. Write content as one self-contained sentence in third person ("Prefers X", "Decided Y on <date>"). type: identity | preference | fact | decision | project | procedure | relationship. scope: personal | work | project:<slug>. subject: a short stable key for the thing this is about (e.g. home-city, communication-style) so updates to the same fact can be detected. sensitivity: public | internal | private. Returns status (pending | auto_approved | duplicate) and neighbours: existing memories that are similar or share the subject. If a neighbour has relation possible_update, the user may want this to replace it. ALWAYS ask the user before calling memory_confirm."""
    try:
        return svc().propose(content, type=type, scope=scope, subject=subject, sensitivity=sensitivity, confidence=confidence, source_app=APP, source_model=MODEL).summary()
    except MemoryError as e:
        return {"error": str(e)}


@mcp.tool()
def memory_confirm(
    id: str,
    decision: str,
    user_quote: str,
    supersedes_id: Optional[str] = None,
    edited_content: Optional[str] = None,
) -> dict[str, Any]:
    """Record the user's decision on a pending proposal. Call ONLY after the user has explicitly answered in this conversation. decision: approve | reject | supersede (supersede requires supersedes_id = the older memory it replaces; the old one is kept as history with an end date). user_quote: the user's actual words of approval or rejection, verbatim: this is stored for audit. edited_content: if the user corrected the wording, pass the corrected sentence."""
    try:
        m = svc().confirm(id, decision, user_quote=user_quote, actor="user", via=APP, supersedes_id=supersedes_id, edited_content=edited_content)
        return _m(m)
    except MemoryError as e:
        return {"error": str(e)}


@mcp.tool()
def memory_retract(id: str, reason: Optional[str] = None) -> dict[str, Any]:
    """Retract a memory the user says is wrong or no longer wants kept. Soft delete: it leaves the digest and search immediately but stays in the audit trail."""
    try:
        return _m(svc().retract(id, reason=reason, actor="user", via=APP))
    except MemoryError as e:
        return {"error": str(e)}


@mcp.tool()
def memory_pending() -> list[dict[str, Any]]:
    """List proposals still awaiting the user's decision, with neighbours. Use when the user asks what is pending or wants to review proposals in bulk."""
    out = []
    for it in svc().pending():
        d = _m(it.memory)
        d["neighbours"] = [dict(_m(n.memory), similarity=round(n.similarity, 3), relation=n.relation) for n in it.neighbours]
        out.append(d)
    return out


@mcp.tool()
def memory_audit(limit: int = 50) -> list[dict[str, Any]]:
    """Recent memory events (proposed, approved, rejected, superseded, retracted, edited), newest first. Use when the user asks what has been remembered or changed recently."""
    return [{"at": e.at_iso, "kind": e.kind, "actor": e.actor, "via": e.via, "memory_id": e.memory_id, "details": e.details} for e in svc().audit(limit)]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
