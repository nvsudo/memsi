# memsi

Governed personal memory on Redis. Every AI assistant reads from it at the start of a session; nothing is written to it without the owner's consent; contradictions are surfaced, never silently overwritten.

See [DESIGN.md](DESIGN.md) for the full design and user stories.

## Quick start (dev backend, no Redis needed)

```bash
./uvw sync                 # install (first time)
./uvw run memctl seed      # demo data: approved memories + pending proposals
./uvw run memctl ui        # dashboard on http://127.0.0.1:7677
./uvw run pytest -q
```

## Redis Cloud

Create a free 30 MB database at redis.io/try-free, copy the connection string, then:

```bash
cp .env.example .env       # paste REDIS_URL, set MEMSI_BACKEND=redis
./uvw run memctl init      # creates the index, prints health
./uvw run memctl seed
```

## Claude Code

```bash
sh scripts/install-launchd.sh        # nightly export at 02:30 -> ~/.memsi/backups (--uninstall to remove)
claude mcp add --scope user --env MEMSI_APP=claude-code -- memsi "$PWD/uvw" run --directory "$PWD" memsi-mcp
```

Then add the SessionStart hook to `~/.claude/settings.json` so every session starts with the digest:

```json
{ "hooks": { "SessionStart": [ { "matcher": "startup|resume|clear|compact",
  "hooks": [ { "type": "command", "command": "/ABS/PATH/memsi/scripts/session-start.sh", "timeout": 20 } ] } ] } }
```

`scripts/session-start.sh` derives `project:<folder>` from the session cwd, calls `memctl recall`, and never blocks a session.

## MCP server

`memsi-mcp` runs the stdio MCP server exposing `memory_recall`, `memory_search`, `memory_propose`, `memory_confirm`, `memory_retract`, `memory_pending`, `memory_audit`. Set `MEMSI_APP` per client so proposals carry their source.

## Layout

- `memsi/core.py` — the one write path (propose, confirm, retract, edit, recall, search)
- `memsi/backend/` — `redis_backend.py` (JSON + Search + Stream) and `memory_backend.py` (dev)
- `memsi/digest.py` — ranking and token budget for the session-start digest
- `memsi/web/` — local dashboard (inbox, digest preview, browse, timeline)
- `memsi/cli.py` — `memctl`
- `memsi/mcp_server.py` — MCP tools; descriptions carry the behavioural contract
