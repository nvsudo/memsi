# Roadmap

Living document. Move items between sections as they start and finish; add the date when something ships. The epics referenced are in [DESIGN.md](DESIGN.md) section 1a.

## Phase 1: the owner (single tenant, local clients)

### Done
- [x] 2026-10-02 Design, user stories, decisions (raw Redis 8, in-chat approval, Claude Code + Desktop first, Python, bge-small later, Redis Cloud free tier)
- [x] 2026-10-03 Core service with the one write path: propose, dedup, neighbours, confirm, supersede, reject, retract, edit, expiry
- [x] 2026-10-03 Redis backend (JSON + Search + Stream, owner prefix) and in-process dev backend
- [x] 2026-10-03 Dashboard: inbox with neighbours and supersede, digest preview with ranking and per-app read filter, browse and edit, timeline
- [x] 2026-10-03 `memctl` CLI incl. export, import, reindex, seed
- [x] 2026-10-03 MCP server with seven tools; descriptions carry the protocol; works on mcp SDK 1.x and 2.x
- [x] 2026-10-03 Connected to Redis Cloud 8.6.2; latency measured (epic 10)
- [x] 2026-10-03 Nightly export via launchd, keep 30, last export shown in stats (epic 10)
- [x] 2026-10-03 Claude Code: SessionStart hook injects digest; MCP server registered at user scope (epics 1, 2, 3)
- [x] 2026-10-03 Claude Desktop MCP config; `memory` skill with `/memory` subcommands; `scripts/install-claude.sh`

### Next
- [ ] Semantic embedder as default (bge-small in-process), then `memctl reindex` (fixes lexical false matches; epic 4)
- [ ] Pipeline the writes in propose and confirm (4 round trips to 1 or 2)
- [ ] Cache the recall digest with a short TTL, invalidate on approval (SessionStart hook becomes one GET)
- [ ] Dashboard: health card (bytes vs plan cap, last export, ping, embedder) and config editor for feedback params (epics 7, 9)
- [ ] Claude Code auto-memory two-way sync through the gate, with hash manifest and loop prevention (epic 8)
- [ ] Stop hook: remind the model to propose anything durable from the session (decide: reminder vs headless extraction)
- [ ] Import from claude.ai memory export and in-chat "propose everything you remember" (epic 8)
- [ ] Tool-description and instructions pass: tighten wording after a week of real use

### Later in phase 1
- [ ] `memctl doctor`: connection, index dim vs embedder, backups age, hook and MCP registration present
- [ ] Sensitive-content guard in propose (refuse obvious secrets, card numbers, IDs)
- [ ] Per-type TTL and decay enforcement (config exists, not enforced)
- [ ] Thin TUI inbox, only if wanted

## Phase 2: the adopter and the operator (copy for others)
- [ ] Config template and installer that stands up an isolated owner store in 15 minutes (epic 11)
- [ ] Remote MCP (streamable HTTP) with OAuth so claude.ai and ChatGPT connect; read filters per app enforced server-side (epic 12)
- [ ] Slack approval buttons as an alternative to in-chat (epic 12)
- [ ] Structured feedback: which feedback params adopters loosen and tighten
- [ ] Upgrade path to the paid 250 MB plan documented and tested (backups, replication)

## Phase 3: the team and the company
- [ ] `team:<slug>` scope with its own approvers (epic 13)
- [ ] Admin policy: per-tool sensitivity ceilings, cross-user audit, per-owner isolation with Redis ACLs (epic 14)
- [ ] Storage backend swap to Redis Agent Memory (Iris) without client changes (epic 15)

## Deliberately not doing
- An LLM inside the server. The calling model is the judge; the server stays embeddings plus Redis.
- Building on the deprecated open-source Agent Memory Server.
- Writing to claude.ai or ChatGPT memory directly. No API exists; the digest in every conversation is the only channel.
