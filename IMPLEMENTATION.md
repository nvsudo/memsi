# Implementation

Living document: how memsi is built right now. Update it in the same commit as the code it describes. For the reasoning behind the shape, read [DESIGN.md](DESIGN.md); for what is next, [ROADMAP.md](ROADMAP.md).

Last updated: 2026-10-03.

## 1. Environment

- macOS, Apple Silicon. The machine has only system Python 3.9 and no Homebrew, Docker or Node, so the toolchain lives inside the project: `.tools/` holds `uv`, `.uv/` holds Python 3.12 and the uv cache, `.venv/` the environment. `./uvw` is the wrapper that sets those paths; use it for everything (`./uvw run memctl ...`, `./uvw run pytest -q`, `./uvw sync`).
- Config: `memsi.yaml` (checked in) plus `.env` (gitignored) for `REDIS_URL`, `MEMSI_BACKEND`, `MEMSI_OWNER`. Env wins over YAML. `MEMSI_CONFIG` can point at a different yaml.
- Redis: Redis Cloud Essentials free 30 MB, Redis 8.6.2, nearest region. Connection string only in `.env`. Limits that matter: 30 connections, 100 ops/sec, 5 GB/month, no replication, idle databases deleted after about two weeks (hence the nightly export).

## 2. Package map

```
memsi/
  config.py            Settings (pydantic): owner, backend, embedder, thresholds, auto_approve rules,
                       read_filters, recall params, backups_dir. load_settings() merges yaml + .env + env.
  models.py            Memory, Neighbour, ProposeResult, Event, PendingItem; TYPES, SENSITIVITIES, STATUSES.
  embed.py             Embedder protocol. HashEmbedder (default, lexical, 256-dim), OllamaEmbedder (768),
                       SentenceTransformerEmbedder (bge-small, 384, needs `memsi[semantic]`). cosine().
  backend/base.py      Backend protocol + Filters (status, scope, type, sensitivity, subject, source_app, exclude_ids).
  backend/redis_backend.py   The real one. See section 3.
  backend/memory_backend.py  In-process dict + brute-force cosine, persisted to .memsi/dev.json. Tests use it.
  digest.py            score_memory(), build_digest(): ranking + token budget + grouping by type.
  core.py              MemoryService: the ONE write path. get_service() wires settings + backend + embedder.
  web/app.py           FastAPI dashboard. Templates in web/templates (Jinja, no JS framework, no build step).
  cli.py               typer app `memctl`.
  mcp_server.py        MCP stdio server. Works on mcp SDK 2.x (MCPServer) and 1.x (FastMCP).
skills/memory/SKILL.md Claude Code skill: protocol + /memory subcommands.
scripts/
  session-start.sh     Claude Code SessionStart hook -> memctl recall for project:<cwd slug>.
  nightly-export.sh    memctl export to ~/.memsi/backups/memsi-YYYY-MM-DD.json, keep 30.
  install-launchd.sh   installs com.memsi.export (02:30 daily). --uninstall removes.
  install-claude.sh    Claude Code MCP (user scope) + hook merge + skill symlink; Claude Desktop MCP config.
tests/                 pytest, 18 tests, all on the dev backend.
```

## 3. Redis layout

All keys carry the owner prefix so a second person is a prefix change.

| Key | Type | Content |
|---|---|---|
| `mem:{owner}:item:{id}` | JSON | the full Memory record including `embedding` (float array) |
| `mem:{owner}:idx` | Search index | prefix `mem:{owner}:item:`; TAG id, type, scope, subject, sensitivity, status, source_app; TEXT content; NUMERIC created_at (sortable), confidence; VECTOR embedding HNSW FLOAT32 COSINE |
| `mem:{owner}:events` | Stream | append-only audit: kind, memory_id, at, actor, via, details(json); capped ~50k |
| `mem:{owner}:meta` | Hash | index_dim, embedder, schema |

Queries: `list` is `FT.SEARCH <filters> SORTBY created_at DESC`; `knn` is `(<filters>)=>[KNN k @embedding $vec AS score]` with DIALECT 2, similarity = 1 - score. Tag values are escaped (scope `project:memsi` becomes `project\:memsi`). `ensure(dim)` creates the index and refuses to run if the stored dim differs from the embedder's; `memctl reindex` rebuilds and re-embeds.

Ids are time-ordered: 11 hex chars of millisecond epoch plus 8 random hex. `short_id` is the last 8 and appears in the digest so the user can say "retract that one".

## 4. The write path (core.MemoryService)

