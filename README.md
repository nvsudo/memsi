# memsi

**Governed personal memory on Redis.** Every AI assistant you use reads from one memory of record at the start of a session. Nothing is written to it without your consent. Contradictions are surfaced, never silently overwritten. You can see, correct and carry it anywhere.

> Repository: https://github.com/nvsudo/memsi · Status: phase 1 (single owner, local clients) is running daily against Redis Cloud. See [ROADMAP.md](ROADMAP.md) for what is done and what is next.

## Why

Knowledge workers use several assistants a day, and each keeps its own opaque memory of them. Those memories drift, contradict each other, cannot be reviewed, and are locked to one vendor. memsi puts one person's memory underneath all of them, with three rules:

1. **Always read.** A token-budgeted digest is injected at session start; search is available on demand.
2. **Write on approval.** Assistants propose, you confirm, and your words of approval are recorded.
3. **Raise, don't resolve.** The server detects neighbours and returns them. The assistant and you decide duplicate, update or contradiction.

## What is here

| Piece | Where | Notes |
|---|---|---|
| Core service (the one write path) | `memsi/core.py` | propose, confirm, supersede, retract, edit, recall, search, audit |
| Redis backend | `memsi/backend/redis_backend.py` | JSON documents, Search index with HNSW vector field, Stream for audit, one owner prefix |
| Dev backend | `memsi/backend/memory_backend.py` | in-process, same interface, used by tests |
| Local dashboard | `memsi/web/` | inbox with neighbours, digest preview, browse and edit, timeline |
| CLI `memctl` | `memsi/cli.py` | recall, search, propose, pending, confirm, retract, audit, stats, export, import, reindex, seed |
| MCP server | `memsi/mcp_server.py` | seven tools; the tool descriptions are the behavioural contract |
| Claude Code skill | `skills/memory/SKILL.md` | protocol for proposing, confirming, `/memory` subcommands |
| Scripts | `scripts/` | SessionStart hook, nightly export, launchd and Claude installers |

## Quick start

```bash
./uvw sync                  # first time: installs Python 3.12 + deps inside the project
./uvw run memctl seed       # demo memories, including a pending update and a near-duplicate
./uvw run memctl ui         # dashboard at http://127.0.0.1:7677
./uvw run pytest -q
```

Without a `.env` this runs on the in-process dev backend. To use Redis Cloud (free 30 MB tier is enough), copy `.env.example` to `.env`, paste the connection string, set `MEMSI_BACKEND=redis`, then `./uvw run memctl init`.

## Connect your assistants

```bash
sh scripts/install-claude.sh      # Claude Code MCP server + SessionStart hook + skill, and Claude Desktop MCP config
sh scripts/install-launchd.sh     # nightly export to ~/.memsi/backups at 02:30
```

Restart Claude Desktop after the first install. Claude Code picks the hook and server up on its next new session.

## Documents

These are living documents. Each change to the system should land with the matching doc change in the same commit.

| Document | What it holds | Update when |
|---|---|---|
| [README.md](README.md) | What memsi is, how to start, where things are | a user-facing capability or entry point changes |
| [DESIGN.md](DESIGN.md) | Why it is shaped this way: user stories, surfaces, data model, conflict semantics, measured latency, decisions | a design decision is made or reversed |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | How it is built right now: modules, data layout, write path, config, scripts, runbook, known limitations | code, config or operations change |
| [ROADMAP.md](ROADMAP.md) | What is done, what is next, what is later, by phase | an item starts, finishes or gets reprioritised |
| [AGENTS.md](AGENTS.md) | Start here if you are an AI agent working on this repo: rules, environment, map, gotchas | a rule or gotcha is learned |

## Licence

Not yet chosen. Private repository for now.
