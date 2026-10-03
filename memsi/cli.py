"""memctl: CLI over MemoryService. Used by hooks, backups and humans."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from .backend import Filters
from .config import load_settings
from .core import MemoryError, get_service
from .models import iso

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Governed personal memory on Redis.")
VIA = "cli"


def _svc(config: Optional[str] = None):
    try:
        return get_service(load_settings(config))
    except Exception as e:  # connection or config problems should be readable
        typer.secho(f"memsi: {e}", fg="red", err=True)
        raise typer.Exit(1)


@app.command()
def ui(port: int = 7677, host: str = "127.0.0.1", config: Optional[str] = None):
    """Run the local dashboard."""
    import uvicorn

    from .web.app import create_app

    svc = _svc(config)
    typer.echo(f"memsi dashboard on http://{host}:{port}  (owner={svc.settings.owner}, backend={svc.backend.name}, embedder={svc.embedder.name})")
    uvicorn.run(create_app(svc), host=host, port=port, log_level="warning")


@app.command()
def recall(scope: Optional[str] = None, budget: Optional[int] = None, app_name: Optional[str] = typer.Option(None, "--app"), config: Optional[str] = None):
    """Print the session-start digest. Used by the Claude Code SessionStart hook."""
    d = _svc(config).recall(scope=scope, budget_tokens=budget, app=app_name)
    typer.echo(d.text)


@app.command()
def search(query: str, k: int = 8, scope: Optional[str] = None, app_name: Optional[str] = typer.Option(None, "--app"), config: Optional[str] = None):
    """Semantic search over approved memories."""
    for m, sim in _svc(config).search(query, k=k, scope=[scope] if scope else None, app=app_name):
        typer.echo(f"{sim:.2f}  [{m.type}/{m.scope}] {m.content}  ({m.short_id})")


@app.command()
def propose(
    content: str,
    type: str = "fact",
    scope: str = "personal",
    subject: Optional[str] = None,
    sensitivity: str = "internal",
    confidence: float = 0.8,
    source: str = "cli",
    config: Optional[str] = None,
):
    """Propose a memory (lands pending unless an auto-approve rule matches)."""
    try:
        r = _svc(config).propose(content, type=type, scope=scope, subject=subject, sensitivity=sensitivity, confidence=confidence, source_app=source)
    except MemoryError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(r.summary(), indent=2))


@app.command()
def pending(config: Optional[str] = None):
    """List pending proposals with their neighbours."""
    items = _svc(config).pending()
    if not items:
        typer.echo("nothing pending")
    for it in items:
        m = it.memory
        typer.echo(f"{m.id}  [{m.type}/{m.scope}] {m.content}   (from {m.source.app}, {iso(m.created_at)})")
        for n in it.neighbours:
            typer.echo(f"    {n.similarity:.2f} {n.relation:16} {n.memory.content}  ({n.memory.short_id}, {n.memory.status})")


@app.command()
def confirm(id: str, decision: str, quote: Optional[str] = None, supersedes: Optional[str] = None, config: Optional[str] = None):
    """approve | reject | supersede a pending proposal."""
    try:
        m = _svc(config).confirm(id, decision, user_quote=quote, via=VIA, supersedes_id=supersedes)
    except MemoryError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    typer.echo(f"{m.status}: {m.content}")


@app.command()
def retract(id: str, reason: Optional[str] = None, config: Optional[str] = None):
    m = _svc(config).retract(id, reason=reason, via=VIA)
    typer.echo(f"retracted: {m.content}")


@app.command()
def audit(limit: int = 50, config: Optional[str] = None):
    """Recent events, newest first."""
    for e in _svc(config).audit(limit):
        typer.echo(f"{e.at_iso}  {e.kind:14} {e.actor:10} via {e.via or '-':14} {e.memory_id[-8:] if e.memory_id else '':8}  {json.dumps(e.details) if e.details else ''}")


@app.command()
def stats(config: Optional[str] = None):
    typer.echo(json.dumps(_svc(config).stats(), indent=2, default=str))


@app.command()
def init(config: Optional[str] = None):
    """Create the index (idempotent) and print connection health."""
    s = _svc(config)
    typer.echo(json.dumps(s.stats(), indent=2, default=str))


@app.command()
def reindex(config: Optional[str] = None):
    """Drop and rebuild the index, re-embedding every memory. Needed after changing embedder."""
    n = _svc(config).reindex()
    typer.echo(f"re-embedded {n} memories")


@app.command()
def export(path: Path, config: Optional[str] = None):
    """Export everything (memories + events) to JSON. Run nightly."""
    data = _svc(config).export_all()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    typer.echo(f"exported {len(data['items'])} memories, {len(data['events'])} events -> {path}")


@app.command("import")
def import_(path: Path, reembed: bool = True, config: Optional[str] = None):
    """Import a memsi export (re-embeds by default)."""
    n = _svc(config).import_all(json.loads(path.read_text()), reembed=reembed)
    typer.echo(f"imported {n} memories")


@app.command()
def seed(config: Optional[str] = None):
    """Load demo memories, including a pending update, a near-duplicate and a clean proposal."""
    s = _svc(config)
    approved = [
        ("I'm Nik, I work at Redis in APJ go-to-market.", "identity", "work", "role", "internal", 0.98),
        ("Prefer direct, short answers. No closing offers, no restating what was done.", "preference", "work", "communication-style", "internal", 0.95),
        ("Writes design docs before code; wants decisions captured with the why.", "preference", "work", "working-style", "internal", 0.9),
        ("Lives in Melbourne.", "fact", "personal", "home-city", "private", 0.9),
        ("Decided on 2026-10-02 to build the personal memory layer on raw Redis 8, not on Redis Agent Memory, for phase 1.", "decision", "project:memsi", "memsi-foundation", "internal", 0.95),
        ("memsi phase 1 targets Claude Code and Claude Desktop over local stdio MCP.", "project", "project:memsi", "memsi-clients", "internal", 0.9),
        ("Uses MEDDPICC for deal reviews.", "procedure", "work", "deal-review", "internal", 0.85),
    ]
    for content, type, scope, subject, sens, conf in approved:
        r = s.propose(content, type=type, scope=scope, subject=subject, sensitivity=sens, confidence=conf, source_app="seed")
        if r.memory and r.memory.status == "pending":
            s.confirm(r.memory.id, "approve", user_quote="seeded", actor="user", via="seed")
    pend = [
        ("Moved to Sydney in September 2026.", "fact", "personal", "home-city", "private", 0.85, "claude-desktop"),
        ("Prefers direct and short answers with no closing offers.", "preference", "work", "communication-style", "internal", 0.9, "claude-code"),
        ("Runs the memsi dashboard on port 7677.", "project", "project:memsi", "memsi-dashboard", "internal", 0.8, "claude-code"),
        ("Partner is vegetarian.", "relationship", "personal", "partner", "private", 0.8, "claude-desktop"),
    ]
    for content, type, scope, subject, sens, conf, src in pend:
        s.propose(content, type=type, scope=scope, subject=subject, sensitivity=sens, confidence=conf, source_app=src, source_model="claude-opus-5-5")
    typer.echo(json.dumps(s.stats()["by_status"], indent=2))


if __name__ == "__main__":
    app()