```
propose(content, type, scope, subject?, sensitivity, confidence, source_app, ...)
  embed -> neighbours_for(vec, subject):
      knn k=8 over status in {approved, pending}
      sim >= thresholds.duplicate (0.92)        -> relation duplicate
      same subject                              -> relation possible_update (also pulled by tag even if sim is low)
      sim >= thresholds.conflict_low (0.75)     -> relation related
  any duplicate -> return status=duplicate, event "duplicate", nothing written
  auto-approve if a rule matches (type, min_confidence, sources, require_no_neighbours) and type not in never_auto_approve_types
      -> status approved, approval.by=auto, event auto_approved
  else -> status pending, event proposed

confirm(id, approve|reject|supersede, user_quote, supersedes_id?, edited_content?)
  only from pending. edited_content re-embeds and emits "edited".
  supersede: old.status=superseded, old.valid_to=now, old.superseded_by=new; new.supersedes=old.
  approval = {by, quote, via, at}. events approved / rejected / superseded.

retract(id, reason)   -> status retracted, valid_to=now, event retracted. Soft delete.
edit(id, **fields)    -> re-embed on content change, event edited with before/after.
expire_pending()      -> pending older than pending_expiry_days (7) -> expired. Runs on every pending().
```

Read path: `recall(scope, budget, app)` lists approved memories in `recall.always_scopes` plus the requested scope, drops anything with `valid_to`, applies the app's read filter (`read_filters[app].sensitivity_max`), and calls `build_digest`. `search(query, k, scope, type, app)` is knn over approved with the same read filter.

Digest ranking: `type_weight * 0.5^(age_days / half_life) * (0.5 + 0.5 * confidence)`; identity and preference decay four times slower. Items are added in score order while they fit the budget (tokens estimated at chars/4), then grouped Identity, Preferences, Decisions, Projects, Procedures, Facts, Relationships. Footer tells the model to search and to ask before confirming.

## 5. Surfaces

- **Dashboard** (`memctl ui`, 127.0.0.1:7677): `/inbox` (decide: approve, supersede with a selected neighbour, reject, edit-then-approve, bulk approve clean), `/digest` (render for scope, budget, app; ranking table), `/browse` (filters, semantic search, inline edit, retract), `/timeline`, `/api/health`, `/api/digest`. All writes go through MemoryService with `via=dashboard`.
- **MCP server** (`memsi-mcp`, stdio): `memory_recall`, `memory_search`, `memory_propose`, `memory_confirm`, `memory_retract`, `memory_pending`, `memory_audit`. `MEMSI_APP` env names the client (claude-code, claude-desktop) and drives the read filter and provenance. Server `instructions` plus tool descriptions carry the protocol; edit them deliberately.
- **Claude Code**: user-scope MCP registration (`~/.claude.json`), SessionStart hook in `~/.claude/settings.json` on `startup|resume|clear|compact` running `scripts/session-start.sh` (derives `project:<cwd basename slug>`, 20 s timeout, never non-zero), skill symlinked at `~/.claude/skills/memory`.
- **Claude Desktop**: `mcpServers.memsi` in `~/Library/Application Support/Claude/claude_desktop_config.json` with `MEMSI_APP=claude-desktop`. No hooks exist there, so the model follows the server instructions to call recall first.
- **CLI**: `memctl` for everything above plus `export`, `import`, `reindex`, `seed`, `stats`, `init`.

## 6. Operations runbook

| Task | Command |
|---|---|
| Health | `./uvw run memctl stats` or `GET /api/health` |
| Backup now | `sh scripts/nightly-export.sh` (same as the 02:30 job) |
| Restore | `./uvw run memctl import ~/.memsi/backups/memsi-YYYY-MM-DD.json` (re-embeds) |
| Change embedder | set `embedder:` in memsi.yaml, then `./uvw run memctl reindex` |
| Check nightly job | `launchctl print gui/$(id -u)/com.memsi.export`; log at `~/.memsi/logs/export.log` |
| Reconnect assistants | `sh scripts/install-claude.sh` (idempotent) |
| Capacity | `bytes_used` in stats vs 30 MB; empty database baseline is ~2 MB; ~5 KB per memory at 256-dim |

## 7. Measured performance (Redis Cloud, same metro, hash embedder)

ping 5.8 ms, recall 10 ms, search 9 ms, propose 24 ms (4 unpipelined round trips), confirm about 24 ms. SessionStart hook end to end 0.45 s including Python startup. See DESIGN.md section 10a.

## 8. Known limitations

- The default hash embedder is lexical. It catches duplicates and shares-a-word neighbours, not meaning. Same-subject updates are caught by the subject tag regardless. Switch to bge-small for real similarity.
- Propose and confirm are not pipelined yet.
- The digest is recomputed on every recall; no cache yet.
- Free-tier Redis has no replication; the nightly export is the only copy. Restore re-embeds, so an export from one embedder imports cleanly into another.
- Dashboard has no auth. It binds to 127.0.0.1 only.
- Pending expiry runs lazily (when `pending()` is called), not on a timer.

## 9. Conventions

- One write path. New entry points (UI, CLI, MCP, sync adapters) call `MemoryService`; they never touch the backend directly.
- Every write emits an Event. If you add a write, add its event kind and render it in the timeline.
- Tests run on `MemoryBackend(None)`; anything that needs Redis is exercised manually against the real database and recorded in DESIGN.md or here.
- Commit messages: imperative summary line; body only when the why is not obvious.
