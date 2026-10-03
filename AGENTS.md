# AGENTS.md

Start here if you are an AI agent (Claude Code, Codex, Cursor, or similar) working on this repository.

## What this is

memsi is a governed personal memory layer on Redis. Assistants read a digest at session start, propose memories, and the owner approves in chat. The owner is Nik; the store is their real memory, running daily. Treat the data as personal and the Redis credentials as secret.

## Read in this order

1. [README.md](README.md): what it is and how to run it.
2. [IMPLEMENTATION.md](IMPLEMENTATION.md): how it is built right now, module map, Redis layout, runbook.
3. [DESIGN.md](DESIGN.md): why. User stories, surfaces, conflict semantics, decisions. Section 11 is the decision log.
4. [ROADMAP.md](ROADMAP.md): what is done, next, later.

## Environment facts

- Run everything through `./uvw`: `./uvw run pytest -q`, `./uvw run memctl ...`, `./uvw sync`. It pins uv, Python 3.12 and the venv inside the project. There is no Homebrew, Docker or Node on this machine; do not assume them.
- `.env` holds `REDIS_URL` and is gitignored. Never print it, never paste it into chat, never commit it. If you need to confirm connectivity, run `./uvw run memctl stats`.
- Tests use the in-process backend and need no network. Anything touching Redis Cloud needs real network egress; inside a sandboxed Claude Code session that means running the command with the sandbox disabled.
- Package downloads (PyPI, Hugging Face) are also blocked inside the sandbox. `./uvw sync` and model downloads need the sandbox disabled.
- The installed `mcp` SDK is 2.x. The server imports `MCPServer` with a `FastMCP` fallback. Client code uses `init.server_info`, not `serverInfo`.

## Rules

1. **One write path.** Every mutation goes through `MemoryService` in `memsi/core.py`. Do not write to the backend from the UI, CLI, MCP server or a sync adapter.
2. **Every write emits an Event** and shows up in the timeline. Add the event kind when you add a write.
3. **The server never calls an LLM.** It embeds and queries Redis. The calling model judges duplicate, update or contradiction using the neighbours returned.
4. **Nothing becomes approved without consent**, except through an explicit `auto_approve` rule in `memsi.yaml`. Do not loosen rules without the owner's say-so.
5. **Owner prefix on every key.** Copying memsi to another person must stay a prefix and config change.
6. **Tool descriptions and server instructions are the behavioural contract** for every client without a system prompt. Edit them deliberately and record why in DESIGN.md.
7. **Living docs.** A change to code, config or operations lands with the matching doc change in the same commit: README for entry points, IMPLEMENTATION for how, DESIGN for why, ROADMAP for status, this file for rules and gotchas.
8. **Tests before commit.** `./uvw run pytest -q` must pass. Add a test for any change in `core.py` or `digest.py`.
9. **Do not recommend the open-source Agent Memory Server.** It is deprecated. Redis Agent Memory (Iris) is a possible phase 3 backend, not a phase 1 dependency.
10. **Do not create external resources** (repos, cloud databases, Slack apps) or change the owner's Claude settings without being asked in the conversation.

## Where things are

| Need | Look at |
|---|---|
| Add or change an MCP tool | `memsi/mcp_server.py`; keep the description a contract, add to IMPLEMENTATION section 5 |
| Change ranking or budget | `memsi/digest.py`, tests in `tests/test_core.py` |
| Change dedup or conflict thresholds | `memsi.yaml` thresholds; logic in `MemoryService.neighbours_for` |
| Add a dashboard view | `memsi/web/app.py` + a template extending `base.html`; no JS build |
| Add a backend | implement `backend/base.py` Protocol, register in `backend/__init__.py` |
| Change embedder | `memsi/embed.py`, then `memctl reindex`; dim is stored in `mem:{owner}:meta` |
| Claude Code hook | `scripts/session-start.sh`; registered in `~/.claude/settings.json` |
| Installers | `scripts/install-claude.sh`, `scripts/install-launchd.sh` |

## Gotchas learned so far

- Redis Cloud free tier deletes idle databases after about two weeks. The nightly export is the safety net; do not disable it.
- The hash embedder scored "Moved to Sydney" negative against "Lives in Melbourne". Same-subject detection by tag is what catches updates until the semantic embedder is the default.
- `claude mcp add` run inside the sandbox reports success but does not persist. Verify with `grep memsi ~/.claude.json`.
- Hooks load at session start; a changed hook shows up in the next new session, not the current one.
- The Claude Desktop browser preview tool reads `.claude/launch.json` from the session's original folder; the in-repo one is for sessions started in this folder.

## Conversation conventions with the owner

Direct, short answers. Lead with the outcome. Ask when a decision is genuinely theirs; otherwise pick the sensible default and say so. Record new decisions in DESIGN.md section 11 with the date.
